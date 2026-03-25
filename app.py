import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output
from utils import TITLE, base_path, PORT

FBK_LOGO = 'assets/img/fbk-logo-blue.png'

app = dash.Dash(title=TITLE, external_stylesheets=[dbc.themes.CYBORG, dbc.icons.BOOTSTRAP],
                use_pages=True, routes_pathname_prefix=base_path, requests_pathname_prefix=base_path)

@app.server.route("/")
def redirect_root():
    from flask import redirect
    return redirect(base_path)

NAVBAR = {
    "Topics": {"relative_path": f"{base_path}"}, 
    "Organisations": {"relative_path": f"{base_path}organisations"},
    "Ask AI": {"relative_path": f"{base_path}askAI"},
    "Concept": {"relative_path": f"{base_path}concept"},
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
    app.run(debug=True, port=PORT)