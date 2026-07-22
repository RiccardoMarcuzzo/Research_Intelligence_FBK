import dash
import requests
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback

from utils import TITLE
from llm_settings import get_llm_url, get_llm_model, update_llm_settings

PAGE_TITLE = "Settings"

dash.register_page(
    __name__,
    name=PAGE_TITLE,
    title=f"{PAGE_TITLE} | {TITLE}",
    path='/settings',
    order=5
)

#--------------------------------------------
# LAYOUT
#--------------------------------------------
layout = dbc.Container(
    [
        html.H1("Settings", className="fw-bold mb-3 mt-4"),
        html.P(
            "Configure the local LLM used for the per-project chat on the Projects page.",
            className="text-muted mb-4",
            style={'fontSize': '1.05rem'}
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.Label("Ollama server URL", className="form-label fw-semibold"),
                    dbc.Input(
                        id='llm-url-input',
                        type='text',
                        value=get_llm_url(),
                        placeholder='http://127.0.0.1:11434',
                        className='mb-2',
                    ),
                    dbc.Button(
                        "Test connection",
                        id='llm-test-btn',
                        color='secondary',
                        outline=True,
                        size='sm',
                        className='mb-3',
                    ),
                    html.Div(id='llm-test-status', className='mb-4'),

                    html.Label("Model", className="form-label fw-semibold"),
                    dcc.Dropdown(
                        id='llm-model-dropdown',
                        options=[{'label': get_llm_model(), 'value': get_llm_model()}],
                        value=get_llm_model(),
                        clearable=False,
                        className='mb-1',
                    ),
                    html.P(
                        'Click "Test connection" to list the models actually installed on that server.',
                        className='text-muted mb-3',
                        style={'fontSize': '0.85rem'}
                    ),

                    dbc.Button("Save settings", id='llm-save-btn', color='primary'),
                    html.Div(id='llm-save-status', className='mt-3'),
                ]
            ),
            className='shadow-sm',
            style={'maxWidth': '600px'},
        ),
    ],
    className="px-4",
)

#--------------------------------------------
# CALLBACK
#--------------------------------------------
@callback(
    Output('llm-test-status', 'children'),
    Output('llm-model-dropdown', 'options'),
    Output('llm-model-dropdown', 'value'),
    Input('llm-test-btn', 'n_clicks'),
    State('llm-url-input', 'value'),
    State('llm-model-dropdown', 'value'),
    prevent_initial_call=True,
)
def test_connection(n_clicks, url, current_model):
    if not url or not url.strip():
        return dbc.Alert("Enter a URL first.", color='warning', className='mb-0 py-2'), dash.no_update, dash.no_update

    try:
        response = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = [m['name'] for m in response.json().get('models', [])]
    except Exception as e:
        return (
            dbc.Alert(f"⚠️ Could not connect: {e}", color='danger', className='mb-0 py-2'),
            dash.no_update,
            dash.no_update,
        )

    if not models:
        return (
            dbc.Alert("Connected, but no models are installed on this Ollama server.", color='warning', className='mb-0 py-2'),
            [],
            None,
        )

    options = [{'label': m, 'value': m} for m in models]
    new_value = current_model if current_model in models else models[0]

    return (
        dbc.Alert(f"✅ Connected — found {len(models)} model(s).", color='success', className='mb-0 py-2'),
        options,
        new_value,
    )


@callback(
    Output('llm-save-status', 'children'),
    Input('llm-save-btn', 'n_clicks'),
    State('llm-url-input', 'value'),
    State('llm-model-dropdown', 'value'),
    prevent_initial_call=True,
)
def save_settings(n_clicks, url, model):
    if not url or not url.strip() or not model:
        return dbc.Alert("URL and model are both required.", color='warning', className='mb-0 py-2')

    update_llm_settings(llm_url=url, llm_model=model)

    return dbc.Alert(
        "Settings saved — applies immediately to new chat messages.",
        color='success',
        className='mb-0 py-2'
    )
