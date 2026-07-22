import torch
import numpy as np
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

from utils import projects_df, RAG_EMBS, org_projects_df

THRESHOLD = 0.55
_rag_tokenizer = None
_rag_model = None

org_names_countries = org_projects_df[['name', 'countryCode', 'activityType']].drop_duplicates() 
def update_dropdown(search_value, country_list, typeorg_list):
    
    df = org_names_countries

    mask = True
    if country_list:
        mask &= df['countryCode'].isin(country_list)
    if typeorg_list:
        mask &= df['activityType'].isin(typeorg_list)

    mask &= df['name'].str.contains(search_value, case=False, na=False)
    filtered = df.loc[mask, 'name'].head(20)

    return [{'label': org, 'value': org} for org in filtered]


def get_rank_model():
    global _rag_tokenizer, _rag_model
    if _rag_model is None:
        print("Caricamento RAG model...") 
        _rag_tokenizer = AutoTokenizer.from_pretrained('data/bge-m3-onnx')
        _rag_model = ORTModelForFeatureExtraction.from_pretrained(
            'data/bge-m3-onnx', provider='CPUExecutionProvider'
        )
    return _rag_tokenizer, _rag_model


def encode(text, max_length=8192):
    tokenizer, model = get_rank_model()

    inputs = tokenizer(
        text,
        max_length=max_length,
        padding=True,
        truncation=True,
        return_tensors='pt'
    )

    outputs = model(**inputs)
    
    embeddings = outputs.last_hidden_state[:, 0, :]
    
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
    
    return embeddings.detach().cpu().numpy()

def retrieve_active_indices(*args):
    fp_list, country_list, typeorg_list, org_list, topic_list, user_input = args

    filters = {
        'fp': fp_list,
        'countryCode': country_list,
        'activityType': typeorg_list,
        'name': org_list,
        'topic_name': topic_list,
    }
    mask = np.ones(len(org_projects_df), dtype=bool)
    for col, lst in filters.items():
        if lst:
            mask &= org_projects_df[col].isin(lst)

    masked_org = org_projects_df.loc[mask]
    valid_ids = set(masked_org['projectID'])
    coordinator_ids = set(masked_org.loc[masked_org['role'] == 'coordinator', 'projectID'])

    if not valid_ids:
        return [], [], {}

    match = projects_df['projectID'].isin(valid_ids).to_numpy()
    active_indices = np.where(match)[0]

    scores_by_project = {}
    if user_input and len(active_indices):
        filtered_embs = RAG_EMBS[active_indices]
        query_emb = encode(user_input, max_length=8192).reshape(1, -1)
        cos_scores = (filtered_embs @ query_emb.T).ravel()

        valid_mask = cos_scores > THRESHOLD
        if not valid_mask.any():
            return [], [], {}
        active_indices = active_indices[valid_mask]
        cos_scores = cos_scores[valid_mask]

        order = np.argsort(cos_scores)[::-1]
        active_indices = active_indices[order]
        cos_scores = cos_scores[order]

        matched_project_ids = projects_df['projectID'].to_numpy()[active_indices]
        scores_by_project = {
            str(pid): float(score) for pid, score in zip(matched_project_ids, cos_scores)
        }

    coordinator_match = projects_df['projectID'].isin(coordinator_ids).to_numpy()
    coordinator_match_set = set(np.where(coordinator_match)[0])

    coordinator_indices = [i for i in active_indices if i in coordinator_match_set]

    return active_indices, coordinator_indices, scores_by_project

def download_file(active_indices, country_list, typeorg_list, org_list):
    valid_projects = projects_df.iloc[active_indices]
    valid_project_ids = valid_projects['projectID'].tolist()

    data = org_projects_df[org_projects_df['projectID'].isin(valid_project_ids)].copy()

    if country_list:
        data = data[data['countryCode'].isin(country_list)]
    if typeorg_list:
        data = data[data['activityType'].isin(typeorg_list)]
    if org_list:
        data = data[data['name'].isin(org_list)]

    cols = [c for c in data.columns if c != "name"]
    cols.insert(2, "name")
    data = data[cols]

    final_data = data.merge(valid_projects[['projectID', 'title', 'physUrl']], on='projectID')
    final_data = final_data.rename(columns={'physUrl': 'deliverables'})

    return final_data