import dash
import dash_bootstrap_components as dbc
import scripts._organisations as script

from dash import html, dcc, Input, Output, State, callback
from utils import TITLE
from datetime import datetime


PAGE_TITLE = "Organisations"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/organisations',
    order=1
)

DEFAULT_ORG = 'Fondazione bruno kessler'
COMPARISON_ORG = 'Fondazione hub innovazione trentino'
#--------------------------------------------
# LAYOUT      
#--------------------------------------------
layout = dbc.Container(
    [
        # === SEARCH SECTION ===
        dbc.Row(
            [
                # === COLONNA SINISTRA: org card ===
                dbc.Col(
                    [
                        # KPI CARDS
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H4(id='tot-proj-org', className="fw-bold mb-1"),
                                            html.P("Projects", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H4(id='tot-eur-org', className="fw-bold mb-1"),
                                            html.P("Funding", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H4(id='tot-publ-org', className="fw-bold mb-1"),
                                            html.P("Publications", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H4(id='tot-tops-org', className="fw-bold mb-1"),
                                            html.P("Topics", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                            ],
                            className="g-2 mb-3",
                        ),

                        # ORG CARD
                        html.Div(id='org1-card-container', className='mt-2'),
                
                        dcc.Store(id='org1-topics'),
                        dcc.Store(id='org1-data')
                    ],
                    width=5
                ),

                # === COLONNA CENTRALE: confronto org
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            
                            # SEARCH
                            html.Label(
                                "Compare with a different organisation",
                                className="form-label fw-semibold mb-2",
                                style={'fontSize': '0.95rem'}
                            ),
                            dcc.Dropdown(
                                id='org2-dropdown',
                                options=[COMPARISON_ORG],
                                value=COMPARISON_ORG,
                                placeholder='Start typing to search...',
                                searchable=True,
                                className='mb-0'
                            ),

                            # KPI CARDS
                            dbc.Row([
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H5(id='tot-proj-2-org', className="fw-bold mb-1"),
                                            html.P("Projects", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H5(id='tot-eur-2-org', className="fw-bold mb-1"),
                                            html.P("Funding", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H5(id='tot-publ-2-org', className="fw-bold mb-1"),
                                            html.P("Publications", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H5(id='tot-tops-2-org', className="fw-bold mb-1"),
                                            html.P("Topics", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                            ], className="g-2 mb-2 mt-3"),

                            # ORG CARD
                            html.Div(id='org2-card-container', className='mt-2'),

                            dcc.Store(id='org2-topics'),
                            dcc.Store(id='org2-data'),

                            # ORGS COLLABORATION
                            html.H5('Joint Projects:', className='mt-2'),
                            html.Div(id='orgs-collaborations', className='mt-2')
                        ]),
                        
                        className='border-0 shadow-sm rounded-3',
                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                    ),
                    width=4,
                ),

                # === COLONNA DESTRA: search + filters ===
                dbc.Col([
                    dbc.Card(
                        dbc.CardBody([

                            # SEARCH
                            dcc.Dropdown(
                                id='org1-dropdown',
                                options=[DEFAULT_ORG],
                                value=DEFAULT_ORG,
                                placeholder='Start typing to search...',
                                searchable=True,
                                className='mb-0'
                            ),

                            # DIVIDER
                            html.Hr(className="my-2"),

                            # FILTERS
                            html.Div(
                                id='filters-container',
                                children=[
                                    html.Div([
                                        html.Label("Ranking metric", className="form-label fw-semibold mb-2",
                                                style={'fontSize': '0.9rem'}),
                                        dbc.RadioItems(
                                            id='metric-filter-org',
                                            options=[
                                                {'label': 'Number of projects', 'value': 'n_progetti'},
                                                {'label': 'Funding amount', 'value': 'euro_finanziamenti'},
                                                {'label': 'Number of publications', 'value': 'n_publ'}
                                            ],
                                            value='n_progetti',
                                            className='mb-3'
                                        ),
                                    ], className="mb-3"),

                                    html.Div([
                                        html.Label("Framework Programme", className="form-label fw-semibold mb-2",
                                                style={'fontSize': '0.9rem'}),
                                        dcc.Dropdown(
                                            id='fp-filter-org',
                                            options=[
                                                {'label': 'Horizon 2020', 'value': 8},
                                                {'label': 'Horizon Europe', 'value': 9}
                                            ],
                                            value=[8, 9],
                                            multi=True,
                                            placeholder='Select Framework Programmes...',
                                            className='mb-3'
                                        ),
                                    ], className="mb-3"),

                                    dbc.Button(
                                        "Reset Filters",
                                        id='reset-filters-btn-org',
                                        size="sm",
                                        className="w-100",
                                        color="primary"
                                    )
                                ],
                            ),                                              
                        ]),
                        className='border-0 shadow rounded-3',
                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'} 
                    ),

                    # INFO AND DOWNLOAD
                    dbc.Card(
                        dbc.CardBody([
                        html.P([
                            "Looking for more details about this tool? See the ",
                            dcc.Link([
                                'documentation.',
                                html.I(className="bi bi-box-arrow-up-right ms-2")
                            ], href='concept', className='text-decoration-none link-primary')
                        ]),
                        html.P([
                            "Do you want to export this page?",
                        ]),
                        dbc.Col([
                            dbc.Button(
                                    "Download CSV",
                                    id='download-orgs-csv-btn',
                                    size="sm",
                                    outline=True,
                                    className="w-100",
                                    color="primary"
                                ),
                            dcc.Download(id='download-orgs-csv')
                            ]),
                        ]),
                        className='border shadow rounded-3 mt-3',
                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                    )],
                    width=3,
                ),
            ],
            className='g-2 mt-2',
        ),
            
        dcc.Store(id='org-data'),
    ],
    id="orgs-page",
    fluid=True,
    className="px-4"
)

#--------------------------------------------
# CALLBACK    
#--------------------------------------------
# === ORG1 callbacks ===
@callback(
    Output('org1-dropdown', 'options'),
    Input('org1-dropdown', 'search_value'),
    prevent_initial_call=True
)
def update_dropdown_org1(search_value):
    if not search_value:
        raise dash.exceptions.PreventUpdate
    return script.update_dropdown(search_value)

@callback(
    Output('org1-card-container', 'children'),
    Output('org1-topics', 'data'),
    Output('org1-data', 'data'),
    Output('tot-proj-org', 'children'),
    Output('tot-eur-org', 'children'),
    Output('tot-publ-org', 'children'),
    Output('tot-tops-org', 'children'),
    Input('org1-dropdown', 'value'),
    Input('metric-filter-org', 'value'),
    Input('fp-filter-org', 'value'),
)
def show_info_org1(selected_org, metric, fp_list):
    if not selected_org:
        return [], None, None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    info_content, topics_data, org_data, tot_proj, tot_eur, tot_publ, times_cp = script.show_info(
        selected_org=selected_org,
        metric=metric,
        fp_list=fp_list)

    return info_content, topics_data, org_data, tot_proj, tot_eur, tot_publ, times_cp

# === ORG2 callbacks ===
@callback(
    Output('org2-dropdown', 'options'),
    Input('org2-dropdown', 'search_value'),
    prevent_initial_call=True
)
def update_dropdown_org2(search_value):
    if not search_value:
        raise dash.exceptions.PreventUpdate
    return script.update_dropdown(search_value)

@callback(
    Output('org2-card-container', 'children'),
    Output('org2-topics', 'data'),
    Output('org2-data', 'data'),
    Output('tot-proj-2-org', 'children'),
    Output('tot-eur-2-org', 'children'),
    Output('tot-publ-2-org', 'children'),
    Output('tot-tops-2-org', 'children'),
    Input('org2-dropdown', 'value'),
    Input('metric-filter-org', 'value'),
    Input('fp-filter-org', 'value'),
)
def show_info_org2(selected_org, metric, fp_list):
    if not selected_org:
        return [], None, None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    info_content, topics_data, org_data, tot_proj, tot_eur, tot_publ, times_cp = script.show_info(
        selected_org=selected_org,
        metric=metric,      
        fp_list=fp_list,
        display_projects=False)
    
    return info_content, topics_data, org_data, tot_proj, tot_eur, tot_publ, times_cp

# === COLLABORATIONS ===
@callback(
    Output('orgs-collaborations', 'children'),
    Input('org1-topics', 'data'),
    Input('org2-topics', 'data')
)
def compare_orgs(org1_docs, org2_docs):
    if org1_docs and org2_docs and org1_docs != org2_docs:
        comparison = script.compare_organisations(org1_docs, org2_docs)
        return comparison
    return []

# === RESET FILTERS ===
@callback(
    Output('metric-filter-org', 'value'),
    Output('fp-filter-org', 'value'),
    Input('reset-filters-btn-org', 'n_clicks'),
    prevent_initial_call=True
)
def reset_filters(n_clicks):
    return 'n_progetti', [8, 9]

# === DOWNLOAD BUTTONS ===
@callback(
    Output('download-orgs-csv', 'data'),
    Input('download-orgs-csv-btn', 'n_clicks'),
    State('org1-data', 'data'),
    State('org2-data', 'data'),
    State('org1-dropdown', 'value'),
    State('org2-dropdown', 'value'),
    prevent_initial_call=True
)
def download_csv(n_clicks, org1, org2, name_org1, name_org2):
    df = script.download_file(org1, org2, name_org1, name_org2)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return dcc.send_data_frame(df.to_csv, f"{timestamp}.csv", index=False)

