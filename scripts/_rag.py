import torch
import re
import numpy as np
import dash_bootstrap_components as dbc
from sklearn.metrics.pairwise import cosine_similarity
from dash import html

from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

from utils import org_topics_df, projects_df, RAG_EMBS

THRESHOLD = 0.6
_rag_tokenizer = None
_rag_model = None

org_names_countries = org_topics_df[['name', 'country_code']].drop_duplicates()
def update_dropdown(search_value, country_list):
    
    df = org_names_countries

    if not country_list:
        mask = True
    else:
        mask = df['country_code'].isin(country_list)

    mask &= df['name'].str.contains(search_value, case=False, na=False)
    filtered = df.loc[mask, 'name'].head(20)

    return [{'label': org, 'value': org} for org in filtered]


def get_rank_model():
    global _rag_tokenizer, _rag_model
    if _rag_model is None:
        print("Caricamento RAG model...") 
        _rank_tokenizer = AutoTokenizer.from_pretrained('data/bge-m3-onnx')
        _rank_model = ORTModelForFeatureExtraction.from_pretrained(
            'data/bge-m3-onnx', provider='CPUExecutionProvider'
        )
    return _rank_tokenizer, _rank_model


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

def research_projects(*args):

    if not any(args):
        return['Enter your requests and click "Retrieve"']

    fp_list, country_list, org_list, topic_list, user_input = args

    mask = True

    if fp_list:
        mask &= projects_df['fp'].isin(fp_list)

    # Filtro geografico: bypassa countrylist se è presente almeno una organizzazione       
    if org_list:
        mask &= projects_df['participants'].apply(lambda x: bool(set(x) & set(org_list)))
    elif not country_list:
        pass   
    else:
        mask &= projects_df['participants_country_code'].apply(lambda x: bool(set(x) & set(country_list)))

    if topic_list:
        mask &= projects_df['topic_name_hierarchy'].apply(lambda x: bool(set(x) & set(topic_list)))

    if user_input:
        filtered_embs = RAG_EMBS[mask]

        query_emb = encode(user_input, max_length=8192).reshape(1, -1)
        cos_scores = cosine_similarity(query_emb, filtered_embs)[0]
        best_indices = np.argsort(cos_scores)[::-1][:20]

        valid_mask = cos_scores[best_indices] > THRESHOLD
        mask = best_indices[valid_mask]

    filtered_projects = projects_df.loc[mask].head(20)

    if filtered_projects.empty:
        return['No projects found. Try different filters.']
     
    accordion_items = []
    for _, row in filtered_projects.iterrows():
        cordis_url = f"https://cordis.europa.eu/project/id/{row['projectID']}"

        proj_fp = 'Horizon 2020' if row['fp'] == 8 else 'Horizon Europe'

        proj_hier = ' → '.join([t for t in row['topic_name_hierarchy'] if t != 'Unlabelled'])
        
        header = html.Div([
            html.Span(row['title'], style={'fontWeight': '600'}),
            html.Div([
                html.Small(f"{proj_fp}  ·  {proj_hier}", className="text-muted"),
                html.Br(),
                html.A("View on CORDIS ↗", href=cordis_url, target="_blank",
                    className="text-danger", style={'fontSize': '0.8rem', 'textDecoration': 'none'}),
            ], className="mt-1")
        ])

        body = html.Div([
            html.P([html.Strong("Participants: "), ', '.join(row['participants'])]),
            html.P([html.Strong("Objective: "), row['objective']]),
        ])

        accordion_items.append(
            dbc.AccordionItem(body, title=header, item_id=str(row['projectID']))
        )

    return [dbc.Accordion(accordion_items, flush=True, always_open=True, start_collapsed=True, style={'borderRadius': '8px', 'overflow': 'hidden'}, class_name='projects-accordion')]