import dash_bootstrap_components as dbc
from utils import projects_df

from dash import html

def build_accordion_items(is_coordinator, active_indices, coordinator_indices):

    if is_coordinator:
        data = projects_df.iloc[coordinator_indices]
    else:
        data = projects_df.iloc[active_indices]

    accordion_items = []
    for _, row in data.iterrows():
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
                    className="text-primary", style={'fontSize': '0.8rem', 'textDecoration': 'none'}),
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