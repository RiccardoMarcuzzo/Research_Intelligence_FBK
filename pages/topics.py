import dash
from datetime import datetime
import dash_bootstrap_components as dbc
import scripts._topics as script
from dash import html, dcc, Input, Output, State, callback
from utils import TITLE, COUNTRY_CODES, topic_names

PAGE_TITLE = "Topics"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/topics',
    order=2
)

DEFAULT_TOPIC = 'Natural Language Processing'
COMPARISON_TOPIC = 'Industrial Safety'
#--------------------------------------------
# LAYOUT      
#--------------------------------------------
layout = dbc.Container(
    [
        dbc.Row(
            [
                # === COLONNA SINISTRA+CENTRALE: topic card + comparison ===
                dbc.Col(
                    [
                        # KPI CARDS
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody([
                                            html.H4(id='tot-proj', className="fw-bold mb-1"),
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
                                            html.H4(id='tot-eur', className="fw-bold mb-1"),
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
                                            html.H4(id='tot-publ', className="fw-bold mb-1"),
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
                                            html.H4(id='tot-org', className="fw-bold mb-1"),
                                            html.P("Organisations", className="text-muted mb-0",
                                                style={'fontSize': '0.8rem'}),
                                        ], className="px-3 py-2"),
                                        className='border-0 shadow rounded-3',
                                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                    ),
                                ),
                            ],
                            className="g-2 mb-3",
                        ),

                        # SLIDE BAR
                        dcc.Slider(10, 50, 5, value=20, id='slider-orgs', className='mt-2'),

                        # TOPIC CARD
                        html.Div(id='topic-card-container', className='mt-2'),

                        # --- COMPARISON (ex colonna centrale) ---
                        dbc.Card(
                            dbc.CardBody([

                                # SEARCH
                                html.Label(
                                    "Compare with a different topic",
                                    className="form-label fw-semibold mb-2",
                                    style={'fontSize': '0.95rem'}
                                ),
                                dcc.Dropdown(
                                    id='topic2-dropdown',
                                    options=topic_names,
                                    value=COMPARISON_TOPIC,
                                    placeholder='Start typing to search...',
                                    searchable=True,
                                    className='mb-3'
                                ),

                                # KPI CARDS
                                dbc.Row([
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody([
                                                html.H5(id='tot-proj-2', className="fw-bold mb-1"),
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
                                                html.H5(id='tot-eur-2', className="fw-bold mb-1"),
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
                                                html.H5(id='tot-publ-2', className="fw-bold mb-1"),
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
                                                html.H5(id='tot-org-2', className="fw-bold mb-1"),
                                                html.P("Organisations", className="text-muted mb-0",
                                                    style={'fontSize': '0.8rem'}),
                                            ], className="px-3 py-2"),
                                            className='border-0 shadow rounded-3',
                                            style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                                        ),
                                    ),
                                ], className="g-2 mb-2 mt-3"),

                                # TOPIC CARD
                                html.Div(id='topic2-card-container', className='mt-2'),

                                # TOPIC COLLABORATION
                                html.H5('Intersecting organisations', className='mt-3'),
                                html.Div(id='topics-collaborations', className='mt-2')
                            ]),
                            className='border-0 shadow-sm rounded-3 mt-3',
                            style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                        ),
                    ],
                    width=9,
                ),

                # === COLONNA DESTRA: search + suggest + filters ===
                dbc.Col([
                    html.Div([
                        dbc.Card(
                            dbc.CardBody([

                                # SEARCH
                                dcc.Dropdown(
                                    id='topic-dropdown',
                                    options=topic_names,
                                    value=DEFAULT_TOPIC,
                                    placeholder='Start typing to search...',
                                    searchable=True,
                                    className='mb-3'
                                ),

                                # DIVIDER + HINT
                                html.Hr(className="my-2"),

                                # FILTERS
                                html.Div(
                                    id='filters-container',
                                    children=[
                                        html.Div([
                                            html.Label("Ranking metric", className="form-label fw-semibold mb-2",
                                                    style={'fontSize': '0.9rem'}),
                                            dbc.RadioItems(
                                                id='metric-filter',
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
                                                id='fp-filter',
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

                                        html.Div([
                                            html.Label("Country", className="form-label fw-semibold mb-2",
                                                    style={'fontSize': '0.9rem'}),
                                            dcc.Dropdown(
                                                id='country-filter',
                                                options=[
                                                    {'label': '🇪🇺 European Union (27 countries)', 'value': 'EU'},
                                                    {'label': '🌍 All World', 'value': 'ALL'},
                                                    {'label': '─────────────────', 'value': 'separator', 'disabled': True},
                                                ] + [
                                                    {'label': f"{name} ({code.upper()})", 'value': code}
                                                    for code, name in sorted(COUNTRY_CODES.items(), key=lambda x: x[1])
                                                ],
                                                value=['EU'],
                                                multi=True,
                                                placeholder='Select countries...',
                                                className='mb-3'
                                            ),
                                        ], className="mb-3"),

                                        html.Div([
                                            html.Label("Organisation Type", className="form-label fw-semibold mb-2",
                                                    style={'fontSize': '0.9rem'}),
                                            dcc.Dropdown(
                                                id='type-filter',
                                                options=[
                                                    {'label': 'Research organisation', 'value': 'REC'},
                                                    {'label': 'Higher education establishment', 'value': 'HES'},
                                                    {'label': 'Private for profit companies', 'value': 'PRC'},
                                                    {'label': 'Public bodies', 'value': 'PUB'},
                                                    {'label': 'Other', 'value': 'OTH'},
                                                ],
                                                value=[],
                                                multi=True,
                                                placeholder='Select organisation types...',
                                                className='mb-3'
                                            ),
                                        ], className="mb-3"),

                                        html.Div([
                                            html.Label("Organisation role", className="form-label fw-semibold mb-2",
                                                    style={'fontSize': '0.9rem'}),
                                            dbc.RadioItems(
                                                id='role-filter',
                                                options=[
                                                    {'label': 'Coordinator', 'value': 'coordinator'},
                                                    {'label': 'Participant', 'value': 'participant'},
                                                    {'label': 'Both', 'value': 'both'}
                                                ],
                                                value='both',
                                                className='mb-3'
                                            ),
                                        ], className="mb-3"),

                                        dbc.Button(
                                            "Reset Filters",
                                            id='reset-filters-btn',
                                            size="sm",
                                            className="w-100",
                                            color="success"
                                        )
                                    ],
                                ),
                            ]),
                            className='border-0 shadow rounded-3',
                            style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                        ),

                        # DETAILS & INFO
                        dbc.Card(
                            dbc.CardBody([
                                html.P([
                                    "Looking for more details about this tool? See the ",
                                    dcc.Link([
                                        'documentation.',
                                        html.I(className="bi bi-box-arrow-up-right ms-2")
                                    ], href='concept', className='text-decoration-none link-success')
                                ]),
                                html.P([
                                    "Do you want to export this page?",
                                ]),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button(
                                            "Download CSV",
                                            id='download-topics-csv-btn',
                                            size="sm",
                                            outline=True,
                                            className="w-100",
                                            color="success"
                                        ),
                                        dcc.Download(id='download-topics-csv')
                                    ]),

                                    dbc.Col([
                                        dbc.Button(
                                            "Download JSON",
                                            id='download-topics-json-btn',
                                            size="sm",
                                            outline=True,
                                            className="w-100",
                                            color="primary"
                                        ),
                                        dcc.Download(id='download-topics-json')
                                    ])
                                ])
                            ]),
                            className='border shadow rounded-3 mt-3',
                            style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                        )],
                        style={
                            'position': 'sticky',
                            'top': '6rem',
                    })],
                    width=3,
                ),
            ],
            className="g-3 mt-2",
        ),

        dcc.Store(id='topics-data'),
        dcc.Store(id='topics2-data'),
    ],
    id="topics-page",
    fluid=True,
    className="px-4"
)

#--------------------------------------------
# CALLBACK    
#--------------------------------------------
@callback(
    Output('topic-card-container', 'children'),
    Output('topics-data', 'data'),
    Output('tot-proj', 'children'),
    Output('tot-eur', 'children'),
    Output('tot-publ', 'children'),
    Output('tot-org', 'children'),
    Input('topic-dropdown', 'value'),
    Input('metric-filter', 'value'),
    Input('fp-filter', 'value'),
    Input('country-filter', 'value'),
    Input('type-filter', 'value'),
    Input('role-filter', 'value'),
    Input('slider-orgs', 'value')
)
def show_info_topic(selected_topic, metric, fp_list, country_list, typeorg_list, role, n_orgs):
    if not selected_topic:
        return [], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    # Passa i filtri alla funzione show_info
    info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org = script.show_info(
        selected_topic=selected_topic,
        metric=metric,
        fp_list=fp_list,
        country_list=country_list,
        typeorg_list=typeorg_list,
        role=role,
        n_orgs=n_orgs
    )
    
    return info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org

@callback(
    Output('topic2-card-container', 'children'),
    Output('topics2-data', 'data'),
    Output('tot-proj-2', 'children'),
    Output('tot-eur-2', 'children'),
    Output('tot-publ-2', 'children'),
    Output('tot-org-2', 'children'),
    Input('topic2-dropdown', 'value'),
    Input('metric-filter', 'value'),
    Input('fp-filter', 'value'),
    Input('country-filter', 'value'),
    Input('type-filter', 'value'),
    Input('role-filter', 'value'),
    Input('slider-orgs', 'value')
)
def show_info_topic2(selected_topic, metric, fp_list, country_list, typeorg_list, role, n_orgs):
    if not selected_topic:
        return [], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    # Passa i filtri alla funzione show_info
    info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org = script.show_info(
        selected_topic=selected_topic,
        metric=metric,
        fp_list=fp_list,
        country_list=country_list,
        typeorg_list=typeorg_list,
        role=role,
        n_orgs=n_orgs,
        is_1=False
    )
       
    return info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org

@callback(
    Output('topics-collaborations', 'children'),
    Input('topics-data', 'data'),
    Input('topics2-data', 'data'),
    Input('metric-filter', 'value'),
    Input('slider-orgs', 'value')
)
def join_topics(topics1_orgs, topics2_orgs, metric, n_orgs):
    if topics1_orgs and topics2_orgs and topics1_orgs != topics2_orgs:
        collaborations = script.join_topics(topics1_orgs, topics2_orgs, metric, n_orgs)
        return collaborations
    return []

@callback(
    Output('metric-filter', 'value'),
    Output('fp-filter', 'value'),
    Output('country-filter', 'value'),
    Output('type-filter', 'value'),
    Output('role-filter', 'value'),
    Input('reset-filters-btn', 'n_clicks'),    
    prevent_initial_call=True
)
def reset_filters(n_clicks):
    return 'n_progetti', [8, 9], ['EU'], [], 'both'

# === DOWNLOAD BUTTONS ===
@callback(
    Output('download-topics-csv', 'data'),
    Input('download-topics-csv-btn', 'n_clicks'),
    State('topics-data', 'data'),
    State('topics2-data', 'data'),
    State('topic-dropdown', 'value'),
    State('topic2-dropdown', 'value'),
    prevent_initial_call=True
)
def download_csv(n_clicks, top1, top2, name_top1, name_top2):
    df = script.download_file(top1, top2, name_top1, name_top2)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return dcc.send_data_frame(df.to_csv, f"{timestamp}.csv", index=False)

@callback(
    Output('download-topics-json', 'data'),
    Input('download-topics-json-btn', 'n_clicks'),
    State('topics-data', 'data'),
    State('topics2-data', 'data'),
    State('topic-dropdown', 'value'),
    State('topic2-dropdown', 'value'),
    prevent_initial_call=True
)
def download_json(n_clicks, top1, top2, name_top1, name_top2):
    df = script.download_file(top1, top2, name_top1, name_top2)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return dcc.send_data_frame(df.to_json, f"{timestamp}.json", index=False)