"""Genera assets/treemap.json (pagina Concept) a partire da data/topic2hier.json.

La struttura dell'albero viene da topic2hier.json; il valore di ogni nodo è il numero
di progetti in projects_uncase il cui topic_name_hierarchy passa per quel nodo.

update_db.py la rigenera alla fine dello step dei progetti (write_treemap). Si può
anche lanciare da sola:

    python generate_treemap.py [--data ../data] [--out ../assets/treemap.json]
"""
import argparse
import json
import os
from collections import Counter

import lancedb
import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
TREEMAP_PATH = os.path.join(HERE, '..', 'assets', 'treemap.json')
UNLABELLED = "Unlabelled"

ROOT_COLORS = {
    'Social Sciences & Humanities': '#FF8C42',
    'Earth & Life Science': '#2D6A4F',
    'Engineering & Technology': '#6C757D',
    'Health & Medicine': '#1E88E5',
    'Physical & Mathematical Sciences': '#D32F2F',
}
DEFAULT_COLOR = '#95A5A6'


def root_first(path):
    """["Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"]
    -> ("Earth & Life Science", "Climatology", "Climate Modelling")"""
    return tuple(name for name in reversed(path) if name != UNLABELLED)


def generate_treemap(topic2hier, project_paths):
    """topic2hier: {topic_id: [4 nomi, foglia prima]}; project_paths: liste come topic_name_hierarchy."""
    counts = Counter(root_first(p) for p in project_paths)
    counts.pop((), None)  # progetti Unlabelled

    paths = {root_first(p) for p in topic2hier.values()} - {()}
    unknown = set(counts) - paths
    if unknown:
        print(f"ATTENZIONE: {sum(counts[p] for p in unknown)} progetti con percorso assente "
              f"da topic2hier.json, esclusi: {sorted(unknown)}")

    # valore di un nodo = progetti dei topic sotto di lui (branchvalues='total')
    node_values = Counter()
    for path in paths:
        for depth in range(1, len(path) + 1):
            node_values[path[:depth]] += counts.get(path, 0)

    # radici prima, poi i livelli successivi (come la versione precedente)
    nodes = sorted(node_values, key=lambda n: (len(n), -node_values[n]))
    nodes = [n for n in nodes if node_values[n] > 0]

    node_id = lambda n: "/".join(n)
    fig = go.Figure(go.Treemap(
        ids=[node_id(n) for n in nodes],
        labels=[n[-1] for n in nodes],
        parents=[node_id(n[:-1]) for n in nodes],
        values=[node_values[n] for n in nodes],
        branchvalues='total',
        marker=dict(colors=[ROOT_COLORS.get(n[0], DEFAULT_COLOR) for n in nodes],
                    line=dict(width=2, color='white')),
        texttemplate='<b>%{label}</b><br>%{percentEntry:.2%}',
        hovertemplate='<b>%{label}</b><br>Projects: %{value:,}<extra></extra>'
    ))
    fig.update_layout(
        margin=dict(t=25, l=10, r=10, b=10),
        paper_bgcolor='white',
        plot_bgcolor='white'
    )
    return fig


def load_topic2hier(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_treemap(projects_tbl, topic2hier, out_path=TREEMAP_PATH):
    """Rigenera la treemap da topic2hier (dict come topic2hier.json) e dai progetti di projects_uncase."""
    project_paths = (
        projects_tbl.search()
        .select(["topic_name_hierarchy"])
        .limit(max(projects_tbl.count_rows(), 1))
        .to_pandas()["topic_name_hierarchy"]
    )
    fig = generate_treemap(topic2hier, project_paths)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(fig.to_json())
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(HERE, "..", "data"))
    parser.add_argument("--out", default=TREEMAP_PATH)
    args = parser.parse_args()

    projects_tbl = lancedb.connect(args.data).open_table("projects_uncase")
    out = write_treemap(projects_tbl, load_topic2hier(os.path.join(args.data, "topic2hier.json")), args.out)
    print(f"Treemap scritta in {out}")
