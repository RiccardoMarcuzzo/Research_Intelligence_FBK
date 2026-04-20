import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ctx, callback, clientside_callback, ALL

from utils import TITLE, COUNTRY_CODES, topic_names
import scripts._rag as script

PAGE_TITLE = "RAG"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/askAI',
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
                    width=3
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
                    width=3
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

        # RETRIEVED PROJECTS SECTION
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
    return [], [], [], [], '', ['Type your requests and click "Retrieve"']


@callback(
    Output('results-section', 'children'),
    Input('retrieve-button-proj', 'n_clicks'),
    State('fp-filter-proj', 'value'),
    State('country-filter-proj', 'value'),
    State('org-filter-proj', 'value'),
    State('topic-filter-proj', 'value'),
    State('user-input-proj', 'value'),
)
def display_projects(n_clicks, fp_list, country_list, org_list, topic_list, user_input):
    return script.research_projects(fp_list, country_list, org_list, topic_list, user_input)
