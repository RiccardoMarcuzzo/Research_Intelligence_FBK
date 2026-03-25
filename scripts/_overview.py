import plotly.graph_objects as go
from dash import html

from utils import projects_df, topics_df, labels_pkl

def generate_treemap():
    # Define macro-cluster color mapping
    cluster_colors = {
        390: {'name': 'Social Sciences & Humanities', 'color': '#FF8C42'},
        394: {'name': 'Earth & Life Science', 'color': '#2D6A4F'},
        399: {'name': 'Engineering & Technology', 'color': '#6C757D'},
        396: {'name': 'Health & Medicine', 'color': '#1E88E5'},
        398: {'name': 'Physical & Mathematical Sciences', 'color': '#D32F2F'}
    }
    
    ids = []
    labels = []
    parents = []
    values = []
    colors = []
    
    for i in range(4, 0, -1):
        column = f'level_{i}'
        ts = [t for t in topics_df[column].unique() if t != -1]
        
        for elem in ts:
            # 1. CREIAMO UN ID UNIVOCO: concateniamo livello e ID
            # Anche se l'id 'elem' si ripete in più livelli, l'ID del nodo sarà diverso
            node_id = f"lvl{i}_{elem}"
            ids.append(node_id)
            
            # 2. LABEL: prendiamo il nome dal pickle
            labels.append(labels_pkl.get(elem, f'Topic {elem}'))
            
            # 3. VALORE
            values.append(topics_df[topics_df[column] == elem]['count'].sum())
            
            # 4. GENITORE: puntiamo all'ID univoco del livello superiore
            if i == 4:
                parents.append('')
            else:
                prec_column = f'level_{i+1}'
                # Trova il valore del genitore nel DF
                parent_val = topics_df[topics_df[column] == elem][prec_column].iloc[0]
                parents.append(f"lvl{i+1}_{parent_val}") # Punta all'ID univoco del padre
            
            # 5. COLORE (Logica level_4)
            l4_parent = topics_df[topics_df[column] == elem]['level_4'].iloc[0]
            base_color = cluster_colors.get(l4_parent, {'color': '#95A5A6'})['color']
            colors.append(base_color)

    # CREAZIONE FIGURA
    fig = go.Figure(go.Treemap(
        ids=ids,           # <--- FONDAMENTALE
        labels=labels,     # <--- Solo per estetica
        parents=parents,   # <--- Punta agli IDs
        values=values,
        branchvalues='total', # 'remainder' è più tollerante di 'total' per il debug
        marker=dict(colors=colors, line=dict(width=2, color='white')),
        texttemplate='<b>%{label}</b><br>%{percentEntry:.2%}',
        hovertemplate='<b>%{label}</b><br>Projects: %{value:,}<extra></extra>'
    ))
    
    # Update layout for better appearance
    fig.update_layout(
        margin=dict(t=25, l=10, r=10, b=10),
        paper_bgcolor='white',
        plot_bgcolor='white'
    )
    return fig

def populate_doc_canvas(proj_id):

    row = projects_df[projects_df['id'] == proj_id].iloc[0]
    title = row['title']

    return html.Div([
        html.P(title, style={
            'fontWeight': 'bold',
            'fontSize': '20px',
            'marginTop': '0',
            'marginBottom': '10px'
        }),
        html.P([
            html.Span('🔎 ', style={'marginRight': '4px'}),
            html.A('Search on Google',
                   href=f'https://www.google.com/search?q=CORDIS%20{title}',
                   target='_blank',
                   rel='noopener noreferrer',
                   style={'textDecoration': 'none','color': '#007BFF','fontWeight': 'bold'})
        ], style={'fontSize': '14px'}),
        html.P(['🇪🇺 ', html.Span('Framework Programme: ', style={'fontWeight': 'bold'}), row['fp']]),
        html.P(['💡 ', html.Span('Topic: ', style={'fontWeight': 'bold'}), row['topic_name']]),
        html.P(['🏢 ', html.Span('Participants: ', style={'fontWeight': 'bold'}), ', '.join(row['participants'])]),
        html.Hr(),
        html.P(['📝 Abstract'], style={'fontWeight': 'bold'}),
        html.P(row['objective'], style={'fontSize': '14px', 'lineHeight': '1.5'})
    ], style={'color': 'black'})

