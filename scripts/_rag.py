import torch
import numpy as np
import pandas as pd
import dash_bootstrap_components as dbc
from dash import html, dcc
import plotly.express as px
import plotly.graph_objects as go

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

def build_accordion_items(*args):

    fp_list, country_list, typeorg_list, org_list, topic_list, user_input = args

    active_indices = np.arange(len(projects_df))

    if fp_list:
        match = projects_df['fp'].isin(fp_list).to_numpy()
        active_indices = active_indices[match[active_indices]]

    # Filtro geografico: bypassa countrylist se è presente almeno una organizzazione       
    if org_list:
        match = projects_df['participants'].apply(lambda x: bool(set(x) & set(org_list))).to_numpy()
        active_indices = active_indices[match[active_indices]]
    else:
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
        return [], 0

    accordion_items = []
    for _, row in filtered_projects.iterrows():
        cordis_url = f"https://cordis.europa.eu/project/id/{row['projectID']}"
        proj_fp = 'Horizon 2020' if row['fp'] == 8 else 'Horizon Europe'
        proj_hier = ' → '.join([t for t in row['topic_name_hierarchy'] if t != 'Unlabelled'])
        deliverables = [
            html.A(f'Deliverable {n} ↗', href=link, target="_blank", style={'marginRight': '12px', 'color': '#1a5276'})
            for n, link in enumerate(row['physUrl'])
        ]
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
            html.P([html.Strong("Deliverables:  "), *deliverables]) if deliverables else '',
            html.P([html.Strong("Publications: "), 'TO-DO'])        
        ], style={'textAlign': 'left'})
        accordion_items.append(
            dbc.AccordionItem(body, title=header, item_id=str(row['projectID']))
        )
    
    return accordion_items, len(accordion_items)

def build_aggregated_view(*args):
# 1. DATI FITTIZI (Simulazione Horizon Europe)
    df_countries = pd.DataFrame({
        "Stato": ["Germania", "Francia", "Italia", "Spagna", "Olanda"],
        "Progetti": [124, 110, 98, 85, 62]
    }).sort_values(by="Progetti")

    df_org_types = pd.DataFrame({
        "Tipo": ["Università (HES)", "Ricerca (REC)", "Privati (PRC)", "Pubblici (PUB)"],
        "Budget": [45000000, 32000000, 28000000, 10000000]
    })

    # Metriche per il cruscotto
    total_deliverables = 150
    completed_deliverables = 112
    completion_rate = (completed_deliverables / total_deliverables) * 100

    # 2. GRAFICO: Progetti per Stato (Bar Orizzontale)
    fig_bar = px.bar(
        df_countries, 
        x="Progetti", 
        y="Stato", 
        orientation='h',
        title="N. Progetti per Stato Membro",
        color="Progetti",
        color_continuous_scale="Viridis",
        template="plotly_white"
    )
    fig_bar.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=False)

    # 3. GRAFICO: Budget per Tipo Organizzazione (Pie)
    fig_pie = px.pie(
        df_org_types, 
        values='Budget', 
        names='Tipo', 
        title="Ripartizione Fondi per Tipo Organizzazione",
        hole=0.4
    )
    fig_pie.update_traces(textinfo='percent+label')
    fig_pie.update_layout(margin=dict(l=20, r=20, t=40, b=20))

    # 5. LAYOUT DASH
    return html.Div([
        html.H2("PROOF OF CONCEPT AGGREGATED VIEW ", 
                style={'textAlign': 'center', 'color': '#2c3e50', 'fontFamily': 'Arial'}),
        
        # Statistiche rapide (KPI)
        html.Div([
            html.Div([
                html.B("Progetti Totali: "), "432"
            ], style={'padding': '15px', 'border': '1px solid #ddd', 'borderRadius': '5px', 'color': 'black'}),
            html.Div([
                html.B("Budget Totale: "), "€ 115M"
            ], style={'padding': '15px', 'border': '1px solid #ddd', 'borderRadius': '5px'}),
        ], style={'display': 'flex', 'gap': '20px', 'justifyContent': 'center', 'marginBottom': '30px', 'color': 'black'}),

        # Griglia Grafici
        html.Div([
            html.Div([dcc.Graph(figure=fig_bar)], style={'width': '48%'}),
            html.Div([dcc.Graph(figure=fig_pie)], style={'width': '48%'})
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'flexWrap': 'wrap'}),
               
    ], style={'padding': '30px', 'backgroundColor': '#f4f7f9'})

def build_latent_space(has_input_text, *args):

    np.random.seed(42)
    
    # 1. GENERAZIONE COORDINATE (200 punti)
    x = np.random.normal(0, 1.5, 200)
    y = np.random.normal(0, 1.5, 200)
    
    # Definiamo i due gruppi: 150 Background, 50 Risultati
    group = ["Background"] * 150 + ["Risultato Ricerca"] * 50
    
    # Similarità (per il gradiente)
    similarity = np.concatenate([
        np.zeros(150),
        np.linspace(0.5, 1.0, 50)
    ])
    
    df = pd.DataFrame({
        'x': x,
        'y': y,
        'Gruppo': group,
        'Similarity': similarity,
        'Project': [f"Progetto ID: {i}" for i in range(200)],
        'Size': [6 if g == "Background" else 12 for g in group]
    })

    # 2. LOGICA DI COLORAZIONE
    if has_input_text:
        # CASO TRUE: Gradiente Giallo -> Rosso
        custom_colorscale = [
            [0.0, "#E0E0E0"],   # Grigio
            [0.49, "#E0E0E0"],  # Resta grigio fino ai match
            [0.5, "#FFFF00"],   # Giallo
            [1.0, "#FF0000"]    # Rosso
        ]
        
        fig = px.scatter(
            df, x='x', y='y',
            color='Similarity',
            size='Size',
            hover_name='Project',
            color_continuous_scale=custom_colorscale,
            title="Mappa Semantica: Analisi Similarità",
            template="plotly_white",
            size_max=12
        )
        fig.update_layout(coloraxis_colorbar=dict(title="Similarità"))
        
    else:
        # CASO FALSE: Colori fissi (Grigio e Arancione)
        fig = px.scatter(
            df, x='x', y='y',
            color='Gruppo',
            size='Size',
            hover_name='Project',
            color_discrete_map={
                "Background": "#E0E0E0",
                "Risultato Ricerca": "#FF8C00" # Arancione
            },
            title="Mappa Progetti: Ricerca Standard",
            template="plotly_white",
            size_max=12
        )
        fig.update_layout(showlegend=True)

    # 3. PULIZIA ESTETICA COMUNE
    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        margin=dict(l=10, r=10, t=50, b=10),
        height=500,
        dragmode='pan'
    )
    
    fig.update_traces(marker=dict(line=dict(width=0.5, color='DimGray')))

    # Messaggio di stato
    status_text = "Visualizzazione basata sulla similarità testuale." if has_input_text else \
                  "Visualizzazione basata sui filtri di ricerca (nessun testo inserito)."

    return html.Div([
        html.Div([
            html.H3("PROOF OF CONCEPT LATENT SPACE", style={'color': 'black', 'marginBottom': '5px'}),
            html.P(status_text, style={'color': '#444', 'fontSize': '14px'})
        ], style={'padding': '15px'}),
        dcc.Graph(figure=fig)
    ], style={
        'backgroundColor': 'white', 
        'borderRadius': '15px', 
        'boxShadow': '0px 4px 20px rgba(0,0,0,0.1)',
        'margin': '20px'
    })