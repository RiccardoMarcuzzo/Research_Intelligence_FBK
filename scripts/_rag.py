import torch
import numpy as np
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

from utils import org_topics_df, projects_df, RAG_EMBS

THRESHOLD = 0.55
_rag_tokenizer = None
_rag_model = None

org_names_countries = org_topics_df[['name', 'country_code', 'activityType']].drop_duplicates() 
def update_dropdown(search_value, country_list, typeorg_list):
    
    df = org_names_countries

    mask = True
    if country_list:
        mask &= df['country_code'].isin(country_list)
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

    active_indices = np.arange(len(projects_df))

    if fp_list:
        match = projects_df['fp'].isin(fp_list).to_numpy()
        active_indices = active_indices[match[active_indices]]

    # Filtro geografico: bypassa countrylist e typeorglist se è presente almeno una organizzazione       
    if org_list:
        match = projects_df['participants'].apply(lambda x: bool(set(x) & set(org_list))).to_numpy()
        active_indices = active_indices[match[active_indices]]
    else: # TODO: i due filtri non funzionano in sinergia, perché basta che 1 partecipante sia di un certo type (anche se di un'altra nazione) e il filtro sul type_org restituisce comunque True
        if country_list:
            match = projects_df['participants_country_code'].apply(lambda x: bool(set(x) & set(country_list))).to_numpy()
            active_indices = active_indices[match[active_indices]]
        if typeorg_list:
            match = projects_df['participants_type_org'].apply(lambda x: bool(set(x) & set(typeorg_list))).to_numpy()
            active_indices = active_indices[match[active_indices]]
        pass

    if topic_list:
        match = projects_df['topic_name_hierarchy'].apply(lambda x: bool(set(x) & set(topic_list))).to_numpy()
        active_indices = active_indices[match[active_indices]]

    if user_input:
        filtered_embs = RAG_EMBS[active_indices]
        query_emb = encode(user_input, max_length=8192).reshape(1, -1)
        cos_scores = (filtered_embs @ query_emb.T).ravel()
   
        valid = cos_scores > THRESHOLD
        original_indices = np.where(valid)[0]
        best_indices = np.argsort(cos_scores[original_indices])[::-1]
        best_indices = original_indices[best_indices]

        active_indices = active_indices[best_indices]

    filtered_projects = projects_df.iloc[active_indices]
    if filtered_projects.empty:
        return ''
    
    return filtered_projects.reset_index().to_json(orient='records')