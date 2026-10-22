# ------------------------------------------------------------------------------
# Riassegnazione dei progetti già nel db a topic creati dalla revisione.
#
# update_db.py lo fa da solo quando la revisione accetta un topic nuovo; questo
# script serve per i topic accettati in passato (ad esempio prima che esistesse
# l'archivio degli embedding Specter2, data/specter2.parquet):
#
#     python reassign_existing.py --topics 203 [--bonus -0.005] [--yes | --dry-run]
#
# Per ogni topic mostra quanti progetti già nel db passerebbero lì, da quali topic
# e con quali titoli, e chiede se applicare, cambiare il bonus o lasciar perdere.
# La regola è quella di topic_review.existing_moves: solo i progetti sotto soglia,
# con un bonus negativo (una penalità) rispetto ai progetti nuovi.
# Ogni scrittura salva in data/backups/reassign_<data>.json i progetti spostati,
# con il topic di prima e le versioni delle tabelle per tornare indietro.
# ------------------------------------------------------------------------------

import os
import sys
import json
import argparse
from configparser import ConfigParser
from datetime import datetime

import numpy as np
import pandas as pd

from specter_store import load_store
from topic_review import ExistingProjects, Target, existing_moves, Hierarchy, load_reviewed_topics
from create_projgraph import create_project_graph
from generate_treemap import write_treemap, TREEMAP_PATH

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, '../data')
SPECTER_STORE_PATH = os.path.join(DATA_DIR, 'specter2.parquet')
PROJECT_GRAPH_DIR = os.path.join(DATA_DIR, 'project_graphs')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
TOPIC_TABLES = ("projects_uncase", "participants")


def load_existing(projects_tbl, store_path, exclude_ids=()):
    """Progetti del db con il loro embedding Specter2, esclusi exclude_ids.
    None se l'archivio degli embedding non esiste."""
    store = load_store(store_path)
    if store is None:
        return None
    store_ids, store_embs = store
    df = (projects_tbl.search()
          .select(["projectID", "title", "topic_name_hierarchy"])
          .limit(None)
          .to_pandas())
    df = df[~df["projectID"].isin(set(int(p) for p in exclude_ids))]
    row = pd.Series(np.arange(len(store_ids)), index=store_ids)
    missing = ~df["projectID"].isin(row.index)
    if missing.any():
        print(f"WARNING: {missing.sum()} projects in the db have no Specter2 embedding in {store_path}: "
              "they cannot be reassigned to new topics.")
    df = df[~missing]
    return ExistingProjects(
        project_ids=df["projectID"].to_numpy(),
        embeddings=store_embs[row.loc[df["projectID"]].to_numpy()],
        titles=df["title"].fillna("").astype(str).tolist(),
        hierarchies=[[str(x) for x in h] if h is not None else [] for h in df["topic_name_hierarchy"]],
    )


def write_moves(db, moves, log_dir=BACKUP_DIR, note=None):
    """Scrive i nuovi topic in projects_uncase e participants. Restituisce il file di
    log (progetti spostati, topic di prima, versioni delle tabelle prima della modifica)."""
    if moves.empty:
        return None
    tables = {name: db.open_table(name) for name in TOPIC_TABLES}
    versions = {name: tbl.version for name, tbl in tables.items()}
    for hier, group in moves.groupby(moves["topic_name_hierarchy"].map(tuple), sort=False):
        ids = ", ".join(str(int(p)) for p in group["projectID"])
        values = {"topic_name": group["topic_name"].iloc[0], "topic_name_hierarchy": list(hier)}
        for tbl in tables.values():
            tbl.update(where=f"projectID IN ({ids})", values=values)

    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(log_dir, f"reassign_{stamp}.json")
    log = {
        "note": note,
        "versions_before": versions,
        "moves": [{
            "projectID": int(m.projectID),
            "topic_id": None if pd.isna(m.topic_id) else int(m.topic_id),
            "from": list(m.from_hierarchy),
            "to": list(m.topic_name_hierarchy),
        } for m in moves.itertuples()],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    return path


def rebuild_project_graphs(projects_tbl, out_dir=PROJECT_GRAPH_DIR):
    projects = (projects_tbl.search()
                .select(["projectID", "title", "topic_name", "participants"])
                .limit(None)
                .to_pandas())
    create_project_graph(projects, out_dir)


def print_moves_summary(moves, targets):
    for t in targets:
        m = moves[moves["key"] == t.key]
        sources = ", ".join(f"{name} {n}" for name, n in m["from_topic"].value_counts().head(5).items())
        print(f"Topic {t.topic_id} ({' > '.join(t.path)}), bonus {t.bonus:+.3f}: "
              f"{len(m)} projects already in the db move here" + (f" (from {sources}, ...)" if len(m) else ""))


def reassign(db, model, hierarchy, reviewed_topics, topic_ids, bonus, similarity_threshold,
             store_path=SPECTER_STORE_PATH, mode="interactive", prompter=None, console=None,
             graph_dir=PROJECT_GRAPH_DIR, log_dir=BACKUP_DIR, treemap_path=TREEMAP_PATH):
    """mode: "interactive" (chiede per ogni topic), "yes" (applica con bonus), "dry-run"
    (mostra soltanto). Restituisce gli spostamenti applicati (o previsti, in dry-run)."""
    targets = []
    for topic_id in topic_ids:
        if topic_id not in reviewed_topics:
            raise ValueError(f"il topic {topic_id} non è stato creato da una revisione "
                             "(reviewed_topics.json): i topic originali non si riassegnano")
        path = hierarchy.path(topic_id)
        if not path:
            raise ValueError(f"il topic {topic_id} è un alias Unlabelled: non prende progetti già nel db")
        targets.append(Target(key=topic_id, centroid=model.topic_embeddings_[topic_id + model._outliers],
                              path=path, bonus=bonus, topic_id=topic_id))

    existing = load_existing(db.open_table("projects_uncase"), store_path)
    if existing is None:
        raise FileNotFoundError(f"archivio degli embedding Specter2 non trovato: {store_path}")

    def compute(targets):
        return existing_moves(model, reviewed_topics, existing, targets, similarity_threshold, bonus)

    if mode == "interactive":
        from rich.console import Console
        from topic_review_cli import QuestionaryPrompter, ask_existing_bonus
        console = console or Console()
        prompter = prompter or QuestionaryPrompter()
        chosen = []
        for t in targets:
            def compute_one(b, t=t):
                t.bonus = b
                return compute([t])
            t.bonus = ask_existing_bonus(prompter, console, t.path, compute_one, bonus)
            if t.bonus is not None:
                chosen.append(t)
        targets = chosen

    moves = compute(targets)
    print_moves_summary(moves, targets)
    if mode == "dry-run" or moves.empty:
        if moves.empty:
            print("Nothing to do.")
        return moves
    if mode == "interactive" and not prompter.confirm(
            f"Spostare {len(moves)} progetti già nel db? (projects_uncase, participants, grafi e treemap)", default=True):
        print("Nothing was written.")
        return moves.iloc[:0]

    log = write_moves(db, moves, log_dir,
                      note={"topics": {int(t.topic_id): t.bonus for t in targets},
                            "similarity_threshold": similarity_threshold})
    projects_tbl = db.open_table("projects_uncase")
    rebuild_project_graphs(projects_tbl, graph_dir)
    # i conteggi della treemap (pagina Concept) cambiano con gli spostamenti
    write_treemap(projects_tbl, hierarchy.to_json(), treemap_path)
    print(f"{len(moves)} projects reassigned; project graphs and treemap rebuilt. Log (with previous topics and "
          f"table versions, to roll back): {log}")
    return moves


def main(argv=None):
    parser = argparse.ArgumentParser(description="Riassegna i progetti già nel db a topic creati dalla revisione.")
    parser.add_argument("--topics", type=int, nargs="+", required=True, help="id dei topic (es. 203)")
    parser.add_argument("--bonus", type=float,
                        help="bonus per i progetti già nel db (default: reviewed_topic_bonus_existing del config)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--yes", action="store_true", help="applica senza chiedere, con --bonus")
    group.add_argument("--dry-run", action="store_true", help="mostra soltanto cosa cambierebbe")
    parser.add_argument("--config", default=os.path.join(HERE, "settings.config"))
    args = parser.parse_args(argv)

    config = ConfigParser()
    config.read(args.config)
    bonus = args.bonus if args.bonus is not None else config.getfloat(
        'topics', 'reviewed_topic_bonus_existing', fallback=-0.005)
    threshold = config.getfloat('topics', 'similarity_threshold', fallback=0.92)
    if args.dry_run:
        mode = "dry-run"
    elif args.yes:
        mode = "yes"
    elif sys.stdin.isatty():
        mode = "interactive"
    else:
        print("No terminal: use --yes to apply or --dry-run to preview.")
        return 1

    import lancedb
    from bertopic import BERTopic
    from extract_topic import OLD_TOPIC_MODEL_DIR, TOPIC_HIER_DICT_DIR

    db = lancedb.connect(DATA_DIR)
    model = BERTopic.load(OLD_TOPIC_MODEL_DIR)
    try:
        reassign(db, model, Hierarchy.load(TOPIC_HIER_DICT_DIR), load_reviewed_topics(OLD_TOPIC_MODEL_DIR),
                 args.topics, bonus, threshold, mode=mode)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted: nothing was written.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
