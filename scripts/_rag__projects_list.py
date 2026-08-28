import json
import urllib.request

import httpx
import dash_bootstrap_components as dbc
from dash import html, dcc
from utils import BASE_URL, API_KEY, projects_tbl

PROJECT_COLUMNS = ["projectID", "title", "fp", "topic_name_hierarchy", "participants", "objective",
                   "has_deliverable", "has_publication"]

def build_collapsible_table_section(label, project_id, section_key, has_rows):
    if label not in ("Deliverables", "Publications"):
        return None
    if not has_rows:  # False o None → niente sezione
        return None

    toggle_id = {'type': 'section-toggle', 'project': project_id, 'section': section_key}
    collapse_id = {'type': 'section-collapse', 'project': project_id, 'section': section_key}
    chevron_id = {'type': 'section-chevron', 'project': project_id, 'section': section_key}

    header = html.Div(
        [
            html.Strong(f"{label}: "),
            html.Span(
                "▸",
                id=chevron_id,
                style={
                    'display': 'inline-block',
                    'transition': 'transform 0.2s ease',
                    'marginLeft': '6px',
                    'cursor': 'pointer',
                },
            ),
        ],
        id=toggle_id,
        n_clicks=0,
        style={'cursor': 'pointer', 'userSelect': 'none'},
    )

    collapse = dbc.Collapse(None, id=collapse_id, is_open=False)
    return html.Div([header, collapse], className="mt-2")


def build_accordion_items(project_ids, has_user_input):
    if not project_ids:
        return [], 0

    ids_str = ", ".join(str(int(pid)) for pid in project_ids)
    rows = (
        projects_tbl.search()
        .select(PROJECT_COLUMNS)
        .where(f"projectID IN ({ids_str})")
        .to_arrow()
        .to_pylist()
    )
    rows_by_id = {r['projectID']: r for r in rows}
    ordered_rows = [rows_by_id[pid] for pid in project_ids if pid in rows_by_id]

    accordion_items = []
    for row in ordered_rows:
        cordis_url = f"https://cordis.europa.eu/project/id/{row['projectID']}"
        proj_fp = 'Horizon 2020' if row['fp'] == 8 else 'Horizon Europe'
        proj_hier = ' → '.join([t for t in row['topic_name_hierarchy'] if t != 'Unlabelled'])
        body_children = []

        if has_user_input:
            why_relevant_section = html.Div([
                dbc.Button(
                    [html.I(className="bi bi-stars me-1"), "Why is this relevant?"],
                    id={'type': 'why-relevant-btn', 'index': row['projectID']},
                    outline=True,
                    size="sm",
                    className="mb-2",
                    style={
                        'color': "#f6f5f7",
                        'borderColor': '#6f42c1',
                        'backgroundColor': '#6f42c1'
                    }
                ),
                dcc.Loading(
                    html.Div(
                        id={'type': 'why-relevant-output', 'index': row['projectID']},
                        style={'fontSize': '0.9rem', 'fontStyle': 'italic'}
                    ),
                    type="circle", 
                    color="#0d6efd"
                ),
            ], className="mb-2")
            body_children.append(why_relevant_section)

        header = html.Div([
            html.Span(row['title'], style={'fontWeight': '600'}),
            html.Div([
                html.Small(f"{proj_fp}  ·  {proj_hier}", className="text-muted"),
                html.Br(),
                html.A("View on CORDIS ↗", href=cordis_url, target="_blank",
                    className="text-primary", style={'fontSize': '0.8rem', 'textDecoration': 'none'}),               
            ], className="mt-1")
        ])

        body_children.extend([
            html.P([html.Strong("Participants: "), ', '.join(row['participants'])]),
            html.P([html.Strong("Objective: "), row['objective']]),
        ])

        deliverables_section = build_collapsible_table_section(
            "Deliverables", row['projectID'], 'deliverables', row.get('has_deliverable')
        )
        if deliverables_section is not None:
            body_children.append(deliverables_section)

        publications_section = build_collapsible_table_section(
            "Publications", row['projectID'], 'publications', row.get('has_publication')
        )
        if publications_section is not None:
            body_children.append(publications_section)

        body = html.Div(body_children, style={'textAlign': 'left'})

        accordion_items.append(
            dbc.AccordionItem(body, title=header, item_id=str(row['projectID']))
        )

    return accordion_items, len(accordion_items)


def build_table_content(rows, link_phrase):
    if not rows:
        return html.Div("Nessun risultato.", className="text-muted mt-2")

    for row in rows:
        if row.get('authors'):
            row['authors'] = json.loads(row['authors'])

    table_header = html.Thead(html.Tr([html.Th("Title"), html.Th("Author(s)"), html.Th("Link")]))
    table_body = html.Tbody([
        html.Tr([
            html.Td(row.get('title') or '—'),
            html.Td(
                html.Div([
                    html.Div(f"{name} ({affiliation})") if affiliation != 'Unknown' else html.Div(f"{name}")
                    for name, affiliation in row['authors'].items()
                ]) if row.get('authors') else '—'
            ),
            html.Td(html.A(link_phrase, href=str(row['physUrl']), target="_blank") if row.get('physUrl') else '—'),
        ])
        for row in rows
    ])
    return dbc.Table([table_header, table_body], bordered=False, hover=True, size="sm", color="light", className="mt-2 mb-0")


async def call_relevance_api(project_id, query):
    row = (
        projects_tbl.search()
        .select(["projectID", "title", "objective"])
        .where(f"projectID IN ({project_id})")
        .to_arrow()
    )
    title = row["title"][0].as_py()
    objective = row["objective"][0].as_py()

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "http://research-llm-api-matita:8060/v1/project/relevance",
            #headers={"X-API-Key": API_KEY},
            json={
                "project": {
                    "title": title,
                    "objective": objective,
                },
                "query_context": {
                    "query_text": query,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("explanation", "Explainability bot not available at the moment.")


def call_relevance_api_old(project_id, query):
    row = (
            projects_tbl.search()
            .select(["projectID", "title", "objective"])
            .where(f"projectID IN ({project_id})")
            .to_arrow()
        )   
    title = row["title"][0].as_py()
    objective = row["objective"][0].as_py()       
    payload = {
        "project": {
            "title": title,
            "objective": objective,
        },
        "query_context": {
            "query_text": query,
        },
    }

    req = urllib.request.Request(
        f"{BASE_URL}/v1/project/relevance",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.load(resp)

    return result.get("explanation", "Explainability bot not available at the moment.")
