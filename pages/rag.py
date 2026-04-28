import dash
import math
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ctx, callback, clientside_callback, ALL

from utils import TITLE, COUNTRY_CODES, topic_names
import scripts._rag as script

PAGE_TITLE = "RAG"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/projects',
    order=2
)

#--------------------------------------------
# LAYOUT      
#--------------------------------------------
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
                                {'label': 'Research organisation', 'value': 'REC'},
                                {'label': 'Higher education establishment', 'value': 'HES'},
                                {'label': 'Private for profit companies', 'value': 'PRC'},
                                {'label': 'Public bodies', 'value': 'PUB'},
                                {'label': 'Other', 'value': 'OTH'},
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
                        "Reset Filters",
                        id="reset-button-proj",
                        outline=True,
                        color="danger",
                        className="w-100",
                        size="lg",
                        style={'borderRadius': '8px'},
                    ),
                    width={"size": 2, "offset": 1}
                ),
                dbc.Col(
                    dbc.Button(
                        "Retrieve",
                        id="retrieve-button-proj",
                        color="danger",
                        className="w-100",
                        size="lg",
                        style={'borderRadius': '8px'},
                    ),
                    width=2
                ),
            ],
            className="mb-4 g-2",
            align="center"
        ),

        # === DOCUMENTAZIONE ===
        html.P(
            [
                "Looking for more details about this tool? See the ",
                dcc.Link(
                    ['documentation.', html.I(className="bi bi-box-arrow-up-right ms-2")],
                    href='concept',
                    className='text-decoration-none link-danger'
                )
            ],
            className="text-muted mt-2",
            style={'fontSize': '0.9rem'}
        ),

        # === RETRIEVED PROJECTS SECTION ===
        html.Div([
            html.Div(id='pagination-info', className="text-muted", style={'fontSize': '0.85rem'}),
            html.Div([
                dbc.Button("← Prev", id="btn-prev-page", size="sm", color="secondary",
                        outline=True, disabled=True, className="me-2"),
                dbc.Button("Next →", id="btn-next-page", size="sm", color="secondary",
                        outline=True, disabled=True),
            ], className="d-flex align-items-center")
        ], id='pagination-controls',
        className="d-flex justify-content-between align-items-center px-1 py-2 mt-2",
        style={'display': 'none'}
        ), 

        dcc.Store(id='store-current-page', data=0),

        html.Div(
            id='results-section',
            children=[
                html.P(
                    "No documents retrieved",
                    className="text-muted fst-italic",
                    style={'fontSize': '0.9rem'}
                )
            ],
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
    ],
    id='rag-page',
    fluid=True,
    className="px-4"
)


#--------------------------------------------
# CALLBACK
#--------------------------------------------
# === ORG filter callback ===
@callback(
    Output('org-filter-proj', 'options'),
    Input('org-filter-proj', 'search_value'),
    State('org-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    prevent_initial_call=True
)
def update_dropdown_org_filter(search_value, selected_orgs, countries):
    if not search_value:
        raise dash.exceptions.PreventUpdate
    
    new_options = script.update_dropdown(search_value, countries)

    if selected_orgs:
        existing = [{'label': org, 'value': org} for org in selected_orgs]
        new_values = {o['value'] for o in new_options}
        existing = [o for o in existing if o['value'] not in new_values]
        return existing + new_options

    return new_options

@callback(
    Output('fp-filter-proj', 'value'),
    Output('country-filter-proj', 'value'),
    Output('org-filter-proj', 'value'),
    Output('topic-filter-proj', 'value'),
    Output('user-input-proj', 'value'),
    Output('results-section', 'children', allow_duplicate=True),
    Input('reset-button-proj', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_filters(n_clicks):
    return [], [], [], [], '', ['Enter your requests and click "Retrieve"']


@callback(
    Output('results-section', 'children'),
    Output('store-current-page', 'data'),
    Output('pagination-info', 'children'),
    Output('btn-prev-page', 'disabled'),
    Output('btn-next-page', 'disabled'),
    Output('pagination-controls', 'style'),
    Input('retrieve-button-proj', 'n_clicks'),
    Input('btn-prev-page', 'n_clicks'),
    Input('btn-next-page', 'n_clicks'),
    State('fp-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
    State('topic-filter-proj', 'value'),
    State('user-input-proj', 'value'),
    State('store-current-page', 'data'),

)
def display_projects(n_clicks, prev_clicks, next_clicks,
                     fp_list, country_list, org_list, topic_list, user_input, current_page):
    triggered = ctx.triggered_id

    if triggered == 'btn-next-page':
        current_page = (current_page or 0) + 1
    elif triggered == 'btn-prev-page':
        current_page = max(0, (current_page or 0) - 1)
    else:
        current_page = 0  # nuovo retrieve → reset

    if not any([fp_list, country_list, org_list, topic_list, user_input]):
        return (
            [html.P('Enter your requests and click "Retrieve"')], 
            0, "", True, True, {'display': 'none'}
        )

    accordion_items, total = script.build_accordion_items(
        fp_list, country_list, org_list, topic_list, user_input
    )

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

# Callback separato per gestire i bottoni di navigazione
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