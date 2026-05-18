import json
import pandas as pd
import plotly.express as px
import dash_bootstrap_components as dbc

from dash import html, dcc

from utils import org_projects_df, projects_df

def format_money(value):
    if value >= 1_000_000:
        return f"€ {value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"€ {value/1_000:.0f}K"
    return f"€ {value:,.0f}"

def make_kpi_card(label, value, section_id=None, clickable=True):
    is_single = not isinstance(value, int) or isinstance(value, str)
    display = value if is_single else str(value)

    base_style = {
        "padding": "1rem",
        "borderRadius": "8px",
        "display": "flex",
        "flexDirection": "column",
        "gap": "6px",
    }

    if clickable and not is_single:
        card_style = {**base_style,
            "background": "white",
            "border": "0.5px solid rgba(0,0,0,0.2)",
            "cursor": "pointer",
            "textDecoration": "none",
        }
        return html.A(
            href=f"#{section_id}",
            style=card_style,
            children=[
                html.Span(label, style={"fontSize": "12px", "color": "#888", "textTransform": "uppercase", "letterSpacing": "0.04em"}),
                html.Span(f"{display} →", style={"fontSize": "22px", "fontWeight": "500", "color": "#3763ca"}),
            ]
        )
    else:
        card_style = {**base_style, "background": "#f5f5f3"}
        return html.Div(
            style=card_style,
            children=[
                html.Span(label, style={"fontSize": "12px", "color": "#888", "textTransform": "uppercase", "letterSpacing": "0.04em"}),
                html.Span(display, style={"fontSize": "22px", "fontWeight": "500", "color": "black"}),
            ]
        )
    
def build_kpi_row(all_fp, tot_proj, all_country, all_typeorg, all_org, all_topic, tot_money):

    def single_or_count(arr):
        """Restituisce il valore stringa se unico, altrimenti il conteggio int."""
        if len(arr) == 1:
            return str(arr[0])
        elif len(arr) == 0:
            return '0'
        return len(arr)

    fp_dict = {'8': "Horizon 2020", '9': "Horizon Europe"}
    fp_n = single_or_count(all_fp)
    cards = [
        make_kpi_card("FPs", fp_dict.get(fp_n, fp_n), clickable=False),
        make_kpi_card("Projects", tot_proj, clickable=False),
        make_kpi_card("Countries", single_or_count(all_country), section_id="agg_countries"),
        make_kpi_card("Org. Types", single_or_count(all_typeorg), section_id="agg_types"),
        make_kpi_card("Organisations", single_or_count(all_org), section_id="agg_orgs"),
        make_kpi_card("Topics", single_or_count(all_topic), section_id="agg_topics"),
        make_kpi_card("EU Contribution", format_money(tot_money), clickable=False),
    ]

    return html.Div(
        cards,
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(140px, 1fr))",
            "gap": "10px",
            "padding": "1rem 0",
        }
    )

def build_aggregated_view(active_indices, coordinator_indices, is_coordinator, country_list, typeorg_list, org_list, topic_list):
    
    if is_coordinator:
        valid_projects = projects_df.iloc[coordinator_indices]['projectID'].tolist()
    else:
        valid_projects = projects_df.iloc[active_indices]['projectID'].tolist()

    data = org_projects_df[org_projects_df['projectID'].isin(valid_projects)].copy()

    if country_list:
        data = data[data['countryCode'].isin(country_list)]
    if typeorg_list:
        data = data[data['activityType'].isin(typeorg_list)]
    if org_list:
        data = data[data['name'].isin(org_list)]

    last_valid = lambda x: x.tail(1)

    data = data.groupby(by=['organisationID', 'role', 'topic_name', 'fp'],
                        observed=True,
                        as_index=False
                        ).agg({'name': last_valid,
                               'projectID': list, 
                               'countryCode': last_valid,
                               'activityType': last_valid,
                               'netEcContribution': 'sum'})

    all_fp =        data['fp'].unique()
    tot_proj =      data['projectID'].explode().nunique()
    all_country =   country_list    or data['countryCode'].unique()
    all_typeorg =   typeorg_list    or data['activityType'].unique()
    all_org =       org_list        or data['name'].unique()
    all_topic =     topic_list      or data['topic_name'].unique()
    tot_money =     data['netEcContribution'].sum()

    kpi_row = build_kpi_row(all_fp, tot_proj, all_country, all_typeorg, all_org, all_topic, tot_money)

    controls_row = html.Div([
        # Radio buttons orizzontali
        dbc.RadioItems(
            id="metrics-radio",
            options=[
                {"label": "Projects produced",   "value": "project"},
                {"label": "Funding amount", "value": "funding"},
                {"label": "Organisations involved",      "value": "org"},
            ],
            value="project",
            inline=True, 
            className="mb-3"
        ),
    ], className="mt-3 d-flex flex-column align-items-center")

    graph_area = html.Div(id="agg-graph-container")

    return html.Div(children=[kpi_row, controls_row, graph_area], id="aggregated-view"), data.to_json(orient='records')

def build_graph(data, by_col, metric_col, metric_text, topk=10):
    TITLE_MAP = {'countryCode': 'Country', 'name': 'Organisation', 'topic_name': 'Topic', 'activityType': 'Activity Type'}

    agg_dict = {'projectID': lambda x: x.explode().nunique(), 'netEcContribution': 'sum',
                **({'name': 'nunique'} if by_col != 'name' else {})}

    graph_data = data.groupby(by=by_col, as_index=False).agg(agg_dict)
    graph_title = f"{metric_text} per {TITLE_MAP[by_col]}"

    if by_col == 'name':
        graph_data = graph_data.nlargest(topk, metric_col)
        graph_title += f' - Top {topk} Players'

    graph_data = graph_data.sort_values(metric_col, ascending=True)
    graph_data['custom_hover'] = (
        '<b>' + graph_data[by_col].astype(str) + '</b><br>' +
        graph_data['projectID'].astype(str) + ' projects<br>' +
        graph_data['netEcContribution'].astype(str) + ' € funded<br>' +
        graph_data['name'].astype(str) + ' organisations<br>'
    )

    if by_col == 'activityType':
        graph_fig = px.pie(graph_data, values=metric_col, names=by_col, title=graph_title, hole=0.4)
    else:
        graph_fig = px.bar(graph_data, x=metric_col, y=by_col, orientation='h', title=graph_title,
                           color=metric_col, color_continuous_scale='Emrld', template="plotly_white")
        graph_fig.update_coloraxes(showscale=False)

    graph_fig.update_traces(hovertemplate=graph_data['custom_hover'])
    graph_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), yaxis_title='', xaxis_title=metric_text)
    return graph_fig

def build_aggregated_graphs(metric, data):
    data = pd.DataFrame(json.loads(data))

    if data.empty:
        return []

    layout = []

    metric_metadata = {
        'project': {'col': 'projectID', 'text': 'Number of projects'}, 
        'funding': {'col': 'netEcContribution', 'text': 'Funding amount'},
        'org': {'col': 'name', 'text': 'Number of organisations'}
    }

    col = metric_metadata[metric]['col']
    text = metric_metadata[metric]['text']

    charts = []
    if data['countryCode'].explode().nunique() > 1:
        country_fig = build_graph(data, 'countryCode', col, text)
        charts.append({'fig': country_fig, 'id': 'agg_countries'})

    if data['activityType'].explode().nunique() > 1:
        type_fig = build_graph(data, 'activityType', col, text)
        charts.append({'fig': type_fig, 'id': 'agg_types'})
     
    col_width = {"size": 8, "offset": 2} if len(charts) == 1 else None
    xs, lg = (12, 12) if len(charts) == 1 else (12, 6)

    layout.append(dbc.Row([
        dbc.Col(dcc.Graph(figure=c['fig'], id=c['id']), width=col_width, xs=xs, lg=lg)
        for c in charts
    ]))

    if metric != 'org' and data['name'].explode().nunique() > 1:
        layout.append(html.Hr(className="my-1 border-3"))
        layout.append(dcc.Slider(5, 30, 5, value=10, id='slider-agg-orgs', className='mt-2'))
        layout.append(dbc.Row(
            dbc.Col(id='agg-orgs-container', width={"size": 8, "offset": 2}, xs=12, lg=12))
        )

    if data['topic_name'].explode().nunique() > 1:
        layout.append(html.Hr(className="my-1 border-3"))
        topic_fig = build_graph(data, 'topic_name', col, text)
        layout.append(dbc.Row(
            dbc.Col(dcc.Graph(figure=topic_fig, id='agg_topics'), width={"size": 8, "offset": 2}, xs=12, lg=12))
        )

    return html.Div(layout, style={"display": "flex", "flexDirection": "column", "gap": "1.5rem"})