import pandas as pd
import numpy as np
import plotly.express as px
import plotly.colors as pc
from scipy.spatial.distance import cdist

from dash import html, dcc
from utils import projects_df, D2_RAG_EMBS, LATENT_SPACE_RADIUS

def spread_points(coords, strength=0.3, seed=1):
    rng = np.random.default_rng(seed)
    noise = np.random.normal(0, strength, coords.shape)
    return coords + noise

def build_latent_space(indices, user_input):

    graph_data = projects_df.iloc[indices].copy()
    graph_data['group'] = 'Research Result'
    graph_data['size'] = 12
    embs = D2_RAG_EMBS[indices]
    graph_data['x'] = embs[:, 0]
    graph_data['y'] = embs[:, 1]

    neighbor_sets = []
    for emb in embs:
        distances = cdist(D2_RAG_EMBS, [emb]).flatten()
        nearby = np.where(distances <= LATENT_SPACE_RADIUS)[0]
        neighbor_sets.append(nearby)

    # Unione di tutti i vicini, esclusi i punti già in indices
    neighbor_indices = np.setdiff1d(
        np.unique(np.concatenate(neighbor_sets)), 
        indices
    )

    neighbors = projects_df.iloc[neighbor_indices].copy()
    neighbors['group'] = 'Neighbours'
    neighbors['size'] = 6
    neighbors['x'] = D2_RAG_EMBS[neighbor_indices, 0]
    neighbors['y'] = D2_RAG_EMBS[neighbor_indices, 1]

    graph_data = pd.concat([neighbors, graph_data], ignore_index=True)

    vis_coords = spread_points(
        graph_data[['x', 'y']].values,
    )

    graph_data['x'] = vis_coords[:, 0]
    graph_data['y'] = vis_coords[:, 1]

    fp_map = {8: 'Horizon 2020', 9: 'Horizon Europe'}
    graph_data['custom_hover'] = graph_data['fp'].map(fp_map)
    graph_data['custom_hover'] = (
        '<b>' + graph_data['title'].astype(str) + '</b><br>' +
        graph_data['fp'].map(fp_map) + '<br>' +
        '<extra></extra>'
    )

    if user_input:
        graph_data['similarity'] = 0.0
        graph_data.loc[graph_data['group'] == 'Research Result', 'similarity'] = np.linspace(1.0, 0.2, len(indices))
        custom_colorscale = [
            [0.0, "#E0E0E0"],   # Grigio
            [0.19, "#E0E0E0"],  # Resta grigio fino ai match
            [0.2, "#FFFF00"],   # Giallo
            [0.85, "#FF0000"],  # Rosso
            [1.0, '#2D0054']    # Viola
        ]
        
        fig = px.scatter(
            graph_data, x='x', y='y',
            color='similarity',
            size='size',
            custom_data=['title','projectID'],
            range_color=[0.0,1.0],
            color_continuous_scale=custom_colorscale,
            template="plotly_white",
            size_max=12
        )
        fig.update_layout(coloraxis_colorbar=dict(title="Similarity"))
        colors = pc.sample_colorscale(custom_colorscale, graph_data['similarity'].values)
        fig.update_traces(hoverlabel=dict(bgcolor=colors))
        
    else:
        fig = px.scatter(
            graph_data, x='x', y='y',
            color='group',
            size='size',
            custom_data=['title','projectID'],
            color_discrete_map={
                "Neighbours": "#E0E0E0",
                "Research Result": "#FF8C00"
            },
            template="plotly_white",
            size_max=12
        )
        fig.update_layout(showlegend=True)

    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        margin=dict(l=10, r=10, t=50, b=10),
        height=500,
        dragmode='pan'
    )
    
    fig.update_traces(marker=dict(line=dict(width=0.5, color='DimGray')), 
                      hovertemplate="<b>%{customdata[0]}</b><br><i>Click to view on CORDIS</i><extra></extra>")

    # Messaggio di stato
    status_text = "Text-similarity-based view." if user_input else \
                "Filter-based view (no text entered)."

    return html.Div([
        html.Div([
            html.H3("LATENT SPACE SEARCH", style={'color': 'black', 'marginBottom': '5px'}),
            html.P(status_text, style={'color': '#444', 'fontSize': '14px'})
        ], style={'padding': '15px'}),
        dcc.Graph(figure=fig, id='latent-space-graph')
    ], style={
        'backgroundColor': 'white', 
        'borderRadius': '15px', 
        'boxShadow': '0px 4px 20px rgba(0,0,0,0.1)',
        'margin': '20px'
    })