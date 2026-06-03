import dash
import math
import io
import json
from datetime import datetime
import pandas as pd
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ctx, callback, ALL

from utils import TITLE, COUNTRY_CODES, topic_names
import scripts._rag as script
from scripts._rag__projects_list import build_accordion_items
from scripts._rag__aggregated_view import build_aggregated_view, build_aggregated_graphs, build_graph
from scripts._rag__latent_space import build_latent_space

PAGE_TITLE = "RAG"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/projects',
    order=0
)

# ===============
# --- LAYOUT ---
 #===============
layout = dbc.Container(
    [
        # === ROW 1: FILTRI ===
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Framework Programme", className="form-label fw-semibold mb-2",
                                   style={'fontSize': '0.9rem'}),
                        dcc.Dropdown(
                            id='fp-filter-proj',
                            options=[
                                {'label': 'Horizon 2020', 'value': 8},
                                {'label': 'Horizon Europe', 'value': 9}
                            ],
                            value=[],
                            multi=True,
                            placeholder='Select Framework Programmes...',
                        ),
                    ],
                    width=2
                ),
                dbc.Col(
                    [
                        html.Label("Country", className="form-label fw-semibold mb-2",
                                   style={'fontSize': '0.9rem'}),
                        dcc.Dropdown(
                            id='country-filter-proj',
                            options=[
                                {'label': f"{name} ({code.upper()})", 'value': code}
                                for code, name in sorted(COUNTRY_CODES.items(), key=lambda x: x[1])
                            ],
                            value=[],
                            multi=True,
                            placeholder='Select countries...',
                        ),
                    ],
                    width=2
                ),
                dbc.Col(
                    [
                        html.Label("Organisation type", className="form-label fw-semibold mb-2",
                                   style={'fontSize': '0.9rem'}),
                        dcc.Dropdown(
                            id='type-filter-proj',
                            options=[
                                {'label': 'Research organisation (REC)', 'value': 'REC'},
                                {'label': 'Higher education establishment (HES)', 'value': 'HES'},
                                {'label': 'Private for profit companies (PRC)', 'value': 'PRC'},
                                {'label': 'Public bodies (PUB)', 'value': 'PUB'},
                                {'label': 'Other (OTH)', 'value': 'OTH'},
                            ],
                            value=[],
                            multi=True,
                            placeholder='Select organisation types...',
                        ),
                    ],
                    width=2
                ),
                dbc.Col(
                    [
                        html.Label("Organisation", className="form-label fw-semibold mb-2",
                                   style={'fontSize': '0.9rem'}),
                        dcc.Dropdown(
                            id='org-filter-proj',
                            options=[],
                            value=[],
                            multi=True,
                            placeholder='Select organisations...',
                        ),
                    ],
                    width=3
                ),
                dbc.Col(
                    [
                        html.Label("Topic", className="form-label fw-semibold mb-2",
                                   style={'fontSize': '0.9rem'}),
                        dcc.Dropdown(
                            id='topic-filter-proj',
                            options=topic_names,
                            value=[],
                            multi=True,
                            placeholder='Select topic...',
                        ),
                    ],
                    width=3
                ),
            ],
            className="mb-3 g-2"
        ),

        # === ROW 2: INPUT TESTO + BOTTONI ===
        dbc.Row(
            [
                dbc.Col(
                    dbc.Textarea(
                        id="user-input-proj",
                        value='',
                        placeholder="Type your description here...",
                        className="form-control-lg",
                        style={'borderRadius': '8px', 'resize': 'vertical', 'minHeight': '100px'},
                    ),
                    width=7
                ),
                dbc.Col(
                    dbc.Button(
                        "Retrieve",
                        id="retrieve-button-proj",
                        color="primary",
                        className="w-100",
                        size="lg",
                        style={'borderRadius': '8px'},
                    ),
                    width={'size':2, 'offset':1}
                ),
                dbc.Col(
                    dbc.Button(
                        "Reset",
                        id="reset-button-proj",
                        outline=True,
                        color="primary",
                        className="w-100",
                        size="lg",
                        style={'borderRadius': '8px'},
                    ),
                    width='auto'
                ),
                dbc.Col(
                    [dbc.Button(
                        "Download",
                        id="download-button-proj",
                        outline=True,
                        color="primary",
                        className="w-100",
                        size="lg",
                        style={'borderRadius': '8px'},
                    ),
                    dcc.Download(id='download-projects-csv')],
                    width='auto'
                ),

            ],
            className="mb-3 g-2",
            align="center"
        ),
        # === ROW 3: COORDINATOR SWITCH ===
        dbc.Row(
            [
                    dbc.Switch(
                        id="coordinator-toggle",
                        label="Show coordinator only",
                        value=False,
                        className="mt-2 mb-3"
                    ),
            ],
            className="g-2",
            align="center"
        ),

        # === DOCUMENTAZIONE ===
        html.P(
            [
                "Looking for more details about this tool? See the ",
                dcc.Link(
                    ['documentation.', html.I(className="bi bi-box-arrow-up-right ms-2")],
                    href='concept',
                    className='text-decoration-none link-primary'
                )
            ],
            className="text-muted",
            style={'fontSize': '0.9rem'}
        ),

        # === RETRIEVED PROJECTS SECTION ===
        dcc.Store(id='retrieved-idx-store', data=[]),
        dcc.Store(id='coordinator-idx-store', data=[]),
        dcc.Store(id='store-current-page', data=0),
        dcc.Store(id='agg-store', data=''),
        html.Div(id='dummy', style={'display': 'none'}),
        html.Div(id='cordis-link-container', style={'marginTop': '10px'}),
        
        html.Div(
            id='results-tabs-container',
            style={'display': 'none'},
            children=[
                dbc.Tabs(
                    id='results-tabs',
                    active_tab='tab-projects',
                    className="mt-4",
                    children=[
                        # TAB 1 – Projects list
                        dbc.Tab(label='Projects list', tab_id='tab-projects', children=[
                            html.Div([
                                html.Div(id='pagination-info', className="text-muted",
                                        style={'fontSize': '0.85rem'}),
                                html.Div([
                                    dbc.Button("← Prev", id="btn-prev-page", size="sm",
                                            color="secondary", outline=True,
                                            disabled=True, className="me-2"),
                                    dbc.Button("Next →", id="btn-next-page", size="sm",
                                            color="secondary", outline=True, disabled=True),
                                ], className="d-flex align-items-center")
                            ], id='pagination-controls',
                            className="d-flex justify-content-between align-items-center px-1 py-2 mt-2",
                            style={'display': 'none'}
                            ),
                            html.Div(
                                id='results-section',
                                children=[html.P("No documents retrieved",
                                                className="text-muted fst-italic",
                                                style={'fontSize': '0.9rem'})],
                                style={
                                    'backgroundColor': "#ffffffc9",
                                    'borderRadius': '8px',
                                    'width': '100%',
                                    'padding': '2rem',
                                    'textAlign': 'center',
                                    'color': 'black',
                                },
                                className="mt-4"
                            ),
                        ]),

                        # TAB 2 – Aggregated view
                        dbc.Tab(label='Aggregated view', tab_id='tab-aggregated', children=[
                            html.Div(id='aggregated-section', className="mt-4")
                        ]),

                        # TAB 3 – Latent space
                        dbc.Tab(label='Latent space', tab_id='tab-latent', children=[
                            html.Div(id='latent-section', className="mt-4")
                ]),
            ]),
        ]),
    ],
    id='rag-page',
    fluid=True,
    className="px-4"
)


# =================
# --- CALLBACK ---
# =================
# --- ORG filter callback
@callback(
    Output('org-filter-proj', 'options'),
    Input('org-filter-proj', 'search_value'),
    State('org-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    State('type-filter-proj', 'value'),
    prevent_initial_call=True
)
def update_dropdown_org_filter(search_value, selected_orgs, countries, types):
    if not search_value:
        raise dash.exceptions.PreventUpdate
    
    new_options = script.update_dropdown(search_value, countries, types)

    if selected_orgs:
        existing = [{'label': org, 'value': org} for org in selected_orgs]
        new_values = {o['value'] for o in new_options}
        existing = [o for o in existing if o['value'] not in new_values]
        return existing + new_options

    return new_options

# === RETRIEVED PROJECTS SECTION ===
@callback(
    Output('results-tabs-container', 'style'),
    Input('retrieve-button-proj', 'n_clicks'),
    prevent_initial_call=True
)
def show_tabs(n_clicks):
    return {'display': 'block'}

@callback(
    Output('retrieved-idx-store', 'data'),
    Output('coordinator-idx-store', 'data'),
    Input('retrieve-button-proj', 'n_clicks'),
    State('fp-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    State('type-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
    State('topic-filter-proj', 'value'),
    State('user-input-proj', 'value'),
    prevent_initial_call=True    
)
def retrieve_idx(n_clicks, fp_list, country_list, typeorg_list, org_list, topic_list, user_input):

    if not any([fp_list, country_list, typeorg_list, org_list, topic_list, user_input]):
        return [], []
    
    return script.retrieve_active_indices(
        fp_list, country_list, typeorg_list, org_list, topic_list, user_input
    )

@callback(
    Output('fp-filter-proj', 'value'),
    Output('country-filter-proj', 'value'),
    Output('type-filter-proj', 'value'),
    Output('org-filter-proj', 'value'),
    Output('topic-filter-proj', 'value'),
    Output('user-input-proj', 'value'),
    Output('results-section', 'children', allow_duplicate=True),
    Output('retrieved-idx-store', 'data', allow_duplicate=True),
    Input('reset-button-proj', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_filters(n_clicks):
    return [], [], [], [], [], '', ['Enter your requests and click "Retrieve"'], ''

# === TABS ===
# -----------------------------------------------------------------------------------------
# --- Project list
@callback(
    Output('results-section', 'children'),
    Output('store-current-page', 'data'),
    Output('pagination-info', 'children'),
    Output('btn-prev-page', 'disabled'),
    Output('btn-next-page', 'disabled'),
    Output('pagination-controls', 'style'),
    Input('btn-prev-page', 'n_clicks'),
    Input('btn-next-page', 'n_clicks'),
    Input("coordinator-toggle", "value"),
    Input('retrieved-idx-store', 'data'),
    Input('coordinator-idx-store', 'data'),
    State('store-current-page', 'data'),
    prevent_initial_call = True
)
def display_projects(prev_clicks, next_clicks, is_coordinator, retrieved_projects, coordinator_projects, current_page):
    triggered = ctx.triggered_id

    if triggered == 'btn-next-page':
        current_page = (current_page or 0) + 1
    elif triggered == 'btn-prev-page':
        current_page = max(0, (current_page or 0) - 1)
    else:
        current_page = 0

    if not retrieved_projects:
        return (
            [html.P('Enter your requests and click "Retrieve"')],
            0, "", True, True, {'display': 'none'}
        )

    accordion_items, total = build_accordion_items(is_coordinator, retrieved_projects, coordinator_projects)

    if not accordion_items:
        return (
            [html.P("No projects found. Try different filters.")],
            0, "", True, True, {'display': 'none'}
        )

    PAGE_SIZE = 15
    total = len(accordion_items)
    total_pages = math.ceil(total / PAGE_SIZE)
    start = current_page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    content = dbc.Accordion(
        accordion_items[start:end],
        flush=True, always_open=True, start_collapsed=True,
        style={'borderRadius': '8px', 'overflow': 'hidden'},
        class_name='projects-accordion'
    )

    info = f"Showing {start + 1}–{end} of {total} projects"
    style_visible = {'display': 'flex', 'justifyContent': 'space-between',
                     'alignItems': 'center', 'padding': '8px 4px'}

    return (
        [content],
        current_page,
        info,
        current_page == 0,              # prev disabled
        current_page >= total_pages - 1, # next disabled
        style_visible
    )
#* -------------------------------------------------------------------------------------------
#* Navigation buttons
@callback(
    Output('store-current-page', 'data', allow_duplicate=True),
    Input('btn-prev-page', 'n_clicks'),
    Input('btn-next-page', 'n_clicks'),
    Input('retrieve-button-proj', 'n_clicks'),
    State('store-current-page', 'data'),
    prevent_initial_call=True
)
def update_page(prev_clicks, next_clicks, n_click, *filter_inputs_and_state):
    current_page = filter_inputs_and_state[-1]
    triggered = ctx.triggered_id
    if triggered == 'btn-next-page':
        return current_page + 1
    elif triggered == 'btn-prev-page':
        return max(0, current_page - 1)
    else:
        return 0
# -----------------------------------------------------------------------------------------
# --- Aggregated view
@callback(
    Output('aggregated-section', 'children'),
    Output("agg-store", "data"), 
    Input('retrieved-idx-store', 'data'),
    Input('coordinator-idx-store', 'data'),
    Input("coordinator-toggle", "value"),    
    State('country-filter-proj', 'value'),
    State('type-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
    State('topic-filter-proj', 'value'),
    prevent_initial_call=True
)
def display_aggregated(retrieved_projects, coordinator_projects, is_coordinator, country_list, typeorg_list, org_list, topic_list):
    if not retrieved_projects:
        return (
            [html.P('Enter your requests and click "Retrieve"')]
        ), ''
    
    return build_aggregated_view(retrieved_projects, coordinator_projects, is_coordinator, country_list, typeorg_list, org_list, topic_list)

@callback(
    Output("agg-graph-container", "children"),
    Input("coordinator-toggle", "value"), 
    Input("metrics-radio",  "value"),
    Input("agg-store",  "data"),
    prevent_initial_call=True
)
def update_agg_graph(is_coordinator, radio_value, stored_data):
    data = pd.DataFrame(json.loads(stored_data))
    if data.empty:
        return []
    return build_aggregated_graphs(is_coordinator, radio_value, data)

@callback(
    Output("agg-orgs-container", "children"),
    Input("slider-agg-orgs",  "value"),
    Input("coordinator-toggle", "value"), 
    Input("metrics-radio",  "value"),
    Input("agg-store",  "data"),
)
def update_agg_orgs_graph(slider_value, is_coordinator, metric, stored_data):
    if metric == 'project':
        col = 'projectID'
        text = 'Number of projects'
    else:
        col = 'netEcContribution'
        text = 'Funding amount'
    data = pd.DataFrame(json.loads(stored_data))
    if is_coordinator:
        data = data[data['role'] == 'coordinator']
        role = 'Coordinators'
    else:
        role = 'Participants'
    org_fig = build_graph(data, 'name', col, text, topk=slider_value, role=role)
    return dcc.Graph(figure=org_fig, id='agg_orgs')
# -----------------------------------------------------------------------------------------
# --- Latent space
@callback(
    Output('latent-section', 'children'),
    Input('retrieved-idx-store', 'data'),
    Input('coordinator-idx-store', 'data'),
    Input('coordinator-toggle', 'value'),
    State('user-input-proj', 'value'),
    prevent_initial_call=True
)
def display_latent_space(retrieved_projects, coordinator_projects, is_coordinator, user_input):
    if is_coordinator:
        indices = coordinator_projects
    else:
        indices = retrieved_projects
    if not indices:
        return (
            [html.P('Enter your requests and click "Retrieve"')]
        )
    return build_latent_space(indices, user_input)

# === Download Buttons ===
@callback(
    Output('download-projects-csv', 'data'),
    Input('download-button-proj', 'n_clicks'),
    State('retrieved-idx-store', 'data'),
    State('country-filter-proj', 'value'),
    State('type-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
)
def download_csv(n_clicks, indices, country_list, typeorg_list, org_list):
    if not indices:
        return None
    df = script.download_file(indices, country_list, typeorg_list, org_list)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    metadata = (
        f"# Exported: {timestamp}\n"
        "# To read in pandas: pd.read_csv('<file>.csv', comment='#')\n"
        "# Columns:\n"
        "# — projectID: the unique identifier in CORDIS database for the project.\n"
        "# — organisationID: the unique identifier in CORDIS database for the organisation.\n"
        "# — name: the organisation's name.\n"
        "# — countryCode: the organisation's country.\n"
        "# — activityType: the organisation's activity type.\n"
        "# — role: the organisation's role for the project.\n"
        "# — netEcContribution: the funding amount received by the organisation for the project.\n"
        "# — topic_name: the project's topic.\n"
        "# — fp: the frameowrk programme in which the project was delivered.\n"
        "# — title: the project's title.\n"
        "# — deliverables: link(s) to the deliverable associated to the project.\n"
        f"# Rows: {len(df)}\n"
        "# ---\n"
    )
    buffer = io.StringIO()
    buffer.write(metadata)
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    return dcc.send_bytes(buffer.getvalue().encode(), f"{timestamp}.csv")