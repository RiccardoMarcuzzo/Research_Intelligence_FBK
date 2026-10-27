# ------------------------------------------------------------------------------
# Revisione dei possibili topic nuovi trovati da extract_topic.assign_topics.
# Qui c'è la logica (gerarchia, modello, spostamento dei progetti già nel db);
# il foglio Excel che il revisore compila è in topic_review_sheet.py.
#
# update_db.py scrive subito i progetti nuovi con un topic provvisorio (il topic più vicino
# al cluster, Unlabelled per gli isolati) e un foglio con i candidati. Quando il revisore
# l'ha compilato, update_db.py --review lo applica ai progetti già nel db.
# Il revisore scrive un percorso (dalla macro-area alla foglia) per un cluster o per
# un progetto isolato. I progetti con lo stesso percorso formano un unico topic:
#   percorso vuoto        i progetti tengono il topic esistente più vicino
#   percorso già presente in topic2hier   i progetti vanno a quel topic
#   percorso nuovo        nasce un topic nuovo, in modello e gerarchia
#   "Unlabelled"          i progetti diventano Unlabelled; per un cluster il gruppo entra
#                         nel modello con percorso vuoto, così i progetti simili dei
#                         prossimi batch vengono scartati automaticamente (per i progetti
#                         isolati no: sono troppo diversi tra loro per un alias)
# I topic nuovi prendono sempre anche i progetti già nel db sotto soglia (vedi
# existing_moves), con una penalità fissa rispetto ai progetti nuovi.
# ------------------------------------------------------------------------------

import os
import json
import shutil
import difflib
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.sparse as sp

from specter_store import load_store
from create_projgraph import create_project_graph

UNLABELLED = "Unlabelled"
# chiave dei gruppi del foglio: progetti isolati marcati Unlabelled, che diventano Unlabelled
# uno per uno senza entrare nel modello. Per un cluster Unlabelled vale () (alias nel modello)
PLAIN_UNLABELLED = (UNLABELLED,)
# topic "non assegnato": i progetti che il foglio non tocca (non è un id di topic valido)
UNSET = -2
DEPTH = 4
# elenco dei topic creati dalla revisione, salvato nella cartella del modello
REVIEWED_FILE = "reviewed_topics.json"
TOPIC_TABLES = ("projects_uncase", "participants")


class HierarchyError(ValueError):
    pass


class ReviewAborted(Exception):
    pass


class SheetError(ReviewAborted):
    """Il foglio compilato contiene errori: il messaggio li elenca tutti."""


# ==============================================================================
# GERARCHIA
# ==============================================================================
class Hierarchy:
    """topic2hier.json contiene per ogni topic 4 nomi dalla foglia alla macro-area,
    allineati a destra con "Unlabelled". Qui ogni topic è un percorso dalla
    macro-area alla foglia, di 2-4 nodi (vuoto per i topic Unlabelled)."""

    def __init__(self, topic2hier):
        self.paths = {int(k): tuple(reversed([x for x in v if x != UNLABELLED]))
                      for k, v in topic2hier.items()}

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def copy(self):
        h = Hierarchy({})
        h.paths = dict(self.paths)
        return h

    @staticmethod
    def pad(path):
        return [UNLABELLED] * (DEPTH - len(path)) + list(reversed(path))

    def to_json(self):
        return {str(k): self.pad(p) for k, p in sorted(self.paths.items())}

    def save(self, path):
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False)
        os.replace(tmp, path)

    def path(self, topic_id):
        return self.paths.get(int(topic_id), ())

    def name(self, topic_id):
        p = self.path(topic_id)
        return p[-1] if p else UNLABELLED

    def leaves(self):
        return {p for p in self.paths.values() if p}

    def categories(self):
        return {p[:i] for p in self.leaves() for i in range(1, len(p))}

    def children(self, prefix=()):
        """Categorie figlie di prefix (i topic foglia sono esclusi)."""
        prefix = tuple(prefix)
        cats = self.categories()
        return sorted({p[len(prefix)] for p in cats
                       if len(p) == len(prefix) + 1 and p[:len(prefix)] == prefix})

    def node_names(self):
        return {x for p in self.paths.values() for x in p}

    def topic_for_path(self, path):
        ids = sorted(k for k, p in self.paths.items() if p == tuple(path))
        return ids[0] if ids else None

    def _ancestors(self):
        known = {}
        for p in self.leaves():
            for i, n in enumerate(p):
                known.setdefault(n, set()).add(p[:i])
        return known

    def validate_new_path(self, path):
        path = tuple(path)
        if not 2 <= len(path) <= DEPTH:
            raise HierarchyError(f"un topic deve avere da 2 a {DEPTH} livelli, non {len(path)}")
        for n in path:
            if not isinstance(n, str) or not n.strip() or n != n.strip() or n == UNLABELLED:
                raise HierarchyError(f'nome di nodo non valido: "{n}"')
        if len(set(path)) != len(path):
            raise HierarchyError("lo stesso nome compare due volte nel percorso")
        if path in self.leaves():
            raise HierarchyError("esiste già un topic con questo percorso")
        if path in self.categories():
            raise HierarchyError(f'"{path[-1]}" è già una categoria, non può essere un topic')
        for i in range(1, len(path)):
            if path[:i] in self.leaves():
                raise HierarchyError(f'"{path[i - 1]}" è un topic e non può avere figli')
        known = self._ancestors()
        for i, n in enumerate(path):
            if n in known and path[:i] not in known[n]:
                where = " > ".join(next(iter(known[n]))) or "radice"
                raise HierarchyError(f'"{n}" esiste già sotto "{where}": ogni nodo ha un solo padre')

    def add(self, topic_id, path):
        topic_id = int(topic_id)
        if topic_id in self.paths:
            raise HierarchyError(f"il topic {topic_id} esiste già in topic2hier")
        path = tuple(path)
        if path:
            self.validate_new_path(path)
        self.paths[topic_id] = path


def check_name(name, hierarchy, cutoff=0.8):
    """Restituisce (nomi uguali, nomi simili) tra tutti i nodi della gerarchia."""
    low = name.strip().lower()
    exact, similar = [], []
    for n in sorted(hierarchy.node_names()):
        nl = n.lower()
        if nl == low:
            exact.append(n)
        elif (difflib.SequenceMatcher(None, low, nl).ratio() >= cutoff
              or (min(len(low), len(nl)) > 3 and (low in nl or nl in low))):
            similar.append(n)
    return exact, similar


# ==============================================================================
# MODELLO
# ==============================================================================
def next_topic_id(model):
    """Gli id dei topic sono le righe di topic_embeddings_ (la prima è l'outlier -1)."""
    return len(model.topic_embeddings_) - model._outliers


def add_topic_to_model(model, embeddings, documents, topic_id):
    """Aggiunge un topic a un BERTopic salvato senza HDBSCAN: transform assegna i
    documenti per similarità con topic_embeddings_, quindi basta il centroide."""
    if topic_id != next_topic_id(model):
        raise ValueError(f"il nuovo topic deve avere id {next_topic_id(model)}, non {topic_id}")
    centroid = np.asarray(embeddings, dtype=model.topic_embeddings_.dtype).mean(axis=0)
    model.topic_embeddings_ = np.vstack([model.topic_embeddings_, centroid])

    bow = model.vectorizer_model.transform([" ".join(documents)])
    row = sp.csr_matrix(model.ctfidf_model.transform(bow))
    model.c_tf_idf_ = sp.vstack([model.c_tf_idf_, row]).tocsr()

    words = model.vectorizer_model.get_feature_names_out()
    scores = row.toarray().ravel()
    top = [i for i in np.argsort(scores)[::-1][:model.top_n_words] if scores[i] > 0]
    model.topic_representations_[topic_id] = [(str(words[i]), float(scores[i])) for i in top]
    model.topic_sizes_[topic_id] = len(documents)
    model.topic_labels_[topic_id] = f"{topic_id}_" + "_".join(str(words[i]) for i in top[:4])
    if getattr(model, "custom_labels_", None) is not None:
        model.custom_labels_.append(model.topic_labels_[topic_id])
    return topic_id


def load_reviewed_topics(model_dir):
    """Topic aggiunti dalla revisione (accettati e alias Unlabelled): vuoto se non ce ne sono."""
    path = os.path.join(model_dir, REVIEWED_FILE)
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {int(t) for t in json.load(f)}


def save_with_backup(model, model_dir, hierarchy, hier_path, backup_dir, reviewed_topics=()):
    """Salva modello e gerarchia, dopo averne copiato la versione precedente in backup_dir."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(backup_dir, exist_ok=True)

    tmp_dir = f"{model_dir}.tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    model.save(tmp_dir, serialization="safetensors", save_ctfidf=True)
    with open(os.path.join(tmp_dir, REVIEWED_FILE), "w", encoding="utf-8") as f:
        json.dump(sorted(int(t) for t in reviewed_topics), f)
    shutil.move(model_dir, os.path.join(backup_dir, f"old_topic_model_{stamp}"))
    shutil.move(tmp_dir, model_dir)

    shutil.copy2(hier_path, os.path.join(backup_dir, f"topic2hier_{stamp}.json"))
    hierarchy.save(hier_path)
    return stamp


# ==============================================================================
# APPLICAZIONE DEL FOGLIO
# ==============================================================================
def apply_groups(groups, project_ids, topics, embeddings, documents, model, hierarchy,
                 reviewed_topics=None):
    """groups: {percorso: [projectID]} come lo restituisce il foglio (() = cluster
    Unlabelled, con alias nel modello; PLAIN_UNLABELLED = isolati Unlabelled, senza
    alias). Restituisce i topic aggiornati, i topic nuovi con un percorso
    [(topic_id, percorso)] e True se modello e gerarchia sono stati modificati (e vanno
    salvati). I topic creati vengono aggiunti a reviewed_topics."""
    if reviewed_topics is None:
        reviewed_topics = set()
    topics = np.array(topics, copy=True)
    pos = {int(p): i for i, p in enumerate(project_ids)}
    created, changed = [], False
    for path, ids in groups.items():
        idx = [pos[int(p)] for p in ids]
        if path == PLAIN_UNLABELLED:
            topics[idx] = -1
            continue
        target = hierarchy.topic_for_path(path) if path else None
        if target is not None:
            topics[idx] = target
            continue
        new_id = next_topic_id(model)
        hierarchy.add(new_id, path)
        add_topic_to_model(model, embeddings[idx], [documents[i] for i in idx], new_id)
        reviewed_topics.add(new_id)
        topics[idx] = new_id
        changed = True
        if path:
            created.append((new_id, path))
    return topics, created, changed


# ==============================================================================
# PROGETTI GIÀ NEL DB
# ==============================================================================
@dataclass
class ExistingProjects:
    """Progetti già nel db di cui c'è l'embedding Specter2: possono passare a un topic nuovo."""
    project_ids: np.ndarray
    embeddings: np.ndarray
    titles: list
    hierarchies: list         # topic_name_hierarchy attuale (4 nomi allineati a destra)


@dataclass
class Target:
    """Topic nuovo che può prendere progetti già nel db, con il suo bonus."""
    key: object               # identifica il topic per chi chiama (di solito l'id)
    centroid: np.ndarray
    path: tuple
    bonus: float
    topic_id: int = None      # id nel modello


MOVE_COLUMNS = ["projectID", "title", "from_topic", "from_hierarchy", "key", "topic_id",
                "topic_name", "topic_name_hierarchy", "similarity", "best_original"]


def _unit_rows(x):
    x = np.asarray(x, dtype=float)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def existing_moves(model, reviewed_topics, existing, targets, similarity_threshold,
                   competitor_bonus, competitors=None, chunk=8192):
    """Progetti già nel db che passano a uno dei targets. È la regola dei progetti nuovi
    (extract_topic.assign_existing_topics) con il bonus di ciascun target: concorrono
    solo i progetti con similarità sotto soglia rispetto ai topic originali, e un
    target vince se sim + bonus >= miglior similarità con un topic originale.
    Concorrono anche i topic in competitors (di default i reviewed_topics che non sono
    target) con competitor_bonus: se vince uno di loro il progetto resta dov'è.
    I progetti che hanno già il percorso del target sono esclusi. Ordinati per target,
    dal più sicuro al più incerto."""
    if existing is None or not len(existing.project_ids) or not targets:
        return pd.DataFrame(columns=MOVE_COLUMNS)
    topic_embs = np.asarray(model.topic_embeddings_, dtype=float)
    ids = np.arange(len(topic_embs)) - model._outliers
    is_reviewed = np.isin(ids, list(reviewed_topics))
    if competitors is None:
        competitors = set(reviewed_topics) - {t.topic_id for t in targets}
    original = _unit_rows(topic_embs[~is_reviewed])
    rivals = _unit_rows(topic_embs[np.isin(ids, list(competitors))]) if competitors else np.empty((0, original.shape[1]))
    centroids = _unit_rows(np.vstack([t.centroid for t in targets]))
    bonuses = np.array([t.bonus for t in targets], dtype=float)

    best_original, best_score, winner = [], [], []
    for start in range(0, len(existing.embeddings), chunk):
        e = _unit_rows(existing.embeddings[start:start + chunk])
        best_original.append((e @ original.T).max(axis=1))
        scores = np.hstack([e @ rivals.T + competitor_bonus, e @ centroids.T + bonuses])
        best_score.append(scores.max(axis=1))
        winner.append(scores.argmax(axis=1) - len(rivals))   # < 0: vince un concorrente
    best_original, best_score, winner = map(np.concatenate, (best_original, best_score, winner))

    moved = (best_original < similarity_threshold) & (best_score >= best_original) & (winner >= 0)
    rows = []
    for i in np.flatnonzero(moved):
        t = targets[winner[i]]
        to_hier = Hierarchy.pad(t.path)
        from_hier = [str(x) for x in existing.hierarchies[i]]
        if from_hier == to_hier:
            continue
        rows.append({
            "projectID": int(existing.project_ids[i]),
            "title": existing.titles[i],
            "from_topic": next((x for x in from_hier if x != UNLABELLED), UNLABELLED),
            "from_hierarchy": from_hier,
            "key": t.key,
            "topic_id": t.topic_id,
            "topic_name": t.path[-1] if t.path else UNLABELLED,
            "topic_name_hierarchy": to_hier,
            "similarity": float(best_score[i] - t.bonus),
            "best_original": float(best_original[i]),
        })
    moves = pd.DataFrame(rows, columns=MOVE_COLUMNS)
    order = {t.key: n for n, t in enumerate(targets)}
    margin = moves["similarity"] - moves["best_original"]
    return (moves.assign(_t=moves["key"].map(order), _m=margin)
            .sort_values(["_t", "_m"], ascending=[True, False])
            .drop(columns=["_t", "_m"]).reset_index(drop=True))


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


def write_moves(db, moves, log_dir, note=None):
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


def rebuild_project_graphs(projects_tbl, out_dir):
    projects = (projects_tbl.search()
                .select(["projectID", "title", "topic_name", "participants"])
                .limit(None)
                .to_pandas())
    create_project_graph(projects, out_dir)


# ==============================================================================
# PUNTO DI INGRESSO
# ==============================================================================
@dataclass
class ReviewContext:
    project_ids: list
    titles: list
    objectives: list
    documents: list
    embeddings: np.ndarray
    topics: np.ndarray        # topic esistente più vicino
    similarity: np.ndarray
    report: pd.DataFrame      # candidati: cluster, cluster_keywords, projectID, similarity, nearest_topic, ...
    model: object
    hierarchy: Hierarchy
    reviewed_topics: set = field(default_factory=set)   # topic creati da revisioni precedenti
    existing: ExistingProjects = None   # progetti già nel db (None: non vengono toccati)
    similarity_threshold: float = 0.92
    existing_bonus: float = -0.005      # bonus dei topic nuovi per i progetti già nel db
    current_names: dict = None          # projectID -> topic_name nel db (None: nessun controllo)


def _cos(a, b):
    a = np.atleast_2d(a)
    return (a @ b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b))


def similar_topics(model, hierarchy, centroid, n=5):
    sims = _cos(model.topic_embeddings_, centroid)
    out, seen = [], set()
    for row in np.argsort(sims)[::-1]:
        topic_id = int(row) - model._outliers
        path = hierarchy.path(topic_id)
        if topic_id < 0 or not path or path in seen:
            continue
        seen.add(path)
        out.append((topic_id, path, float(sims[row])))
        if len(out) == n:
            break
    return out


def review_and_apply(ctx, mode, sheet_path, model_dir, hier_path, backup_dir):
    """mode: "none" (ogni progetto tiene ctx.topics), "provisional" (scrive in sheet_path il
    foglio da compilare; ctx.topics sono già i topic provvisori) o "sheet" (applica il
    foglio compilato: i progetti che non tocca restano a UNSET se ctx.topics lo è).
    Restituisce i topic finali e i progetti già nel db da spostare sui topic nuovi
    (vedi existing_moves); se servono, salva modello e gerarchia con backup."""
    no_moves = pd.DataFrame(columns=MOVE_COLUMNS)
    if mode == "none":
        return ctx.topics, no_moves
    if mode not in ("provisional", "sheet"):
        raise ValueError(f"modalità di revisione non valida: {mode}")

    from topic_review_sheet import write_review_sheet, read_review_sheet
    if mode == "provisional":
        if ctx.report.empty:
            print("No candidate new topics to review.")
        else:
            write_review_sheet(ctx, sheet_path)
        return ctx.topics, no_moves

    groups, warnings = read_review_sheet(sheet_path, ctx)
    for w in warnings:
        print(f"WARNING: {w}")

    previous_reviewed = set(ctx.reviewed_topics)
    topics, created, changed = apply_groups(groups, ctx.project_ids, ctx.topics, ctx.embeddings,
                                            ctx.documents, ctx.model, ctx.hierarchy, ctx.reviewed_topics)

    # progetti già nel db: ogni topic nuovo con un percorso concorre con il suo centroide;
    # gli alias Unlabelled e i topic delle revisioni precedenti sono solo concorrenti
    targets = [Target(key=topic_id, centroid=ctx.model.topic_embeddings_[topic_id + ctx.model._outliers],
                      path=path, bonus=ctx.existing_bonus, topic_id=topic_id)
               for topic_id, path in created]
    if targets and ctx.existing is None:
        print("WARNING: no Specter2 embeddings for the projects already in the db: "
              "they are not reassigned to the new topics.")
    moves = existing_moves(ctx.model, ctx.reviewed_topics, ctx.existing, targets,
                           ctx.similarity_threshold, ctx.existing_bonus, competitors=previous_reviewed)

    if changed:
        stamp = save_with_backup(ctx.model, model_dir, ctx.hierarchy, hier_path, backup_dir,
                                 ctx.reviewed_topics)
        print(f"Topic model and hierarchy updated (backup {stamp} in {backup_dir}).")
    return topics, moves
