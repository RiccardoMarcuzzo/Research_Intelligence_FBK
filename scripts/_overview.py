from dash import html

from utils import projects_tbl

def populate_doc_canvas(proj_id):
    safe_id = str(proj_id).replace("'", "''")

    row_arrow = (
        projects_tbl.search()
        .where(f"projectID = {safe_id}")
        .limit(1)
        .to_arrow()
    )

    row = row_arrow.to_pylist()[0]  # dict con tutte le colonne della riga
    title = row['title']
    proj_hier = ' → '.join([t for t in row['topic_name_hierarchy'] if t != 'Unlabelled'])

    return html.Div([
        html.P(title, style={
            'fontWeight': 'bold',
            'fontSize': '20px',
            'marginTop': '0',
            'marginBottom': '10px'
        }),
        html.P([
            html.Span('🔎 ', style={'marginRight': '4px'}),
            html.A('View on Cordis',
                   href=f'https://cordis.europa.eu/project/id/{proj_id}',
                   target='_blank',
                   rel='noopener noreferrer',
                   style={'textDecoration': 'none', 'color': '#007BFF', 'fontWeight': 'bold'})
        ], style={'fontSize': '14px'}),
        html.P(['🇪🇺 ', html.Span('Framework Programme: ', style={'fontWeight': 'bold'}), row['fp']]),
        html.P(['💡 ', html.Span('Topic: ', style={'fontWeight': 'bold'}), proj_hier]),
        html.P(['🏢 ', html.Span('Participants: ', style={'fontWeight': 'bold'}), ', '.join(row['participants'])]),
        html.Hr(),
        html.P(['📝 Abstract'], style={'fontWeight': 'bold'}),
        html.P(row['objective'], style={'fontSize': '14px', 'lineHeight': '1.5'})
    ], style={'color': 'black'})

