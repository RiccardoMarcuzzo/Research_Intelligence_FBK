import dash
from datetime import datetime
import dash_bootstrap_components as dbc
import scripts._topics as script
from dash import html, dcc, Input, Output, State, callback
from utils import TITLE, COUNTRY_CODES, labels_pkl, base_path

PAGE_TITLE = "Topics"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/',
    order=0
)

DEFAULT_TOPIC = 'Natural Language Processing'
COMPARISON_TOPIC = 'Industrial Safety'
topic_names = list(labels_pkl.values())
#--------------------------------------------
# LAYOUT      
#--------------------------------------------
layout = dbc.Container(
    [
        dbc.Row(
            [
                # === COLONNA SINISTRA: topic card ===
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
                        dcc.Slider(10,50,5, value=20, id='slider-orgs', className='mt-2'),

                        # TOPIC CARD
                        html.Div(id='topic-card-container', className='mt-2'),
                    ],
                    width=5,
                ),

                # === COLONNA CENTRALE: comparison ===
                dbc.Col(
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

                        className='border-0 shadow-sm rounded-3',
                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                    ),
                    width=4,
                ),

                # === COLONNA DESTRA: search + suggest + filters ===
                dbc.Col([
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
                            html.P(
                                [
                                    "Not sure what to search? Try typing a definition or description "
                                    "and find the most similar topics in our ",
                                    html.A("taxonomy", href=f"{base_path}concept#taxonomy-section"),
                                    "."
                                ],
                                className="text-muted fst-italic mb-2",
                                style={'fontSize': '0.85rem'}
                            ),

                            # SUGGEST
                            html.Div(
                                id='suggest-container',
                                children=[
                                    dbc.Input(
                                        id='suggest-input',
                                        placeholder="Type...",
                                        maxLength=140,
                                        style={'minHeight': '40px'},
                                        className='mb-2'
                                    ),
                                    html.Div([
                                        dbc.Button(
                                            "Find",
                                            id='submit-suggest-btn',
                                            color="success",
                                            size="sm",
                                            className='me-2 d-inline-flex align-items-center'
                                        ),
                                        html.Span(id='suggested-topics-buttons', style={'overflowX': 'auto', 'whiteSpace': 'nowrap', 'display': 'inline-flex', 'alignItems': 'center'})
                                    ], className='d-flex align-items-center')
                                ],
                            ),

                            html.Hr(className="my-3"),

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
                            ])
                        ]),
                        className='border shadow rounded-3 mt-3',
                        style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                    )],
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
# Mostra i bottoni con i topic suggeriti
@callback(
    Output('suggested-topics-buttons', 'children', allow_duplicate=True),
    Input('submit-suggest-btn', 'n_clicks'),
    Input('suggest-input', 'n_submit'),    
    State('suggest-input', 'value'),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def show_suggested_topics(n_clicks, n_submit, user_text):
    if not user_text:
        raise dash.exceptions.PreventUpdate
    
    suggested_topics = script.suggest_topic(user_text)
    
    if not suggested_topics:
        return html.Small("No topics found", className="text-muted")
    
    buttons = []
    for topic in suggested_topics:
        buttons.append(
            dbc.Button(
                topic,
                id={'type': 'select-topic-btn', 'topic': topic},
                color="success",
                outline=True,
                size="sm",
                className='me-2'
            )
        )
    
    return html.Div(
    buttons,
    style={'display': 'inline-flex', 'gap': '8px', 'paddingBottom': '12px'}
)

# Seleziona il topic cliccato e popola dropdown
@callback(
    Output('topic-dropdown', 'value'),
    Output('suggest-input', 'value'),
    Output('suggested-topics-buttons', 'children'),
    Input({'type': 'select-topic-btn', 'topic': dash.dependencies.ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def select_topic(n_clicks_list):
    ctx = dash.callback_context
    
    if not ctx.triggered or not any(n_clicks_list):
        raise dash.exceptions.PreventUpdate
    
    button_id = eval(ctx.triggered[0]['prop_id'].split('.')[0])
    selected_topic = button_id['topic']
       
    return selected_topic, None, []

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
    Input('slider-orgs', 'value')
)
def show_info_topic(selected_topic, metric, fp_list, country_list, n_orgs):
    if not selected_topic:
        return [], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    # Passa i filtri alla funzione show_info
    info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org = script.show_info(
        selected_topic=selected_topic,
        metric=metric,
        fp_list=fp_list,
        country_list=country_list,
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
    Input('slider-orgs', 'value')
)
def show_info_topic2(selected_topic, metric, fp_list, country_list, n_orgs):
    if not selected_topic:
        return [], None, 'N/A', 'N/A', 'N/A', 'N/A'
    
    # Passa i filtri alla funzione show_info
    info_content, topics_data, tot_proj, tot_eur, tot_publ, tot_org = script.show_info(
        selected_topic=selected_topic,
        metric=metric,
        fp_list=fp_list,
        country_list=country_list,
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
    Input('reset-filters-btn', 'n_clicks'),
    prevent_initial_call=True
)
def reset_filters(n_clicks):
    return 'n_progetti', [8, 9], ['EU']

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