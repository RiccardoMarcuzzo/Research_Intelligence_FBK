import dash
import utils
import dash_bootstrap_components as dbc
import scripts._overview as script

from dash import dcc, html, Input, Output, State, ctx, callback, clientside_callback
from utils import TITLE, base_path

PAGE_TITLE = "Overview"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/concept',
    order=3
)
#--------------------------------------------
# LAYOUT      
#--------------------------------------------
layout = html.Div([
    html.H1("Ex-CORDIS: Exploring CORDIS from its core", className="fw-bold mb-3 mt-4",),
    # TOP HOMEPAGE
    html.P(
        ["CORDIS is the EU's platform for accessing and analysing data on funded research. "
        "Since 1984, EU Framework Programmes have supported scientific excellence and collaboration across Europe. "
        "This dashboard lets you explore projects, organisations, research topics and helps you connect your research with the wider European landscape. ",
        html.B(html.I("Note: ")), 
        html.I("Data regarding Horizon Europe projects are current through the end of 2024.")
    ],
    className="text-muted mb-4",
    style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
    ),

    # KPIs
    dbc.Row([
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.H4("-", id="home-number-of-projects", className="card-title"),
                    html.H6("projects investigated", className="card-subtitle")]
                    )),
                class_name="mb-3",
                md=4,
                sm=12),
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.H4("-", id="home-number-of-organisations", className="card-title"),
                    html.H6("organisations involved", className="card-subtitle")]
                )),
            class_name="mb-3",
            md=4,
            sm=12),
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.H4("-", id="home-number-of-topics", className="card-title"),
                    html.H6("research topics explored", className="card-subtitle")]
                )),
            class_name="mb-3",
            md=4,
            sm=12),
    ]),
    
    # DATAMAPPLOT
    dbc.Row(
        [
            # Colonna sinistra - Mappa
            dbc.Col(
                [
                    html.Iframe(
                        id='datamapplot',
                        src='assets/dmp_for_dash.html',
                        sandbox="allow-scripts allow-same-origin",
                        style={
                            'width': '100%',
                            'height': '65vh',
                            'border': 'none'
                        }
                    ),
                    dcc.Store(id='message-store'),
                ],
                width=7
            ),

            # Colonna destra - Descrizione
            dbc.Col(
                [
                    html.H3("Explore the Project Latent Space", className="fw-bold mb-3 mt-2"),
                    html.P(
                        [
                            html.B(html.I("Instructions: ")),
                            html.I("Hover or click on project points to reveal specific attributes and cluster topics.")
                        ],
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                    html.P(
                        [
                            "The latent space was engineered using SPECTER2 (",
                            html.A("paper", href="https://arxiv.org/pdf/2211.13308", target="_blank"),
                            ", ",
                            html.A("HuggingFace", href="https://huggingface.co/allenai/specter2", target="_blank"),
                            "), an embedding model specifically trained for scientific abstract representation. "
                            "The resulting embeddings were subsequently reduced to two dimensions via UMAP prior to topic extraction.",
                        ],                      
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                    html.P(
                        "The datamap presented here accurately reflects the latent space from which topics were derived using the HDBSCAN algorithm. " \
                        "Over 50 hyperparameter combinations were systematically evaluated, selecting the optimal configuration based on topic diversity, topic coherence, and qualitative analysis. " \
                        "Furthermore, projects initially identified as noise were reassigned to their most semantically similar cluster, provided the cosine similarity between the topic embedding and the project embedding exceeded a threshold of 0.99.",
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                ],
                width=5
            ),
        ],
        className="mb-5"
    ),

    # TOPIC TREEMAP
    dbc.Row(
        [
            # Colonna sinistra - Testo
            dbc.Col(
                [
                    html.H3("Explore the Topic Taxonomy", className="fw-bold mb-3 mt-2"),
                    html.P(
                        [
                            html.B(html.I("Instructions: ")),
                            html.I("Click a topic to view its constituent subtopics, their relative share (%), and the number of associated projects. "
                                   "Click the navigation bar above to navigate back to parent topics.")
                        ],
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                    html.P(
                        [
                            "The topic taxonomy was developed using BERTopic (",
                            html.A("website", href="https://maartengr.github.io/BERTopic/index.html", target="_blank"),
                            "). Following the extraction of base topics, a hierarchical structure was established via agglomerative clustering, "
                            "which was subsequently refined through a Human-in-the-Loop approach.",
                        ],                      
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),        
                    html.P(
                        "Labels were synthesized by an LLM leveraging c-TF-IDF keywords, representative documents, and, for higher-order nodes, the descriptors of their constituent child topics.",
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                    html.P(
                        "The resulting framework constitutes a rigorous, data-driven, bottom-up taxonomy.",
                        className="text-muted",
                        style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
                    ),
                ],
                width=5
            ),

            # Colonna destra - Treemap
            dbc.Col(
                [
                    dbc.Card([
                        dbc.CardBody([
                            dcc.Graph(
                                id='topic-treemap',
                                config={'scrollZoom': True},
                                style={'height': '65vh', 'width': '100%'}
                            )
                        ], className="p-0")
                    ], className="shadow-sm mb-5")
                ],
                width=7
            ),
        ],
        className="mb-5"
    ),
    
    # EXPLORE SECTIONS
    html.Div([
        html.Hr(className="my-5"),
        html.H3("Explore by Section", className="fw-bold mb-4 text-center", id="explore-sections"),
        html.P(
            "Choose your preferred way to explore CORDIS research data.",
            className="text-muted text-center mb-5",
            style={'fontSize': '1.1rem'}
        ),
    ]),

    # TOPICS
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.I(className="bi bi-lightbulb", style={'fontSize': '3rem', 'color': '#198754'}),
                    ], className="text-center mb-3"),
                    html.H4("Topics", className="card-title text-center fw-bold"),
                    html.P(
                        "Browse research topics and themes. "
                        "Identify trending areas and explore thematic connections between projects.",
                        className="card-text text-muted",
                        style={'fontSize': '0.95rem', 'lineHeight': '1.6'}
                    ),
                    html.Div([
                        dcc.Link(
                            dbc.Button("Explore Topics →", color="success", className="w-100 mt-3"),
                            href=base_path
                        )
                    ])
                ])
            ], className="h-100 shadow-sm")
        ], width=4),

        dbc.Col([
            html.H4('Page: Topics', className="fw-bold mt-2"),
            html.P(
                "Here you can select a topic to identify the leading organizations based on project count, total funding received, or publication volume. "
                "The analysis can be further refined using temporal filters (by Framework Programme) or geographical parameters (by Country). "
                "Additionally, you can select a second topic to perform a comparative analysis and identify the top players common to both selected research areas.",
                className="text-muted mt-4",
                style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
            )
        ], width=4),

                dbc.Col([
            html.Img(src='assets/img/placeholder-topics.png', style={'width': '100%', 'height': '100%', 'objectFit': 'cover'})
        ], width=4, style={'height': '283px', 'overflow': 'hidden'}),

    ], className="mb-5"),

    

    # ORGANIZATIONS
    dbc.Row([
        dbc.Col([
            html.Img(src='assets/img/placeholder-org.jpg', style={'width': '100%', 'height': '100%', 'objectFit': 'cover'})
        ], width=4, style={'height': '283px', 'overflow': 'hidden'}),

        dbc.Col([
            html.H4('Page: Organisations', className="fw-bold mt-2"),
            html.P(
                "In this section, you can select a specific organization to analyze its research output across topics " \
                "based on project count, publication volume, or total funding allocated. " \
                "The analysis can be further refined by Framework Programme to focus on specific temporal periods. " \
                "Additionally, you can review the organization's project portfolio and select a second entity to compare and identify their collaborative projects.",
                className="text-muted mt-4",
                style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
            )
        ], width=4),

        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.I(className="bi bi-building", style={'fontSize': '3rem', 'color': '#0d6efd'}),
                    ], className="text-center mb-3"),
                    html.H4("Organisations", className="card-title text-center fw-bold"),
                    html.P(
                        "Discover research institutions, universities, and companies participating in EU-funded projects. "
                        "Analyse their collaboration networks and funding patterns.",
                        className="card-text text-muted",
                        style={'fontSize': '0.95rem', 'lineHeight': '1.6'}
                    ),
                    html.Div([
                        dcc.Link(
                            dbc.Button("Explore Organisations →", color="primary", className="w-100 mt-3"),
                            href="organisations"
                        )
                    ])
                ])
            ], className="shadow-sm")
        ], width=4),
    ], className="mb-5"),

    # RAG
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.I(className="bi bi-chat-dots", style={'fontSize': '3rem', 'color': '#dc3545'}),
                    ], className="text-center mb-3"),
                    html.H4("Ask AI", className="card-title text-center fw-bold"),
                    html.P(
                        "Use RAG-powered search to ask questions in natural language. "
                        "Get precise answers grounded in project descriptions, objectives, and outcomes.",
                        className="card-text text-muted",
                        style={'fontSize': '0.95rem', 'lineHeight': '1.6'}
                    ),
                    html.Div([
                        dcc.Link(
                            dbc.Button("Try Ask AI →", color="danger", className="w-100 mt-3"),
                            href="askAI"
                        )
                    ])
                ])
            ], className="shadow-sm")
        ], width=4),

        dbc.Col([
            html.H4('Page: Ask AI', className="fw-bold mt-2"),
            html.P(
                'Do you have specific questions, or would you like to explore the project portfolio? ' \
                'This page allows you to query the database directly; ' \
                'a Retrieval-Augmented Generation (RAG) system will provide answers based on the evidence found within the CORDIS project corpus. ' \
                'Furthermore, you can refine your search by focusing on a specific Framework Programme, Country, Organization, or any combination of these filters.',
                className="text-muted mt-4",
                style={'fontSize': '1.1rem', 'lineHeight': '1.6'}
            )
        ], width=4),

        dbc.Col([
            html.Img(src='assets/img/placeholder-askai.jpg', style={'width': '100%', 'height': '100%', 'objectFit': 'cover'})
        ], width=4, style={'height': '283px', 'overflow': 'hidden'}),
    ], className="mb-5"),

    # CONTACT FORM
    html.Div([
        html.Hr(className="my-5"),
        html.H3("Meet the Team", className="fw-bold mb-4 text-center", id="explore-sections"),
        html.P(
            "Contact us for questions and feedback.",
            className="text-muted text-center mb-5",
            style={'fontSize': '1.1rem'}
        ),
        
        dbc.Row([

            dbc.Col([
                html.Img(src='assets/img/chub.jpg', style={'width': '25%', 'height': 'auto'}),
                html.H5("Veronica Orsanigo", className="fw-bold mb-2 mt-2"),
                html.A("vorsanigo@fbk.eu", href="mailto:vorsanigo@fbk.eu?cc=rmarcuzzo@fbk.eu,eleonardelli@fbk.eu", 
                       className="text-info", style={'fontSize': '0.95rem'}),
                html.P("Curation and structuring of project and organisation data.", 
                    className="text-muted", style={'fontSize': '0.95rem', "minHeight": "60px"}),                
            ], width=4, className="text-center px-4"),

            dbc.Col([
                html.Img(src='assets/img/chub.jpg', style={'width': '25%', 'height': 'auto'}),
                html.H5("Riccardo Marcuzzo", className="fw-bold mb-2 mt-2"),
                html.A("rmarcuzzo@fbk.eu", href="mailto:rmarcuzzo@fbk.eu?cc=vorsanigo@fbk.eu,eleonardelli@fbk.eu", 
                       className="text-info", style={'fontSize': '0.95rem'}),
                html.P("Topic modeling, taxonomy development and dashboard design.", 
                    className="text-muted",
                style={'fontSize': '0.95rem', 'minHeight': '60px'}),                
            ], width=4, className="text-center px-4"),            

            dbc.Col([
                html.Img(src='assets/img/dh.png', style={'width': '25%', 'height': 'auto'}),
                html.H5("Elisa Leonardelli", className="fw-bold mb-2 mt-2"),
                html.A("eleonardelli@fbk.eu", href="mailto:eleonardelli@fbk.eu?rmarcuzzo@fbk.eu,vorsanigo@fbk.eu", 
                       className="text-info", style={'fontSize': '0.95rem'}),
                html.P("Retrieval and organization of scientific publication dataset.", 
                    className="text-muted", style={'fontSize': '0.95rem', "minHeight": "60px"}),                
            ], width=4, className="text-center px-4"),
        ], className="justify-content-center mt-5"),

        html.P(
            "Please feel free to contact us for anything concerning Ex-CORDIS: Research Intelligence Tool.",
            className="text-muted text-center mt-5 italic",
            style={'fontSize': '0.95rem', 'opacity': '0.7'}
        )
    ]),

    # SIDEBAR
    dbc.Offcanvas(
        id="doc-sidebar",
        title="Project Details",
        is_open=False,
        placement="end",  # Right side
        style={
            "backgroundColor": "#e0e0e0",
            "width": "30vw",  # Desktop default
        },
        children=html.Div(id="doc-details"),
    )
])
#--------------------------------------------
# CALLBACK    
#--------------------------------------------
# TOP HOMEPAGE
@callback([
        Output("home-number-of-projects", "children"),
        Output("home-number-of-organisations", "children"),
        Output("home-number-of-topics", "children")],
        Input("home-number-of-projects", "children")
)
def update_overview(_) -> tuple:
    return (
        utils.PROJs_No,
        utils.ORGs_No,
        utils.TOPs_No)
# TOPIC TREEMAP
@callback(
    Output('topic-treemap', 'figure'),
    Input('home-number-of-projects', 'children')  # Trigger quando le metriche sono caricate
)
def update_treemap(_):
    fig = script.generate_treemap()  # O script.generate_treemap() se è lì
    return fig

# SIDEBAR
@callback(
    Output("doc-sidebar", "is_open"),
    Input("message-store", "data"),
    State("doc-sidebar", "is_open"),
    prevent_initial_call=True
)
def toggle_sidebar(data, is_open):
    if ctx.triggered_id == "message-store" and data:
        return True
    return False
clientside_callback(
    """
    function(iframe_id) {
    function handleMessage(event) {
        if (!event.data || event.data.type !== 'point-clicked') return;
        if (!window.dash_clientside || !window.dash_clientside.set_props) {
            return;
        }
        window.dash_clientside.set_props('message-store', {
            data: {
                type: event.data.type,
                id: event.data.id
            }
        });
    }
    window.removeEventListener('message', handleMessage);
    window.addEventListener('message', handleMessage);
    return window.dash_clientside.no_update;
}
    """,
    Output('message-store', 'data'),
    Input('datamapplot', 'id'),
)
@callback(
    Output('doc-details', 'children'),
    Input('message-store', 'data'),
    prevent_initial_call=True,
)
def show_doc_details(message_data):   
    if not message_data:
        return "Click a point on the map to display project details..."
    
    proj_id = message_data.get('id')
    
    return script.populate_doc_canvas(int(proj_id))
