import dash
import math
import io
import json
from datetime import datetime
import pandas as pd
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html, Input, Output, State, ctx, callback, MATCH, no_update
from dash.exceptions import PreventUpdate

from utils import TITLE, COUNTRY_CODES, topic_names, deliverables_tbl, publications_tbl
import scripts._rag as script
from scripts._rag__projects_list import build_accordion_items, build_table_content
from scripts._rag__aggregated_view import build_aggregated_view, build_aggregated_graphs, build_graph
from scripts._rag__projects_graph import build_project_graph, build_overview_figure, build_topic_detail_figure
from scripts._explainability_api import call_relevance_api

PAGE_TITLE = "RAG"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/query',
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
        dcc.Store(id='retrieved-projects-store', data=[]),
        dcc.Store(id='retrieved-participants-store', data=[]),
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
                                            color="secondary", disabled=True, className="me-2"),
                                    dbc.Button("Next →", id="btn-next-page", size="sm",
                                            color="secondary", disabled=True),
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

                        # TAB 2 - Aggregated view
                        dbc.Tab(label='Aggregated view', tab_id='tab-aggregated', children=[
                            html.Div(id='aggregated-section', className="mt-4")
                        ]),

                        # TAB 3 - Project graph
                        dbc.Tab(label='Project graph', tab_id='tab-graph', children=[
                            html.Div(id='graph-section', className="mt-4")
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
    Output('retrieved-projects-store', 'data'),
    Output('retrieved-participants-store', 'data'),
    Input('retrieve-button-proj', 'n_clicks'),
    Input('coordinator-toggle', 'value'),
    State('fp-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    State('type-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
    State('topic-filter-proj', 'value'),
    State('user-input-proj', 'value'),    
    prevent_initial_call=True    
)
def retrieve_idx(n_clicks, is_coordinator, fp_list, country_list, typeorg_list, org_list, topic_list, user_input):

    if not any([fp_list, country_list, typeorg_list, org_list, topic_list, user_input]):
        return [], []

    projects_id, participants = script.retrieve_results_df(
        fp_list, country_list, typeorg_list, org_list, topic_list, user_input, is_coordinator,
    )

    return projects_id, participants

@callback(
    Output('fp-filter-proj', 'value'),
    Output('country-filter-proj', 'value'),
    Output('type-filter-proj', 'value'),
    Output('org-filter-proj', 'value'),
    Output('topic-filter-proj', 'value'),
    Output('user-input-proj', 'value'),
    Output('results-section', 'children', allow_duplicate=True),
    Output('retrieved-projects-store', 'data', allow_duplicate=True),
    Output('retrieved-participants-store', 'data', allow_duplicate=True),
    Input('reset-button-proj', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_filters(n_clicks):
    return [], [], [], [], [], '', ['Enter your requests and click "Retrieve"'], '', ''

# === TABS ===
# -----------------------------------------------------------------------------------------
@callback(
    Output('results-section', 'children'),
    Output('store-current-page', 'data'),
    Output('pagination-info', 'children'),
    Output('btn-prev-page', 'disabled'),
    Output('btn-next-page', 'disabled'),
    Output('pagination-controls', 'style'),
    Input('btn-prev-page', 'n_clicks'),
    Input('btn-next-page', 'n_clicks'),
    Input('retrieved-projects-store', 'data'),
    State('user-input-proj', 'value'),
    State('store-current-page', 'data'),
    prevent_initial_call=True,
)
def display_projects(prev_clicks, next_clicks, retrieved_projects, user_input, current_page):
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

    accordion_items, total = build_accordion_items(retrieved_projects, bool(user_input))

    if not accordion_items:
        return (
            [html.P("No projects found. Try different filters.")],
            0, "", True, True, {'display': 'none'}
        )

    PAGE_SIZE = 15
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
        current_page == 0,
        current_page >= total_pages - 1,
        style_visible
    )

SECTION_CONFIG = {
    'deliverables': {'tbl': deliverables_tbl, 
                     'columns': ["projectID", "title", "authors", "physUrl"], 
                     'link_phrase': 'Download deliverable↗'},
    'publications': {'tbl': publications_tbl, 
                     'columns': ["projectID", "title", "authors", "physUrl"], 
                     'link_phrase': 'See publication↗'},
}
@callback(
    Output({'type': 'section-collapse', 'project': MATCH, 'section': MATCH}, 'children'),
    Output({'type': 'section-collapse', 'project': MATCH, 'section': MATCH}, 'is_open'),
    Output({'type': 'section-chevron', 'project': MATCH, 'section': MATCH}, 'style'),
    Input({'type': 'section-toggle', 'project': MATCH, 'section': MATCH}, 'n_clicks'),
    State({'type': 'section-collapse', 'project': MATCH, 'section': MATCH}, 'is_open'),
    State({'type': 'section-collapse', 'project': MATCH, 'section': MATCH}, 'children'),
    prevent_initial_call=True,
)
def toggle_section(n_clicks, is_open, current_children):
    if not n_clicks:
        return no_update, no_update, no_update

    triggered = ctx.triggered_id
    project_id, section = triggered['project'], triggered['section']
    new_is_open = not is_open

    chevron_style = {
        'display': 'inline-block',
        'transition': 'transform 0.2s ease',
        'marginLeft': '6px',
        'cursor': 'pointer',
        'transform': 'rotate(90deg)' if new_is_open else 'rotate(0deg)',
    }

    # La query a LanceDB parte solo alla prima apertura di quella sezione:
    # se i children sono già popolati da un click precedente, non si rifà.
    if new_is_open and not current_children:
        cfg = SECTION_CONFIG[section]
        rows = (
            cfg['tbl'].search()
            .select(cfg['columns'])
            .where(f"projectID = {int(project_id)}")
            .to_arrow()
            .to_pylist()
        )
        content = build_table_content(rows, cfg['link_phrase'])
        return content, new_is_open, chevron_style

    return no_update, new_is_open, chevron_style

@callback(
    Output({'type': 'why-relevant-output', 'index': dash.MATCH}, 'children'),
    Input({'type': 'why-relevant-btn', 'index': dash.MATCH}, 'n_clicks'),
    State({'type': 'why-relevant-btn', 'index': dash.MATCH}, 'id'),
    State('user-input-proj', 'value'),
    prevent_initial_call=True
)
async def show_why_relevant(n_clicks, btn_id, user_input):
    project_id = btn_id['index']
    try:
        explanation = await call_relevance_api(project_id, user_input)
    except Exception as e:
        return html.Span(f"Could not load explanation: {e}", style={'color': '#dc3545'})
    return dcc.Markdown(explanation, style={'fontSize': '0.9rem'})
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
    Input('retrieved-participants-store', 'data'),
    prevent_initial_call=True
)
def display_aggregated(participants_data):
    if not participants_data:
        return (
            [html.P('Enter your requests and click "Retrieve"')]
        ), ''
    
    return build_aggregated_view(participants_data)

@callback(
    Output("agg-graph-container", "children"),
    Input("metrics-radio",  "value"),
    Input("agg-store",  "data"),
    prevent_initial_call=True
)
def update_agg_graph(radio_value, stored_data):
    data = pd.DataFrame(json.loads(stored_data))
    if data.empty:
        return []
    return build_aggregated_graphs(radio_value, data)

@callback(
    Output("agg-orgs-container", "children"),
    Input("slider-agg-orgs",  "value"),
    Input("metrics-radio",  "value"),
    Input("agg-store",  "data"),
    State("coordinator-toggle", "value"), 
)
def update_agg_orgs_graph(slider_value, metric, stored_data, is_coordinator):
    if metric == 'project':
        col = 'projectID'
        text = 'Number of projects'
    else:
        col = 'netEcContribution'
        text = 'Funding amount'
    data = pd.DataFrame(json.loads(stored_data))
    if is_coordinator:
        role = 'Coordinators'
    else:
        role = 'Participants'
    org_fig = build_graph(data, 'name', col, text, topk=slider_value, role=role)
    return dcc.Graph(figure=org_fig, id='agg_orgs')
# -----------------------------------------------------------------------------------------
# --- Project graph
@callback(
    Output('graph-section', 'children'),
    Input('retrieved-projects-store', 'data'),
    State('user-input-proj', 'value'),
    prevent_initial_call=True
)
def display_project_graph(projects_data, user_input):
    if not projects_data:
        return (
            [html.P('Enter your requests and click "Retrieve"')]
        )
    return build_project_graph(projects_data, user_input)


@callback(
    Output('project-graph', 'figure'),
    Output('project-graph-view-store', 'data'),
    Output('project-graph-back-btn', 'style'),
    Input('project-graph', 'clickData'),
    Input('project-graph-back-btn', 'n_clicks'),
    Input('project-graph-weight-slider', 'value'),
    State('project-graph-store', 'data'),
    State('project-graph-view-store', 'data'),
    State('user-input-proj', 'value'),
    prevent_initial_call=True
)
def update_project_graph(click_data, back_clicks, min_weight, store_data, view_data, user_input):
    if not store_data:
        return go.Figure(), no_update, no_update

    nodes = {int(pid): n for pid, n in store_data['nodes'].items()}
    edges = store_data['edges']
    user_input = bool(user_input)

    triggered_id = ctx.triggered_id

    back_visible_style = {'margin': '0 25px 10px 25px'}
    back_hidden_style = {'display': 'none', 'margin': '0 25px 10px 25px'}

    if triggered_id == 'project-graph-back-btn':
        fig = build_overview_figure(nodes, edges, min_weight, user_input)
        return fig, {'view': 'overview', 'topic': None}, back_hidden_style

    if triggered_id == 'project-graph':
        if not click_data or 'points' not in click_data:
            raise PreventUpdate
        point = click_data['points'][0]
        customdata = point.get('customdata')
        # click sulla hitbox del topic -> customdata è direttamente il nome del topic (stringa)
        if not isinstance(customdata, str):
            raise PreventUpdate  # click su un nodo/edge, non sulla casella: ignora
        topic_name = customdata
        fig = build_topic_detail_figure(topic_name, nodes, edges, min_weight, user_input)
        return fig, {'view': 'topic', 'topic': topic_name}, back_visible_style

    if triggered_id == 'project-graph-weight-slider':
        # lo slider rigenera la figura coerente con la vista corrente (overview o detail)
        if view_data and view_data.get('view') == 'topic':
            fig = build_topic_detail_figure(view_data['topic'], nodes, edges, min_weight, user_input)
            return fig, no_update, no_update
        fig = build_overview_figure(nodes, edges, min_weight, user_input)
        return fig, no_update, no_update

    raise PreventUpdate

# === Download Buttons ===
@callback(
    Output('download-projects-csv', 'data'),
    Input('download-button-proj', 'n_clicks'),
    State('retrieved-participants-store', 'data'),
)
def download_csv(n_clicks, participants_data):
    if not participants_data:
        return None
    df = pd.read_json(io.StringIO(participants_data), orient='split')
    df = df.drop(columns='topic_name')
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
        "# — topic_name_hierarchy: the project's topic hierarchy.\n"
        "# — fp: the framework programme in which the project was delivered.\n"
        f"# Rows: {len(df)}\n"
        "# ---\n"
    )
    buffer = io.StringIO()
    buffer.write(metadata)
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    return dcc.send_bytes(buffer.getvalue().encode(), f"{timestamp}.csv")