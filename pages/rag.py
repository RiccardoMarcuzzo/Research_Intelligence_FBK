import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ctx, callback, clientside_callback, ALL

from utils import TITLE, projects_df, COUNTRY_CODES
import scripts._rag as script

PAGE_TITLE = "RAG"
dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    order=2
)

#TODO: gestione del backend dei filtri 

#--------------------------------------------
# LAYOUT      
#--------------------------------------------
layout = dbc.Container(
    [
        # === CHAT INTERFACE ===
        dbc.Row(
            [
                # COLONNA SINISTRA
                dbc.Col(
                    [
                        # Chat messages container con autoscroll
                        html.Div(
                            id="chat-messages",
                            children=[
                                html.Div(
                                    [
                                        html.Div(
                                            "AskAI is currently under maintenance", #TODO: TO-REMOVE-ASKAI-RAG
                                            className="p-3 rounded bg-light text-dark",
                                            style={
                                                'maxWidth': '80%',
                                                'marginLeft': 'auto',
                                                'marginRight': '0',
                                            }
                                        )
                                    ],
                                    className="mb-3 d-flex justify-content-start"
                                )
                            ],
                            style={
                                'height': '600px',
                                'overflowY': 'auto',
                                'border': '1px solid #dee2e6',
                                'borderRadius': '8px',
                                'padding': '1rem',
                                'backgroundColor': '#f8f9fa',
                                'marginBottom': '1rem'
                            }
                        ),

                        # Input area
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Input(
                                        id="user-input",
                                        placeholder="Type your question here...",
                                        type="text",
                                        className="form-control-lg",
                                        style={'borderRadius': '8px'},
                                        disabled=True #TODO: TO-REMOVE-ASKAI-RAG
                                    ),
                                    width=10
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Send",
                                        id="send-button",
                                        color="danger",
                                        className="w-100",
                                        size="lg",
                                        style={'borderRadius': '8px'},
                                        disabled=True #TODO: TO-REMOVE-ASKAI-RAG
                                    ),
                                    width=2
                                ),
                            ],
                            className="g-2"
                        ),

                        # Loading indicator
                        dbc.Spinner(
                            html.Div(id="loading-output"),
                            color="danger",
                            size="sm",
                            spinner_style={'marginTop': '10px'}
                        ),
                    ],
                    width=8
                ),

                # COLONNA DESTRA
                dbc.Col(
                    [
                        # WARNING
                        html.P(
                            'NOTE: To ensure high-quality synthesis, AskAI prioritizes and retrieves '
                            'the 15 most relevant documents from the database. For more comprehensive results or '
                            'specific insights, please refine your search terms. '
                            'All AI-generated content should be evaluated critically.',
                            className="text-muted mb-4",
                            style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                        ),

                        # DIVIDER
                        html.Hr(className="my-2"),

                        #FILTERS
                        html.Div(
                            id='filters-container-rag',
                            children=[
                                html.Div([
                                    html.Label("Framework Programme", className="form-label fw-semibold mb-2",
                                            style={'fontSize': '0.9rem'}),
                                    dcc.Dropdown(
                                        id='fp-filter-rag',
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
                                        id='country-filter-rag',
                                        options=[
                                            {'label': '🇪🇺 European Union (27 countries)', 'value': 'EU'},
                                            {'label': '🌍 All World', 'value': 'ALL'},
                                            {'label': '─────────────────', 'value': 'separator', 'disabled': True},
                                        ] + [
                                            {'label': f"{name} ({code.upper()})", 'value': code}
                                            for code, name in sorted(COUNTRY_CODES.items(), key=lambda x: x[1])
                                        ],
                                        value=['ALL'],
                                        multi=True,
                                        placeholder='Select countries...',
                                        className='mb-3'
                                    ),
                                ], className="mb-3"),

                                html.Div([
                                    html.Label("Organisation", className="form-label fw-semibold mb-2",
                                            style={'fontSize': '0.9rem'}),
                                    dcc.Dropdown(
                                        id='org-filter-rag',
                                        options=[],
                                        multi=True,
                                        placeholder='Select organisations...',
                                        className='mb-3'
                                    ),
                                ], className="mb-3"),

                                dbc.Button(
                                    "Reset Filters",
                                    id='reset-filters-btn-org',
                                    size="sm",
                                    className="w-100",
                                    color="danger"
                                )
                            ],
                        ),

                        # INFO AND DOWNLOAD
                        dbc.Card(
                            dbc.CardBody([
                            html.P([
                                "Looking for more details about this tool? See the ",
                                dcc.Link([
                                    'documentation.',
                                    html.I(className="bi bi-box-arrow-up-right ms-2")
                                ], href='overview', className='text-decoration-none link-danger')
                            ]),
                            ]),
                            className='border shadow rounded-3 mt-3',
                            style={'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
                        ),                                       

                        # STORES
                        dcc.Store(id='conversation-store', data=[]),
                        dcc.Store(id='source-store', data={}),
                        dcc.Store(id='scroll-trigger', data=0),

                        # SOURCES
                        dbc.Offcanvas(
                            id="source-sidebar",
                            title="Project Details",
                            is_open=False,
                            placement="end",
                            style={
                                "backgroundColor": "#e0e0e0",
                                "width": "30vw",
                            },
                            children=html.Div(id="source-details"),
                        )
                    ],
                    width=4
                ),
            ],
            className="mb-5"
        ),
    ],
    id='rag-page',
    fluid=True,
    className="px-4"
)


#--------------------------------------------
# CALLBACK
#--------------------------------------------
@callback(
    [
        Output('chat-messages', 'children'),
        Output('conversation-store', 'data'),
        Output('user-input', 'value'),
        Output('scroll-trigger', 'data'),
    ],
    [
        Input('send-button', 'n_clicks'),
        Input('user-input', 'n_submit'),
    ],
    [
        State('user-input', 'value'),
        State('conversation-store', 'data'),
        State('scroll-trigger', 'data'),
        State('source-store', 'data')
    ],
    prevent_initial_call=True
)
def display_user_message(n_clicks, n_submit, user_message, conversation, scroll_trigger, current_sources):
    """
    Mostra immediatamente il messaggio dell'utente nella chat.
    """
    if not user_message or user_message.strip() == "":
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    # Aggiungi messaggio utente alla conversazione
    conversation.append({
        'role': 'user',
        'content': user_message
    })
    
    # Costruisci i componenti visuali dei messaggi
    messages_components = build_message_components(conversation, current_sources)
    
    # Aggiungi indicatore "typing" dell'AI
    messages_components.append(
        html.Div(
            [
                html.Div(
                    [
                        html.Span("AI is thinking", className="me-2"),
                        html.Span(".", className="typing-dot", style={'animationDelay': '0s'}),
                        html.Span(".", className="typing-dot", style={'animationDelay': '0.2s'}),
                        html.Span(".", className="typing-dot", style={'animationDelay': '0.4s'}),
                    ],
                    className="p-3 rounded bg-light text-muted fst-italic",
                    style={
                        'maxWidth': '80%',
                        'marginLeft': '0',
                        'marginRight': 'auto',
                    },
                    id="typing-indicator"
                )
            ],
            className="mb-3 d-flex justify-content-start"
        )
    )
    
    # Incrementa scroll trigger
    scroll_trigger += 1
    
    return messages_components, conversation, "", scroll_trigger


@callback(
    [
        Output('chat-messages', 'children', allow_duplicate=True),
        Output('conversation-store', 'data', allow_duplicate=True),
        Output('source-store', 'data', allow_duplicate=True),
        Output('scroll-trigger', 'data', allow_duplicate=True),
    ],
    Input('conversation-store', 'data'),
    State('scroll-trigger', 'data'),
    State('source-store', 'data'),
    prevent_initial_call=True
)
def generate_ai_response(conversation, scroll_trigger, current_sources):
    """
    Genera la risposta dell'AI quando viene aggiunto un nuovo messaggio utente.
    """
    # Verifica se l'ultimo messaggio è dell'utente (quindi necessita risposta)
    if not conversation or conversation[-1]['role'] != 'user':
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    # Ottieni la risposta dall'AI
    user_message = conversation[-1]['content']
    ai_response, sources = script.ask_rag(user_message, conversation)
    
    # Aggiungi risposta AI alla conversazione
    conversation.append({
        'role': 'assistant',
        'content': ai_response.replace('\\n', '\n')
    })
    
    # Ricostruisci i componenti visuali (senza typing indicator)
    ai_idx = sum(1 for msg in conversation if msg['role'] == 'assistant')
    current_sources[str(ai_idx)] = sources

    messages_components = build_message_components(conversation, current_sources)
    
    scroll_trigger += 1
    
    return messages_components, conversation, current_sources, scroll_trigger


def build_message_components(conversation, sources):
    """
    Funzione helper per costruire i componenti visuali dei messaggi.
    """
    messages_components = []
    ai_idx = 1
    
    for msg in conversation:
        if msg['role'] == 'user':
            # Messaggio utente (allineato a destra)
            messages_components.append(
                html.Div(
                    [
                        html.Div(
                            msg['content'],
                            className="p-3 rounded text-white",
                            style={
                                'maxWidth': '80%',
                                'marginLeft': 'auto',
                                'marginRight': '0',
                                'backgroundColor': '#dc3545',
                                'wordWrap': 'break-word'
                            }
                        )
                    ],
                    className="mb-3 d-flex justify-content-end"
                )
            )
        else:
            # Messaggio AI
            ai_msg = [
                dcc.Markdown(
                    msg['content'],
                    dedent=True,
                    dangerously_allow_html=True,
                    link_target='_blank',
                    className="p-3 rounded",
                    style={
                        'maxWidth': '80%',
                        'marginLeft': '0',
                        'marginRight': 'auto',
                        'wordWrap': 'break-word',
                        'backgroundColor': '#f8f9fa',
                        'border': '1px solid #dee2e6',
                        'color': '#000000'
                    }
                )
            ]

            if sources[str(ai_idx)].get('used', {}) or sources[str(ai_idx)].get('unused', []):
                ai_msg.append(
                    html.Button(
                            'Show Source(s)',
                            id={'type': 'trigger-source-canvas', 'index': ai_idx},
                            className="btn btn-sm btn-outline-danger mt-2",
                            style={'marginLeft': '0'}
                        ),
                )

            messages_components.append(
                html.Div(
                    ai_msg,
                    className="mb-3 d-flex flex-column align-items-start"
                )
            )
            ai_idx += 1
    
    return messages_components


# Clientside callback per autoscroll
clientside_callback(
    """
    function(trigger) {
        if (trigger > 0) {
            var chatDiv = document.getElementById('chat-messages');
            if (chatDiv) {
                chatDiv.scrollTop = chatDiv.scrollHeight;
            }
        }
        return '';
    }
    """,
    Output('loading-output', 'children'),
    Input('scroll-trigger', 'data'),
    prevent_initial_call=True
)

# SIDEBAR
# trigger della sidebar
@callback(
    Output("source-sidebar", "is_open"),
    Input({'type': 'trigger-source-canvas', 'index': ALL}, 'n_clicks'),
    State("source-sidebar", "is_open"),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def open_sidebar(n_clicks_list, is_open):
    if ctx.triggered_id and any(n is not None for n in n_clicks_list):
        return True
    return is_open
# popolamento della sidebar
@callback(
    Output('source-details', 'children'),
    Input({'type': 'trigger-source-canvas', 'index': ALL}, 'n_clicks'),
    State('source-store', 'data'),
    prevent_initial_call=True,
)
def show_source_details(n_clicks_list, all_sources):
    if ctx.triggered_id:
        index = str(ctx.triggered_id['index'])
        source_data = all_sources.get(index, {})

        all_elements = []
        # SOURCE(s) USED
        used_dict = source_data.get('used', {})
        if used_dict:
            all_elements.append(html.H4("SOURCE(s) USED", style={'marginTop': '20px', 'borderBottom': '1px solid #ccc'}))
            for cit_num, idx in used_dict.items():
                all_elements.append(script.create_project_block(projects_df.iloc[idx], citation_number=cit_num))

        # OTHER(s)
        unused_list = source_data.get('unused', [])
        if unused_list:
            all_elements.append(html.H4("OTHER(s)", style={'marginTop': '20px', 'borderBottom': '1px solid #ccc'}))
            for idx in unused_list:
                all_elements.append(script.create_project_block(projects_df.iloc[idx]))
        
        if not all_elements:
            return html.Div("No details available.", style={'color': 'gray', 'fontStyle': 'italic', 'marginTop': '20px'})

        return html.Div(all_elements, style={'color': 'black'})
