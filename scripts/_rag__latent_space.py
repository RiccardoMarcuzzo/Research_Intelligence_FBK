import json
import pandas as pd
import numpy as np
import plotly.express as px

from dash import html, dcc

def build_latent_space(filtered_json, user_input):

    filtered_projects = pd.DataFrame(json.loads(filtered_json))

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
    if user_input:
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
    status_text = "Visualizzazione basata sulla similarità testuale." if user_input else \
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