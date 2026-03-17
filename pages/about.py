import dash
from dash import html
import dash_bootstrap_components as dbc
from utils import TITLE

PAGE_TITLE = "About"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    order=6
)

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                [
                    html.H1(
                        "Mappare la ricerca europea: LLM-Based Topic Modeling e Visual Analytics del database CORDIS",
                        className="fw-bold mb-3 mt-4",
                    ),
                    html.P(
                        "Riccardo Marcuzzo",
                        className="mb-2",
                        style={'fontSize': '1.1rem'}
                    ),
                    html.P(
                        [
                            html.Strong("Relatori: "),
                            "Dott. Alessandro Bondielli, Dott. Riccardo Gallotti"
                        ],
                        className="mb-2",
                        style={'fontSize': '1.1rem'}
                    ),
                    html.P(
                        [
                            html.Strong("Correlatore: "),
                            "Dott.ssa Veronica Orsanigo"
                        ],
                        className="mb-2",
                        style={'fontSize': '1.1rem'}
                    ),
                    html.P(
                        html.A("Link al progetto", href="https://github.com/RiccardoMarcuzzo/Ex-CORDIS", target="_blank"),
                        className="mb-4",
                        style={'fontSize': '1.1rem'}
                    ),
                ],
                width=12
            ),
            className="mb-4"
        ),
    ]
)