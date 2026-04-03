import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, clientside_callback
from utils import TITLE, base_path, PORT

FBK_LOGO = 'assets/img/fbk-logo-blue.png'

app = dash.Dash(
    title=TITLE,
    external_stylesheets=[dbc.themes.CYBORG, dbc.icons.BOOTSTRAP],
    use_pages=True,
    routes_pathname_prefix=base_path,
    requests_pathname_prefix=base_path,
)

@app.server.route("/")
def redirect_root():
    from flask import redirect
    return redirect(base_path)

NAVBAR = {
    "Topics":        {"relative_path": f"{base_path}"},
    "Organisations": {"relative_path": f"{base_path}organisations"},
    "Ask AI":        {"relative_path": f"{base_path}askAI"},
    "Concept":       {"relative_path": f"{base_path}concept"},
}

def generate_nav_links(current_path):
    nav_items = []
    for label, details in NAVBAR.items():
        is_overview = label == "Concept"
        is_active   = details["relative_path"] == current_path
        base_style  = {
            "fontSize": "1.05rem",
            "fontWeight": "600" if is_overview else "500",
            "color": "#ffffff",
            "borderRadius": "6px",
            "padding": "0.3rem 1rem" if is_overview else "0.3rem 0.8rem",
            "marginLeft": "0.25rem",
        }
        if is_overview:
            base_style.update({
                "border": "2px solid #ffffff",
                "backgroundColor": "rgba(255,255,255,0.15)" if is_active else "transparent",
            })
        else:
            base_style["backgroundColor"] = "rgba(255,255,255,0.2)" if is_active else "transparent"

        nav_items.append(
            dbc.NavLink(label, href=details["relative_path"], style=base_style)
        )
    return nav_items

navbar = html.Div([
    html.Div([

        # Sinistra: logo + titolo 
        html.Div([
            html.Img(src=FBK_LOGO, height="34px"),
            html.Span([
                "Ex-CORDIS",
                html.Span(
                    ": research intelligence tool",
                    className="navbar-subtitle",
                    style={"fontWeight": "400", "opacity": "0.8",
                           "fontSize": "28px", "marginLeft": "12px"},
                ),
            ], className="navbar-title"),
        ], className="navbar-left"),

        # Destra: link (desktop) + hamburger (mobile)
        html.Div([
            # Link desktop (nascosti su mobile via CSS)
            html.Div(id="top-nav", className="navbar-right-links"),

            # Hamburger button (visibile solo su mobile via CSS)
            html.Button(
                html.I(className="bi bi-list", style={"fontSize": "1.6rem"}),
                id="hamburger-btn",
                className="hamburger-btn",
                n_clicks=0,
            ),
        ], className="navbar-right"),

    ], className="navbar-wrapper"),

    # Menu mobile a tendina
    html.Div(id="mobile-menu", className="mobile-menu"),

], id="main-navbar", style={
    "position": "fixed",
    "top": "0", "left": "0", "right": "0",
    "zIndex": "1000",
})

content = html.Div(
    dash.page_container,
    style={"padding": "2rem", "paddingTop": "80px"},
)

app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="menu-open", data=False),
    navbar,
    content,
])


@app.callback(
    Output("top-nav",     "children"),
    Output("mobile-menu", "children"),
    Input("url", "pathname"),
)
def update_nav(pathname):
    links = generate_nav_links(pathname)
    mobile_links = []
    for label, details in NAVBAR.items():
        is_active = details["relative_path"] == pathname
        mobile_links.append(
            dbc.NavLink(label, href=details["relative_path"],
                        style={
                            "color": "#ffffff",
                            "fontWeight": "600" if label == "Concept" else "500",
                            "fontSize": "1.1rem",
                            "padding": "0.75rem 1.5rem",
                            "borderBottom": "1px solid rgba(255,255,255,0.1)",
                            "backgroundColor": "rgba(255,255,255,0.12)" if is_active else "transparent",
                        })
        )
    return links, mobile_links


app.clientside_callback(
    """
    function(pathname, n_clicks) {
        const menu   = document.getElementById('mobile-menu');
        const btn    = document.getElementById('hamburger-btn');
        if (!menu || !btn) return [false, 'mobile-menu'];

        const triggered = dash_clientside.callback_context.triggered[0].prop_id;
        const isOpen    = menu.classList.contains('open');

        if (triggered === 'url.pathname') {
            btn.innerHTML = '<i class="bi bi-list" style="font-size:1.6rem"></i>';
            return [false, 'mobile-menu'];
        }

        const newOpen = !isOpen;
        btn.innerHTML = newOpen
            ? '<i class="bi bi-x-lg" style="font-size:1.6rem"></i>'
            : '<i class="bi bi-list" style="font-size:1.6rem"></i>';
        return [newOpen, newOpen ? 'mobile-menu open' : 'mobile-menu'];
    }
    """,
    Output("menu-open",       "data"),
    Output("mobile-menu",     "className"),
    Input("url",              "pathname"),
    Input("hamburger-btn",    "n_clicks"),
    prevent_initial_call=True,
)

app.clientside_callback(
    """
    function(is_open) {
        function handleOutsideClick(e) {
            const navbar = document.getElementById('main-navbar');
            if (navbar && !navbar.contains(e.target)) {
                document.removeEventListener('click', handleOutsideClick);
                const menu = document.getElementById('mobile-menu');
                const btn  = document.getElementById('hamburger-btn');
                if (menu) menu.className = 'mobile-menu';
                if (btn)  btn.innerHTML  = '<i class="bi bi-list" style="font-size:1.6rem"></i>';
            }
        }
        if (is_open) {
            setTimeout(() => document.addEventListener('click', handleOutsideClick), 0);
        } else {
            document.removeEventListener('click', handleOutsideClick);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("menu-open", "data", allow_duplicate=True),
    Input("menu-open",  "data"),
    prevent_initial_call=True,
)


if __name__ == "__main__":
    app.run(debug=True, port=PORT, host="0.0.0.0")