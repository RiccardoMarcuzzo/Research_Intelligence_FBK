import textwrap
import io
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import dash_bootstrap_components as dbc

from dash import html, dcc
from plotly.colors import qualitative
from utils import orgs_df, projects_df, org_topics_df

# FUNZIONI PER LA SEZIONE DI CONFRONTO TRA DUE ORGANIZZAZIONI
orgs_names = orgs_df['name']
def update_dropdown(search_value):
    filtered = orgs_names[
        orgs_names.str.contains(search_value, case=False, na=False)
    ].head(20)
    return [{'label': org, 'value': org} for org in filtered]

def populate_kpis(org_df):
    
    tot_proj = str(org_df['projectIDs'].explode().nunique())

    eur = org_df['netEcContribution'].sum()
    tot_eur = f'{round(eur / 1_000_000, 1)} M'

    tot_publ = str(org_df['scopusID'].explode().nunique())

    tot_tops = str(org_df['topic_name'].nunique())

    return tot_proj, tot_eur, tot_publ, tot_tops

def smart_wrap(text, width=50):
    """Wrappa il testo preservando le parole intere"""
    if len(text) <= width:
        return text
    return '<br>'.join(textwrap.wrap(text, width=width, break_long_words=False))

def compare_organisations(org1_docs, org2_docs):
    org1_docs = pd.DataFrame(org1_docs)
    org2_docs = pd.DataFrame(org2_docs)
    
    merged_docs = pd.concat([org1_docs, org2_docs], ignore_index=True)
    common_rcns = merged_docs['projectID'][merged_docs['projectID'].duplicated()].unique()
    common_projects = merged_docs[merged_docs['projectID'].isin(common_rcns)].drop_duplicates(subset='projectID')

    if common_projects.empty:
        return html.P(
            "These organisations have never collaborated.",
            className="text-muted fst-italic",
            style={'fontSize': '0.9rem'}
        )

    accordion_items = [
        dbc.AccordionItem(
            html.Div([
                html.A(
                    [f'• {proj.title}', html.I(className="bi bi-box-arrow-up-right ms-2")],
                    href=f'https://www.google.com/search?q=CORDIS%20{proj.title}',
                    target='_blank', rel='noopener noreferrer',
                    style={'textDecoration': 'none', 'display': 'block',
                           'marginBottom': '8px', 'color': '#007BFF'}
                )
                for proj in group.itertuples()
            ], style={'padding': '5px 0'}),
            title=f"{topic} ({len(group)} projects)",
            item_id=f"topic-{idx}"
        )
        for idx, (topic, group) in enumerate(common_projects.groupby('topic_name'))
    ]

    return html.Div(
        dbc.Accordion(accordion_items, start_collapsed=True, flush=True, className="mb-0"),
        className='border rounded',
        style={'maxHeight': '400px', 'overflowY': 'auto', 'backgroundColor': 'rgba(255, 255, 255, 0.08)'}
    )


def show_info(selected_org, metric='n_progetti', fp_list=[], display_projects=True):

    # STEP 1: Filtra progetti per organisationID
    row = orgs_df[orgs_df['name'] == selected_org]
    org_data = org_topics_df[org_topics_df['organisationID'].isin(row['organisationID'].unique())]

    row = row.iloc[0]
    filtered_projects = (
        projects_df[projects_df['projectID'].isin(row['projectIDs'])]
        .copy()
        .pipe(lambda df: df[df['fp'].isin(fp_list)])
    )

    # STEP 2: Filtra per Framework Programme
    proj_filtered = org_data[org_data['fp'].isin(fp_list)]

    # STEP 3: Verifica se ci sono progetti dopo il filtro FP
    if proj_filtered.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"No projects found for selected framework programme",
            xaxis_title='',
            yaxis_title='',
            annotations=[{
                'text': 'Try selecting different framework programmes',
                'xref': 'paper',
                'yref': 'paper',
                'x': 0.5,
                'y': 0.5,
                'showarrow': False,
                'font': {'size': 16, 'color': 'gray'}
            }]
        )
        return [dcc.Graph(figure=fig, config={'scrollZoom': True})], None, None, 'N/A', 'N/A', 'N/A', 'N/A'

    proj_filtered['topic_name'] = proj_filtered['topic_name_hierarchy'].apply(
        lambda x: next((el for el in x if el != 'Unlabelled'), '')
    )

    org_stats = proj_filtered.groupby('topic_name').agg({
        'n_proj': 'sum',
        'netEcContribution': 'sum',
        'n_publ': 'sum'
    }).reset_index()

    org_stats['custom_hover'] = (
        '<b>' + org_stats['topic_name'] + '</b><br><i>' +
        org_stats['n_proj'].astype(str) + ' projects<br>' +
        org_stats['netEcContribution'].astype(str) + ' € funded<br>' +
        org_stats['n_publ'].astype(str) + ' publications</i>' +
        '<extra></extra>'
    )   

    if metric == 'n_progetti':
        x_label = 'Number of projects'

        org_stats = org_stats.drop(columns=['netEcContribution', 'n_publ'])
        org_stats.rename(columns={'n_proj': 'value'}, inplace=True)        

    elif metric == 'euro_finanziamenti':
        x_label = 'Funding amount (€)'

        org_stats = org_stats.drop(columns=['n_proj', 'n_publ'])
        org_stats.rename(columns={'netEcContribution': 'value'}, inplace=True)        

    else: # n_publ
        x_label = 'Number of publications'

        org_stats = org_stats.drop(columns=['n_proj', 'netEcContribution'])
        org_stats.rename(columns={'n_publ': 'value'}, inplace=True)
        
    palette = qualitative.Dark24
    org_stats['colors'] = [
        palette[i % len(palette)] for i in range(len(org_stats))
    ]

    # STEP 5: Crea il grafico
    fig = go.Figure(data=[
        go.Bar(
            x=org_stats['value'],
            y=org_stats['topic_name'],
            orientation='h',
            hovertemplate=org_stats['custom_hover'],
            marker=dict(
                color=org_stats['colors'],
                showscale=False,
                colorbar=dict(title=x_label)
            )
        )
    ])

    fig.update_layout(
        font_size=10,
        margin=dict(l=0, r=20, t=30, b=30),
        showlegend=False,
        dragmode='pan',
        xaxis_title=x_label,
        yaxis_title=None,
        height=max(150, 30 * len(org_stats)) if len(org_stats) <= 10 else 20 * len(org_stats),
        hovermode='closest'
    )

    # STEP 6: Header organization
    info_elements = []
    country_code = row.get('country_code')
    if pd.notna(country_code):
        flag = chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)
        info_elements.append(html.P(f"{flag} {country_code}", style={'marginRight': '15px'}))
    url = row.get('organizationUrl')
    if pd.notna(url):
        info_elements.append(html.A(
            f'{url}', href=url, target='_blank', rel='noopener noreferrer',
            style={'textDecoration': 'none', 'color': '#007BFF', 'marginRight': '15px'}
        ))
    activity_type = row.get('activityType')
    if pd.notna(activity_type):
        info_elements.append(html.P(f"Type: {activity_type}"))

    org_header = [
        html.H3(selected_org, style={'marginBottom': '5px'}),
        html.Div(info_elements, style={
            'display': 'flex', 'flexWrap': 'wrap',
            'alignItems': 'center', 'fontSize': '14px', 'marginBottom': '10px'
        }),
    ]

    graph_row = dbc.Row(
        dcc.Graph(figure=fig, config={'scrollZoom': True}),
        className="mb-3"
    )

    graph_row = dbc.Row(
        dcc.Graph(figure=fig, config={'scrollZoom': True}),
        className="mb-3"
    )

    # --- ACCORDION PROGETTI ---
    if display_projects:
        accordion_items = [
            dbc.AccordionItem(
                html.Div([
                    html.A(
                        [f'• {proj.title}', html.I(className="bi bi-box-arrow-up-right ms-2")],
                        href=f'https://cordis.europa.eu/project/id/{proj.projectID}',
                        target='_blank', rel='noopener noreferrer',
                        style={'textDecoration': 'none', 'display': 'block',
                               'marginBottom': '8px', 'color': '#007BFF'}
                    )
                    for proj in group.itertuples()
                ], style={'padding': '5px 0'}),
                title=f"{topic} ({len(group)} projects)",
                item_id=f"topic-{idx}"
            )
            for idx, (topic, group) in enumerate(filtered_projects.groupby('topic_name', observed=True))
        ]

        accordion_row = html.Div(
            [
                html.H5("Projects:", className="mb-2"),
                dbc.Accordion(accordion_items, start_collapsed=True, flush=True, className="mb-0"),
            ],
            style={'maxHeight': '400px', 'height': '400px', 
                   'boxSizing': 'border-box',
                   'overflowY': 'auto'}
            )
        content_layout = org_header + [dbc.Col([graph_row, accordion_row])]
    else:
        content_layout = org_header + [dbc.Col([graph_row])]

    tot_proj, tot_eur, tot_publ, tot_tops = populate_kpis(proj_filtered)

    return content_layout, filtered_projects.to_dict('records'), proj_filtered.to_json(orient='split'), tot_proj, tot_eur, tot_publ, tot_tops

def polish_df(df: pd.DataFrame, org_name):
    df = df.drop(columns=['topic_name_hierarchy', 'n_proj', 'n_publ'])
    df = df.explode('projectIDs').reset_index(drop=True)
    df = df.rename(columns={'projectIDs': 'projectID', 'name': 'org_name'})
    df = df.drop_duplicates(subset=['organisationID', 'projectID']).reset_index(drop=True)

    return df

def download_file(org1, org2, name_org1, name_org2):   
    orgs1 = pd.read_json(io.StringIO(org1), orient='split')
    orgs2 = pd.read_json(io.StringIO(org2), orient='split')

    orgs1 = polish_df(orgs1, name_org1)
    orgs2 = polish_df(orgs2, name_org2)

    final_df = pd.concat([orgs1, orgs2], ignore_index=True)

    return final_df