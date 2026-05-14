import json
import pandas as pd
import plotly.express as px
import dash_bootstrap_components as dbc

from dash import html, dcc

from utils import org_projects_df

def obuild_aggregated_view(filtered_json, *args):
    filtered_projects = pd.DataFrame(json.loads(filtered_json))

# 1. DATI FITTIZI (Simulazione Horizon Europe)
    df_countries = pd.DataFrame({
        "Stato": ["Germania", "Francia", "Italia", "Spagna", "Olanda"],
        "Progetti": [124, 110, 98, 85, 62]
    }).sort_values(by="Progetti")

    df_org_types = pd.DataFrame({
        "Tipo": ["Università (HES)", "Ricerca (REC)", "Privati (PRC)", "Pubblici (PUB)"],
        "Budget": [45000000, 32000000, 28000000, 10000000]
    })

    # Metriche per il cruscotto
    total_deliverables = 150
    completed_deliverables = 112
    completion_rate = (completed_deliverables / total_deliverables) * 100

    # 2. GRAFICO: Progetti per Stato (Bar Orizzontale)
    fig_bar = px.bar(
        df_countries, 
        x="Progetti", 
        y="Stato", 
        orientation='h',
        title="N. Progetti per Stato Membro",
        color="Progetti",
        color_continuous_scale="Viridis",
        template="plotly_white"
    )
    fig_bar.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=False)

    # 3. GRAFICO: Budget per Tipo Organizzazione (Pie)
    fig_pie = px.pie(
        df_org_types, 
        values='Budget', 
        names='Tipo', 
        title="Ripartizione Fondi per Tipo Organizzazione",
        hole=0.4
    )
    fig_pie.update_traces(textinfo='percent+label')
    fig_pie.update_layout(margin=dict(l=20, r=20, t=40, b=20))

    # 5. LAYOUT DASH
    return html.Div([
        html.H2("PROOF OF CONCEPT AGGREGATED VIEW ", 
                style={'textAlign': 'center', 'color': '#2c3e50', 'fontFamily': 'Arial'}),
        
        # Statistiche rapide (KPI)
        html.Div([
            html.Div([
                html.B("Progetti Totali: "), "432"
            ], style={'padding': '15px', 'border': '1px solid #ddd', 'borderRadius': '5px', 'color': 'black'}),
            html.Div([
                html.B("Budget Totale: "), "€ 115M"
            ], style={'padding': '15px', 'border': '1px solid #ddd', 'borderRadius': '5px'}),
        ], style={'display': 'flex', 'gap': '20px', 'justifyContent': 'center', 'marginBottom': '30px', 'color': 'black'}),

        # Griglia Grafici
        html.Div([
            html.Div([dcc.Graph(figure=fig_bar)], style={'width': '48%'}),
            html.Div([dcc.Graph(figure=fig_pie)], style={'width': '48%'})
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'flexWrap': 'wrap'}),
               
    ], style={'padding': '30px', 'backgroundColor': '#f4f7f9'})

def format_money(value):
    if value >= 1_000_000:
        return f"€ {value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"€ {value/1_000:.0f}K"
    return f"€ {value:,.0f}"

def make_kpi_card(label, value, section_id=None, clickable=True):
    """
    Se clickable=True e len > 1, la card è cliccabile e linka a section_id.
    Se c'è un solo elemento, mostra il valore stringa invece del conteggio.
    """
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

def build_aggregated_view(filtered_json, country_list, typeorg_list, org_list, topic_list):
    valid_projects = [p['projectID'] for p in json.loads(filtered_json)]
    
    data = org_projects_df[org_projects_df['projectID'].isin(valid_projects)].copy()

    if country_list:
        data = data[data['countryCode'].isin(country_list)]
    if typeorg_list:
        data = data[data['activityType'].isin(typeorg_list)]
    if org_list:
        data = data[data['name'].apply(lambda x: x.title()).isin(org_list)]

    data = data.groupby(by=['organisationID', 'role', 'topic_name', 'fp'],
                        observed=True,
                        as_index=False
                        ).agg({'name': lambda x: x.tail(1),
                               'projectID': list, 
                               'countryCode': lambda x: x.tail(1),
                               'activityType': lambda x: x.tail(1),
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
        # Toggle switch
        dbc.Switch(
            id="coordinator-toggle",
            label="Show coordinator only",
            value=False,
            className="mb-3"
        ),

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

def build_aggregated_graphs(is_coordinator, metric, data):
    data = pd.DataFrame(json.loads(data))
    layout = []

    agg_func = {
        'project': {'projectID': lambda x: x.explode().nunique()}, # se metric==project, allora deve contare gli elementi unici in data['projectID'] per ogni riga
        'funding': {'netEcContribution': 'sum'}, # se metric==funding, allora deve sommare nel groupby
        'org': {'name': 'nunique'} # se metric==org, allora deve contare gli elementi unici in data['name']
    }
    metric_metadata = {
        'project': {'col': 'projectID', 'text': 'Number of projects'}, 
        'funding': {'col': 'netEcContribution', 'text': 'Funding amount'},
        'org': {'col': 'name', 'text': 'Number of organisations'}
    }

    if is_coordinator:
        data = data[data['role'] == 'coordinator']

    charts = []
    if data['countryCode'].explode().nunique() > 1:
        country_data = (data.groupby(by='countryCode', as_index=False)
                        .agg(agg_func[metric])
                        .rename(columns={metric_metadata[metric]['col']: 'value'}))
        country_fig = px.bar(
            country_data, 
            x="value", 
            y="countryCode", 
            orientation='h',
            title=f"{metric_metadata[metric]['text']} per Country",
            color="value",
            color_continuous_scale="Viridis",
            template="plotly_white",
        )
        country_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=False)
        charts.append({'fig': country_fig, 'id': 'agg_countries'})

    if data['activityType'].explode().nunique() > 1:
        type_data = (data.groupby(by='activityType', as_index=False)
                     .agg(agg_func[metric])
                     .rename(columns={metric_metadata[metric]['col']: 'value'}))
        type_fig = px.pie(
            type_data, 
            values='value', 
            names='activityType', 
            title=f"{metric_metadata[metric]['text']} per Activity Type",
            hole=0.4,
        )
        type_fig.update_traces(textinfo='percent+label')
        type_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
        charts.append({'fig': type_fig, 'id': 'agg_types'})
     
    col_width = {"size": 8, "offset": 2} if len(charts) == 1 else None
    xs, lg = (12, 12) if len(charts) == 1 else (12, 6)

    layout.append(dbc.Row([
        dbc.Col(dcc.Graph(figure=c['fig'], id=c['id']), width=col_width, xs=xs, lg=lg)
        for c in charts
    ]))

    if metric != 'org' and data['name'].explode().nunique() > 1:
        org_data = (data.groupby(by='name', as_index=False)
                        .agg(agg_func[metric])
                        .rename(columns={metric_metadata[metric]['col']: 'value'}))
        org_fig = px.bar(
            org_data, 
            x="value", 
            y="name", 
            orientation='h',
            title=f"{metric_metadata[metric]['text']} per Organisation",
            color="value",
            color_continuous_scale="Viridis",
            template="plotly_white",
        )
        org_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=False)
        layout.append(dbc.Row(
            dbc.Col(dcc.Graph(figure=org_fig, id='agg_orgs'), width={"size": 8, "offset": 2}, xs=12, lg=12))
        )

    if data['topic_name'].explode().nunique() > 1:
        topic_data = (data.groupby(by='topic_name', as_index=False)
                        .agg(agg_func[metric])
                        .rename(columns={metric_metadata[metric]['col']: 'value'}))
        topic_fig = px.bar(
            topic_data, 
            x="value", 
            y="topic_name", 
            orientation='h',
            title=f"{metric_metadata[metric]['text']} per Topic",
            color="value",
            color_continuous_scale="Viridis",
            template="plotly_white",
        )
        topic_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=False)
        layout.append(dbc.Row(
            dbc.Col(dcc.Graph(figure=topic_fig, id='agg_topics'), width={"size": 8, "offset": 2}, xs=12, lg=12))
        )
    

    return html.Div(layout, style={"display": "flex", "flexDirection": "column", "gap": "1.5rem"})