import dash
import argparse
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output
from utils import TITLE

# Configurazione CLI 
parser = argparse.ArgumentParser(description="Lancio della Dashboard Dash")

parser.add_argument("--path", type=str, default="/research_intelligence/", help="Percorso base dell'app (es: /research_intelligence/)")
parser.add_argument("--port", type=int, default=8050, help="Porta di esecuzione")
args = parser.parse_args()

# Pulizia del path
base_path = args.path
if not base_path.startswith('/'): base_path = '/' + base_path
if not base_path.endswith('/'): base_path = base_path + '/'

FBK_LOGO = 'assets/img/fbk-logo-blue.png'

app = dash.Dash(title=TITLE, external_stylesheets=[dbc.themes.CYBORG, dbc.icons.BOOTSTRAP],
                use_pages=True, routes_pathname_prefix=base_path, requests_pathname_prefix=base_path)

NAVBAR = {
    "Topics": {"relative_path": "/"},
    "Organisations": {"relative_path": "/organisations"},
    "Ask AI": {"relative_path": "/rag"},
    "Concept": {"relative_path": "/overview"},
}

def generate_nav_links(current_path):
    nav_items = []
    for label, details in NAVBAR.items():
        is_overview = label == "Concept"
        is_active = details["relative_path"] == current_path

        if is_overview:
            nav_items.append(
                dbc.NavLink(
                    label,
                    href=details["relative_path"],
                    style={
                        "fontSize": "1.05rem",
                        "fontWeight": "600",
                        "color": "#ffffff",
                        "border": "2px solid #ffffff",
                        "borderRadius": "6px",
                        "padding": "0.3rem 1rem",
                        "marginLeft": "0.5rem",
                        "backgroundColor": "rgba(255,255,255,0.15)" if is_active else "transparent",
                    }
                )
            )
        else:
            nav_items.append(
                dbc.NavLink(
                    label,
                    href=details["relative_path"],
                    style={
                        "fontSize": "1.05rem",
                        "fontWeight": "500",
                        "color": "#ffffff",
                        "borderRadius": "6px",
                        "padding": "0.3rem 0.8rem",
                        "marginLeft": "0.25rem",
                        "backgroundColor": "rgba(255,255,255,0.2)" if is_active else "transparent",
                    }
                )
            )
    return nav_items


navbar = html.Div([
    html.Div([
        # Sezione sinistra: logo + titolo
        html.Div([
            html.Img(src=FBK_LOGO, height="34px"),
            html.Span([
                "Ex-CORDIS: ",
                html.Span("research intelligence tool", style={"fontWeight": "400", "opacity": "0.8", "fontSize": "28px", "marginLeft": "12px"})
            ], className="navbar-title"),
        ], className="navbar-left"),

        # Sezione destra: link navigazione
        html.Div(
            id="top-nav",
            className="navbar-right",
        ),
    ], className="navbar-wrapper"),
], style={
    "position": "fixed",
    "top": "0",
    "left": "0",
    "right": "0",
    "zIndex": "1000",
})

content = html.Div(
    dash.page_container,
    style={"padding": "2rem", 'paddingTop': '80px'},
)

app.layout = html.Div([
    dcc.Location(id="url"),
    navbar,
    content,
])


@app.callback(Output("top-nav", "children"), Input("url", "pathname"))
def update_nav(pathname):
    return generate_nav_links(pathname)


if __name__ == "__main__":
    app.run(debug=True, port=args.port)