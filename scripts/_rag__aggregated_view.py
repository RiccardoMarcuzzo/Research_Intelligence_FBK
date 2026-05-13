import json
import pandas as pd
import plotly.express as px

from dash import html, dcc

def build_aggregated_view(filtered_json):
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