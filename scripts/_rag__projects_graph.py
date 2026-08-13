import os
import json

import numpy as np
import plotly.graph_objects as go
from dash import html, dcc

from utils import projects_tbl, TOPIC_GRAPHS_DIR, RETRIEVAL_THRESHOLD

PROJECT_COLUMNS = ["projectID", "title", "topic_name"]
_INDEX_CACHE = None
_GRAPH_CACHE = {}

CUSTOM_COLORSCALE = [
    [0.0, "#E0E0E0"],
    [0.19, "#E0E0E0"],
    [0.2, "#FFFF00"],
    [0.85, "#FF0000"],
    [1.0, '#2D0054'],
]


def _load_index():
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        with open(os.path.join(TOPIC_GRAPHS_DIR, "_index.json"), encoding="utf-8") as f:
            _INDEX_CACHE = json.load(f)
    return _INDEX_CACHE


def _load_topic_graph(topic_name):
    if topic_name not in _GRAPH_CACHE:
        filename = _load_index().get(topic_name)
        if filename is None:
            _GRAPH_CACHE[topic_name] = {"nodes": {}, "edges": []}
        else:
            with open(os.path.join(TOPIC_GRAPHS_DIR, filename), encoding="utf-8") as f:
                _GRAPH_CACHE[topic_name] = json.load(f)
    return _GRAPH_CACHE[topic_name]


def _merge_ego_networks(project_ids):
    ids_str = ", ".join(str(int(pid)) for pid in project_ids)
    rows = (
        projects_tbl.search()
        .select(PROJECT_COLUMNS)
        .where(f"projectID IN ({ids_str})")
        .to_arrow()
        .to_pylist()
    )
    result_ids = set(project_ids)

    nodes = {}
    edges = {}

    for row in rows:
        pid, topic_name = row['projectID'], row['topic_name']
        graph = _load_topic_graph(topic_name)

        nodes[pid] = {'title': row.get('title', ''), 'topic_name': topic_name, 'group': 'Research Result'}

        for e in graph['edges']:
            if e['source'] != pid and e['target'] != pid:
                continue
            other = e['target'] if e['source'] == pid else e['source']
            key = tuple(sorted((pid, other)))
            edges[key] = {**e, 'topic_name': topic_name}
            if other not in nodes:
                nodes[other] = {
                    'title': graph['nodes'].get(str(other), {}).get('title', ''),
                    'topic_name': topic_name,
                    'group': 'Neighbours' if other not in result_ids else 'Research Result',
                }

    return nodes, list(edges.values())


def _force_directed(node_ids, edges, iterations=20, seed=42):
    n = len(node_ids)
    if n <= 1:
        return {node_ids[0]: (0.0, 0.0)} if n == 1 else {}

    idx = {pid: i for i, pid in enumerate(node_ids)}
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1, 1, size=(n, 2)).astype(np.float32)
    k = np.float32(1.0 / np.sqrt(n))
    edge_idx = [(idx[e['source']], idx[e['target']], e['weight']) for e in edges]

    edge_i = np.array([i for i, j, w in edge_idx])
    edge_j = np.array([j for i, j, w in edge_idx])
    edge_w = np.array([w for i, j, w in edge_idx], dtype=np.float32)
    edge_factor = (np.float32(0.4) + np.float32(0.15) * edge_w)

    k_sq = k ** 2

    for it in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist_sq = np.einsum('ijk,ijk->ij', delta, delta)
        np.fill_diagonal(dist_sq, np.float32(1e-12))
        disp = ((delta / dist_sq[..., None]) * k_sq).sum(axis=1)
        try:
            d = pos[edge_i] - pos[edge_j]
        except IndexError:
            continue
        dist_ij = np.linalg.norm(d, axis=1) + np.float32(1e-6)
        force = (dist_ij ** 2 / k)[:, None] * (d / dist_ij[:, None]) * edge_factor[:, None]
        np.add.at(disp, edge_i, -force * np.float32(0.5))
        np.add.at(disp, edge_j, force * np.float32(0.5))

        temp = np.float32(0.1) * (1 - it / iterations)
        length = np.linalg.norm(disp, axis=1)
        length[length == 0] = np.float32(1e-6)
        pos += (disp / length[:, None]) * np.minimum(length, temp)[:, None]

    pos -= pos.mean(axis=0)
    return {pid: tuple(pos[idx[pid]]) for pid in node_ids}


def _simple_layout(pids, radius=0.8):
    n = len(pids)
    if n == 0:
        return {}
    if n == 1:
        return {pids[0]: (0.0, 0.0)}
    golden_angle = np.pi * (3 - np.sqrt(5))
    pos = {}
    for i, pid in enumerate(pids):
        r = radius * np.sqrt((i + 0.5) / n)
        theta = i * golden_angle
        pos[pid] = (r * np.cos(theta), r * np.sin(theta))
    return pos


def _overview_grid_centers(topics, spacing):
    n_cols = min(5, len(topics))
    centers = {}
    for i, topic in enumerate(topics):
        cx, cy = (i % n_cols) * spacing, -(i // n_cols) * spacing
        centers[topic] = (cx, cy)
    return centers, n_cols


def build_overview_figure(nodes, edges, min_weight, user_input,
                           cell_size=2.0, spacing=3.0):
    node_radius = cell_size / 2 - 0.35  # margine per non sovrapporre l'etichetta

    topics = sorted({n['topic_name'] for n in nodes.values()})
    centers, n_cols = _overview_grid_centers(topics, spacing)

    visible_edges = [e for e in edges if e['weight'] >= min_weight]
    connected_ids = {pid for e in visible_edges for pid in (e['source'], e['target'])}
    visible_ids = {pid for pid, n in nodes.items() if n['group'] == 'Research Result'} | connected_ids
    vis_nodes = {pid: n for pid, n in nodes.items() if pid in visible_ids}

    coords = {}
    for topic in topics:
        pids = [pid for pid, n in vis_nodes.items() if n['topic_name'] == topic]
        local = _simple_layout(pids, radius=node_radius)
        cx, cy = centers[topic]
        for pid, (x, y) in local.items():
            coords[pid] = (cx + x, cy + y)

    # archi disegnati solo se entrambi gli estremi sono nello stesso topic/casella
    edge_x, edge_y = [], []
    for e in visible_edges:
        if e['source'] not in coords or e['target'] not in coords:
            continue
        if vis_nodes[e['source']]['topic_name'] != vis_nodes[e['target']]['topic_name']:
            continue
        x0, y0 = coords[e['source']]
        x1, y1 = coords[e['target']]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode='lines',
        line=dict(width=1, color='#CCCCCC'), hoverinfo='none', showlegend=False,
    ))

    # hitbox invisibile: un marker "quadrato" grande quanto la cella per ogni topic
    fig.add_trace(go.Scatter(
        x=[centers[t][0] for t in topics], y=[centers[t][1] for t in topics],
        mode='markers',
        marker=dict(size=cell_size / spacing * 100, symbol='square', color='rgba(0,0,0,0)'),
        customdata=topics,
        hovertemplate="<b>%{customdata}</b><br><i>Click to expand</i><extra></extra>",
        showlegend=False, name='topic-hitbox',
    ))

    pids_all = list(coords.keys())
    if user_input:
        fig.add_trace(go.Scatter(
            x=[coords[p][0] for p in pids_all], y=[coords[p][1] for p in pids_all],
            mode='markers',
            marker=dict(
                size=[10 if vis_nodes[p]['group'] == 'Research Result' else 5 for p in pids_all],
                color=[vis_nodes[p].get('similarity', 0.0) for p in pids_all],
                colorscale=CUSTOM_COLORSCALE, cmin=0.0, cmax=1.0,
                colorbar=dict(title="Similarity"),
                line=dict(width=0.5, color='DimGray'),
            ),
            customdata=[[vis_nodes[p]['title'], p] for p in pids_all],
            hovertemplate="<b>%{customdata[0]}</b><extra></extra>",
            showlegend=False, name='nodes',
        ))
    else:
        for group, color, size in [('Research Result', '#FF8C00', 10), ('Neighbours', '#E0E0E0', 5)]:
            pids = [p for p in pids_all if vis_nodes[p]['group'] == group]
            fig.add_trace(go.Scatter(
                x=[coords[p][0] for p in pids], y=[coords[p][1] for p in pids],
                mode='markers', name=group,
                marker=dict(size=size, color=color, line=dict(width=0.5, color='DimGray')),
                customdata=[[vis_nodes[p]['title'], p] for p in pids],
                hovertemplate="<b>%{customdata[0]}</b><extra></extra>",
            ))

    for topic in topics:
        cx, cy = centers[topic]
        fig.add_annotation(
            x=cx, y=cy + cell_size / 2 + 0.15,
            text=f"<b>{topic}</b>", showarrow=False,
            font=dict(size=13, color='#333333'), xanchor='center', yanchor='bottom',
        )

    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title="", fixedrange=True),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title="", fixedrange=True),
        margin=dict(l=10, r=10, t=50, b=10),
        height=600, template="plotly_white",
        showlegend=not user_input, dragmode=False, clickmode='event',
    )
    return fig


def build_topic_detail_figure(topic_name, nodes, edges, min_weight, user_input):
    pids_topic = [pid for pid, n in nodes.items() if n['topic_name'] == topic_name]
    topic_edges = [e for e in edges if e['topic_name'] == topic_name]

    local_pos = _force_directed(pids_topic, topic_edges)

    topic_nodes = {
        pid: {**nodes[pid], 'x': local_pos[pid][0], 'y': local_pos[pid][1]}
        for pid in pids_topic
    }
    fig = build_figure(topic_nodes, topic_edges, min_weight, user_input)
    return fig

def build_figure(nodes, edges, min_weight, user_input):
    visible_edges = [e for e in edges if e['weight'] >= min_weight]
    connected_ids = {pid for e in visible_edges for pid in (e['source'], e['target'])}
    visible_ids = {pid for pid, n in nodes.items() if n['group'] == 'Research Result'} | connected_ids
    vis_nodes = {pid: n for pid, n in nodes.items() if pid in visible_ids}

    edge_x, edge_y = [], []
    edge_mid_x, edge_mid_y, edge_hover_text = [], [], []
    for e in visible_edges:
        if e['source'] not in visible_ids or e['target'] not in visible_ids:
            continue
        x0, y0 = vis_nodes[e['source']]['x'], vis_nodes[e['source']]['y']
        x1, y1 = vis_nodes[e['target']]['x'], vis_nodes[e['target']]['y']
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

        edge_mid_x.append((x0 + x1) / 2)
        edge_mid_y.append((y0 + y1) / 2)
        collaborators = e.get('collaborators', [])
        edge_hover_text.append("<br>".join(f"• {c}" for c in collaborators))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode='lines',
        line=dict(width=1, color='#CCCCCC'), hoverinfo='none', showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=edge_mid_x, y=edge_mid_y, mode='markers',
        marker=dict(size=10, color='rgba(0,0,0,0)'),
        text=edge_hover_text,
        hovertemplate="<b>Collaboratori condivisi:</b><br>%{text}<extra></extra>",
        hoverinfo='text', showlegend=False, name='edge-hover',
    ))

    if user_input:
        pids = list(vis_nodes.keys())
        fig.add_trace(go.Scatter(
            x=[vis_nodes[p]['x'] for p in pids],
            y=[vis_nodes[p]['y'] for p in pids],
            mode='markers',
            marker=dict(
                size=[12 if vis_nodes[p]['group'] == 'Research Result' else 6 for p in pids],
                color=[vis_nodes[p].get('similarity', 0.0) for p in pids],
                colorscale=CUSTOM_COLORSCALE, cmin=0.0, cmax=1.0,
                colorbar=dict(title="Similarity"),
                line=dict(width=0.5, color='DimGray'),
            ),
            customdata=[[vis_nodes[p]['title'], p] for p in pids],
            hovertemplate="<b>%{customdata[0]}</b><br><i>Click to view on CORDIS</i><extra></extra>",
            showlegend=False,
        ))
    else:
        for group, color, size in [('Research Result', '#FF8C00', 12), ('Neighbours', '#E0E0E0', 6)]:
            pids = [p for p in vis_nodes if vis_nodes[p]['group'] == group]
            fig.add_trace(go.Scatter(
                x=[vis_nodes[p]['x'] for p in pids],
                y=[vis_nodes[p]['y'] for p in pids],
                mode='markers', name=group,
                marker=dict(size=size, color=color, line=dict(width=0.5, color='DimGray')),
                customdata=[[vis_nodes[p]['title'], p] for p in pids],
                hovertemplate="<b>%{customdata[0]}</b><br><i>Click to view on CORDIS</i><extra></extra>",
            ))

    topic_centers = {}
    for pid, n in vis_nodes.items():
        cx, cy = topic_centers.setdefault(n['topic_name'], ([], []))
        cx.append(n['x'])
        cy.append(n['y'])

    for topic_name, (xs, ys) in topic_centers.items():
        fig.add_annotation(
            x=sum(xs) / len(xs), y=max(ys) + 0.4,
            text=f"<b>{topic_name}</b>", showarrow=False,
            font=dict(size=15, color='#333333'), xanchor='center',
        )

    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=""),
        margin=dict(l=10, r=10, t=50, b=10),
        height=600, template="plotly_white", showlegend=not user_input, dragmode='zoom',
    )
    return fig


def build_project_graph(projects_data, user_input, min_weight=2):
    project_ids = list(projects_data)
    if not project_ids:
        return html.Div(['No projects found. Try different filters.'])
    elif len(project_ids) >= 500:
        return html.Div(['Too many projects. Skipping project graph generation.'])

    nodes, edges = _merge_ego_networks(project_ids)

    if user_input:
        for pid, n in nodes.items():
            n['similarity'] = 0.0
        for i, pid in enumerate(project_ids):
            if pid in nodes:
                nodes[pid]['similarity'] = np.linspace(1.0, 0.2, len(project_ids))[i]

    max_weight = max((e['weight'] for e in edges), default=min_weight)

    overview_fig = build_overview_figure(nodes, edges, min_weight, bool(user_input))

    status_text = "Ogni casella rappresenta un topic: clicca per esplorare i progetti al suo interno." \
    " Due progetti sono collegati se coprono lo stesso topic e condividono almeno N collaboratori." \
    " Puoi modificare N con lo slider qui sotto."

    return html.Div([
        html.Div([
            html.H3("PROJECT GRAPH", style={'color': 'black', 'marginBottom': '5px'}),
            html.P(status_text, style={'color': '#444', 'fontSize': '14px'}),
        ], style={'padding': '15px'}),
        html.Div([
            html.Label("Collaboratori condivisi minimi", style={'fontSize': '13px', 'color': '#444'}),
            dcc.Slider(
                id='project-graph-weight-slider',
                min=1, max=min(max_weight, 10), step=1, value=min_weight,
                marks={i: str(i) for i in range(1, min(max_weight, 10) + 1)},
            ),
        ], style={'padding': '0 25px 15px 25px'}),
        html.Div([
            html.Button('← Back', id='project-graph-back-btn', n_clicks=0,
                        style={'display': 'none', 'margin': '0 25px 10px 25px'}),
        ]),
        dcc.Store(id='project-graph-store', data={'nodes': nodes, 'edges': edges, 'user_input': bool(user_input)}),
        dcc.Store(id='project-graph-view-store', data={'view': 'overview', 'topic': None}),
        dcc.Graph(figure=overview_fig, id='project-graph'),
    ], style={
        'backgroundColor': 'white',
        'borderRadius': '15px',
        'boxShadow': '0px 4px 20px rgba(0,0,0,0.1)',
        'margin': '20px',
    })