import os
import re
import json
import itertools
from collections import defaultdict

MIN_SHARED_COLLABORATORS = 1
TOP_K_NEIGHBORS = None  # es. 20, oppure None per nessun upperbound

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name):
    return _SLUG_RE.sub("_", str(name).strip()).strip("_") or "unnamed_topic"


def create_project_graph(projects_df, OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    participants_sets = projects_df["participants"].map(set)
    index = {}

    for topic_name, group in projects_df.groupby("topic_name", observed=True):
        idx = group.index
        ids = group["projectID"].tolist()
        titles = group["title"].tolist()
        sets = [participants_sets.loc[i] for i in idx]

        nodes = {str(pid): {"title": t} for pid, t in zip(ids, titles)}

        edges = []
        for i, j in itertools.combinations(range(len(ids)), 2):
            shared = sets[i] & sets[j]
            w = len(shared)
            if w >= MIN_SHARED_COLLABORATORS:
                edges.append((ids[i], ids[j], w, sorted(shared)))

        if TOP_K_NEIGHBORS is not None and edges:
            by_node = defaultdict(list)
            for e in edges:
                by_node[e[0]].append(e)
                by_node[e[1]].append(e)
            keep = set()
            for pid, es in by_node.items():
                es.sort(key=lambda e: e[2], reverse=True)
                keep.update(id(e) for e in es[:TOP_K_NEIGHBORS])
            edges = [e for e in edges if id(e) in keep]

        payload = {
            "topic_name": str(topic_name),
            "nodes": nodes,
            "edges": [
                {"source": s, "target": t, "weight": w, "collaborators": c}
                for s, t, w, c in edges
            ],
        }

        filename = slugify(topic_name) + ".json"
        while filename in index.values():
            filename = filename.replace(".json", "_.json")
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        index[str(topic_name)] = filename

    with open(os.path.join(OUTPUT_DIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


