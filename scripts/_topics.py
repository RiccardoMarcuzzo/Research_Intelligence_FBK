import plotly.graph_objects as go

from dash import dcc, html
from utils import labels_pkl, org_topics_df, TOPIC_IDS, TOPIC_EMBS, EU_COUNTRY_CODES

import numpy as np
import pandas as pd
import torch
import io
from sklearn.metrics.pairwise import cosine_similarity

from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

_rank_tokenizer = None
_rank_model = None

topic_names = labels_pkl.values()
def update_dropdown(search_value):
    filtered = [t for t in topic_names if search_value.lower() in t.lower()][:20]
    return [{'label': top, 'value': top} for top in filtered]

def get_rank_model():
    global _rank_tokenizer, _rank_model
    if _rank_model is None:
        print("Caricamento RANK model...")  # utile per il log del server
        _rank_tokenizer = AutoTokenizer.from_pretrained('data/specter2-onnx')
        _rank_model = ORTModelForFeatureExtraction.from_pretrained(
            'data/specter2-onnx', provider='CPUExecutionProvider'
        )
    return _rank_tokenizer, _rank_model

def normalize_score(score):
    return (score - np.min(score)) / (np.max(score) - np.min(score) + 1e-9)

def suggest_topic(query):
    query = query.title().strip()
    if query == '':
        return []
    elif query in topic_names:
        return [query]
    else:
        tokenizer, model = get_rank_model()
        inputs = tokenizer(
            query,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512
        )
        
        inputs.pop("token_type_ids", None)

        with torch.no_grad():
            output = model(**inputs)
        
        query_emb = output.last_hidden_state[:, 0, :].numpy()
        
        cos_scores = cosine_similarity(query_emb, TOPIC_EMBS)[0]
        final_scores = normalize_score(cos_scores)

        best_indices = np.argsort(final_scores)[::-1][:3]
        
        return [TOPIC_IDS[idx] for idx in best_indices]

def populate_kpis(project_df):

    tot_proj = str(project_df['projectIDs'].explode().nunique())

    eur = project_df['netEcContribution'].sum()
    tot_eur = f'{round(eur / 1_000_000, 1)} M'

    tot_publ = str(project_df['scopusID'].explode().nunique())

    tot_org = str(project_df['organisationID'].nunique())

    return tot_proj, tot_eur, tot_publ, tot_org


def show_info(selected_topic, metric='n_progetti', fp_list=[], country_list=[], n_orgs=0, is_1=True):
    # STEP 1: Filtra progetti per topic
    topics_data = org_topics_df.copy()
    
    # STEP 2: Filtra per Framework Programme
    proj_filtered = topics_data[topics_data['fp'].isin(fp_list)]
   
    # STEP 3: Verifica se ci sono progetti dopo il filtro FP
    if proj_filtered.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"No organisations found for selected framework programme",
            xaxis_title='',
            yaxis_title='',
            annotations=[{
                'text': 'Try selecting different framework programmes',
                'xref': 'paper',
                'yref': 'paper',
                'x': 0.5,
                'y': 0.5,
                'showarrow': False,
                'font': {'size': 16, 'color': 'gray'}
            }]
        )
        return [dcc.Graph(figure=fig, config={'scrollZoom': True})], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    # STEP 4: Filtra per Country
    if 'ALL' not in country_list:
        if 'EU' in country_list:
            country_list_expanded = [c for c in country_list if c != 'EU'] + EU_COUNTRY_CODES
            proj_filtered = proj_filtered[proj_filtered['country_code'].isin(country_list_expanded)]
        else:
            proj_filtered = proj_filtered[proj_filtered['country_code'].isin(country_list)]
    
    if proj_filtered.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"No organisations found for selected countries",
            annotations=[{
                'text': 'Try selecting different countries',
                'xref': 'paper',
                'yref': 'paper',
                'x': 0.5,
                'y': 0.5,
                'showarrow': False,
                'font': {'size': 16, 'color': 'gray'}
            }]
        )

        return [dcc.Graph(figure=fig, config={'scrollZoom': True})], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    mask_topics = proj_filtered['topic_name_hierarchy'].apply(
        lambda topics: selected_topic in set(topics))
    proj_filtered = proj_filtered[mask_topics]
    
    # STEP 5: Aggrega per organizzazione secondo la metrica
    org_stats = proj_filtered.groupby('name').agg({
        'n_proj': 'sum',
        'netEcContribution': 'sum',
        'n_publ': 'sum'
    }).reset_index()
    org_stats['custom_hover'] = (
        '<b>' + org_stats['name'] + '</b><br><i>' +
        org_stats['n_proj'].astype(str) + ' projects<br>' +
        org_stats['netEcContribution'].astype(str) + ' € funded<br>' +
        org_stats['n_publ'].astype(str) + ' publications</i>' +
        '<extra></extra>'
    )   
    
    if metric == 'n_progetti':
        x_label = 'Number of projects'
        
        org_stats = org_stats.drop(columns=['netEcContribution', 'n_publ'])
        org_stats.rename(columns={'n_proj': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)

    elif metric == 'euro_finanziamenti':
        x_label = 'Funding amount (€)' 
        
        org_stats = org_stats.drop(columns=['n_proj', 'n_publ'])
        org_stats.rename(columns={'netEcContribution': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)

    else: # metric == 'n_publ'
        x_label = 'Number of publications'
        
        org_stats = org_stats.drop(columns=['n_proj', 'netEcContribution'])
        org_stats.rename(columns={'n_publ': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)
       
    # STEP 7: Crea il grafico
    fig = go.Figure(data=[
        go.Bar(
            x=top_10['value'],
            y=top_10['name'],
            orientation='h',
            marker=dict(
                color=top_10['value'],
                colorscale='greens',
                showscale=False,
                colorbar=dict(title=x_label)
            ),
            hovertemplate=top_10['custom_hover']
        )
    ])
    
    fig.update_layout(
        title=f"Top {n_orgs} Players in <b>{selected_topic}</b>",
        xaxis_title=x_label,
        dragmode=False,
        xaxis_fixedrange=True,
        yaxis_fixedrange=True,
        height=max(150, 35*len(top_10)) if is_1 else max(150, 30*len(top_10)),
        margin=dict(l=20, r=20, t=60, b=40),
        hovermode='closest',
    )
    tot_proj, tot_eur, tot_publ, tot_org = populate_kpis(proj_filtered)

    return [dcc.Graph(figure=fig, config={'scrollZoom': False})], proj_filtered.to_json(orient='split'), tot_proj, tot_eur, tot_publ, tot_org

def join_topics(topics1_orgs, topics2_orgs, metric, n_orgs):
    topics1_orgs = pd.read_json(io.StringIO(topics1_orgs), orient='split')
    topics2_orgs = pd.read_json(io.StringIO(topics2_orgs), orient='split')

    common_names = set(topics1_orgs['name']) & set(topics2_orgs['name'])
    if not common_names:
        return html.P("No organisations in common.", className="text-muted fst-italic")
    proj_filtered = pd.concat([
        topics1_orgs[topics1_orgs['name'].isin(common_names)],
        topics2_orgs[topics2_orgs['name'].isin(common_names)]
    ])
    
    org_stats = proj_filtered.groupby('name').agg({
        'n_proj': 'sum',
        'netEcContribution': 'sum',
        'n_publ': 'sum'
    }).reset_index()
    org_stats['custom_hover'] = (
        '<b>' + org_stats['name'] + '</b><br><i>' +
        org_stats['n_proj'].astype(str) + ' projects<br>' +
        org_stats['netEcContribution'].astype(str) + ' € funded<br>' +
        org_stats['n_publ'].astype(str) + ' publications</i>' +
        '<extra></extra>'
    )   

    if metric == 'n_progetti':
        x_label = 'Number of projects'
        
        org_stats = org_stats.drop(columns=['netEcContribution', 'n_publ'])
        org_stats.rename(columns={'n_proj': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)

    elif metric == 'euro_finanziamenti':
        x_label = 'Funding amount (€)' 
        
        org_stats = org_stats.drop(columns=['n_proj', 'n_publ'])
        org_stats.rename(columns={'netEcContribution': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)

    else: # metric == 'n_publ'
        x_label = 'Number of publications'
        
        org_stats = org_stats.drop(columns=['n_proj', 'netEcContribution'])
        org_stats.rename(columns={'n_publ': 'value'}, inplace=True)
        top_10 = org_stats.nlargest(n_orgs, 'value').sort_values('value', ascending=True)
   
    # STEP 7: Crea il grafico
    fig = go.Figure(data=[
        go.Bar(
            x=top_10['value'],
            y=top_10['name'],
            orientation='h',
            marker=dict(
                color=top_10['value'],
                colorscale='greens',
                showscale=False,
                colorbar=dict(title=x_label)
            ),
            hovertemplate=top_10['custom_hover']
        )
    ])
    
    fig.update_layout(
        title=f"Top {n_orgs} Players in both topics",
        xaxis_title=x_label,
        yaxis_title='Organisation',
        dragmode=False,
        xaxis_fixedrange=True,
        yaxis_fixedrange=True,
        height=30*len(top_10),
        margin=dict(l=20, r=20, t=60, b=40),
        hovermode='closest',
    )
   
    return [dcc.Graph(figure=fig, config={'scrollZoom': False})]

def polish_df(df:pd.DataFrame, topic_name):
    df = df.drop(columns=['topic_name_hierarchy', 'n_proj', 'n_publ'])
    df['topic_name'] = topic_name

    df = df.explode('projectIDs').reset_index(drop=True)
    df = df.rename(columns={'projectIDs': 'projectID', 'name': 'org_name'})
    df = df.drop_duplicates(subset=['organisationID', 'projectID']).reset_index(drop=True)

    return df

def download_file(top1, top2, name_top1, name_top2, is_csv=True):
    topics1 = pd.read_json(io.StringIO(top1), orient='split')
    topics2 = pd.read_json(io.StringIO(top2), orient='split')

    topics1 = polish_df(topics1, name_top1)
    topics2 = polish_df(topics2, name_top2)

    final_df = pd.concat([topics1, topics2], ignore_index=True)

    return final_df
