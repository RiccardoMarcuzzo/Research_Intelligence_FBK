import dash_bootstrap_components as dbc
from dash import html
from utils import projects_df, deliverables_df, publications_df


def build_collapsible_table_section(label, project_id, section_key, rows):

    if label == "Deliverables":
        df = deliverables_df
        link_phrase = 'Download deliverable↗'
    elif label == "Publications":
        df = publications_df
        link_phrase = 'See publication↗'
    else:
        return None

    filtered = df[df['projectID'] == project_id]
    rows = filtered.to_dict('records')

    if not rows:
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

    table_header = html.Thead(
        html.Tr([html.Th("Title"), html.Th("Author(s)"), html.Th("Link")])
    )
    table_body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(row.get('title') or '—'),
                    html.Td(
                        html.Div([
                            html.Div(f"{name} ({affiliation})") 
                            if affiliation != 'Unknown'
                            else html.Div(f"{name}")
                            for name, affiliation in row['authors'].items()
                        ]) if row.get('authors') else '—'
                    ),
                    html.Td(
                        html.A(link_phrase, href=str(row['physUrl']), target="_blank")
                        if row.get('physUrl') else '—'
                    ),
                ]
            )
            for row in rows
        ]
    )

    table = dbc.Table(
        [table_header, table_body],
        bordered=False,
        hover=True,
        size="sm",
        color="light",
        className="mt-2 mb-0",
    )

    collapse = dbc.Collapse(
        table,
        id=collapse_id,
        is_open=False,
    )

    return html.Div([header, collapse], className="mt-2")

def retrieve_deliverable_info(link):
    mask = deliverables_df['physUrl'] == link
    row = deliverables_df[mask]
    if row.empty:
        return {'title': None, 'authors': None, 'link': link}
    return {
        'title': row.iloc[0]['title'], 
        'authors': row.iloc[0]['authors'], 
        'link': link
    }

def build_accordion_items(is_coordinator, active_indices, coordinator_indices):
    if is_coordinator:
        data = projects_df.iloc[coordinator_indices]
    else:
        data = projects_df.iloc[active_indices]

    accordion_items = []
    for _, row in data.iterrows():
        cordis_url = f"https://cordis.europa.eu/project/id/{row['projectID']}"
        proj_fp = 'Horizon 2020' if row['fp'] == 8 else 'Horizon Europe'
        proj_hier = ' → '.join([t for t in row['topic_name_hierarchy'] if t != 'Unlabelled'])

        deliverable_rows = [
            retrieve_deliverable_info(link)
            for link in row['physUrl']
        ]

        publication_rows = []

        header = html.Div([
            html.Span(row['title'], style={'fontWeight': '600'}),
            html.Div([
                html.Small(f"{proj_fp}  ·  {proj_hier}", className="text-muted"),
                html.Br(),
                html.A("View on CORDIS ↗", href=cordis_url, target="_blank",
                       className="text-primary", style={'fontSize': '0.8rem', 'textDecoration': 'none'}),
            ], className="mt-1")
        ])

        body_children = [
            html.P([html.Strong("Participants: "), ', '.join(row['participants'])]),
            html.P([html.Strong("Objective: "), row['objective']]),
        ]

        deliverables_section = build_collapsible_table_section(
            "Deliverables", row['projectID'], 'deliverables', deliverable_rows
        )
        if deliverables_section is not None:
            body_children.append(deliverables_section)

        publications_section = build_collapsible_table_section(
            "Publications", row['projectID'], 'publications', publication_rows
        )
        if publications_section is not None:
            body_children.append(publications_section)

        body = html.Div(body_children, style={'textAlign': 'left'})

        accordion_items.append(
            dbc.AccordionItem(body, title=header, item_id=str(row['projectID']))
        )

    return accordion_items, len(accordion_items)