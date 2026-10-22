# ------------------------------------------------------------------------------
# Revisione dei possibili topic nuovi trovati da extract_topic.assign_topics.
# Qui c'è solo la logica (gerarchia, controllo dei nomi, decisioni, aggiornamento
# del modello); l'interfaccia a terminale è in topic_review_cli.py.
#
# Una decisione riguarda un insieme di progetti (project_ids) e può essere:
#   accept      nuovo topic: entra in old_topic_model e in topic2hier con "path"
#   remap       i progetti vanno al topic esistente con percorso "path"
#   unlabelled  i progetti diventano Unlabelled; con alias=True il gruppo entra nel
#               modello con percorso vuoto, così i progetti simili dei prossimi batch
#               vengono scartati automaticamente
#   nearest     i progetti tengono il topic esistente più vicino
# I percorsi vanno dalla macro-area alla foglia (es. ["Engineering & Technology", ...]).
# Una decisione accept può avere "existing_bonus": il topic nuovo prende anche i
# progetti già nel db sotto soglia, con quel bonus (di solito negativo, cioè una
# penalità); None o assente = i progetti già nel db non vengono toccati.
# ------------------------------------------------------------------------------

import os
import json
import shutil
import difflib
import hashlib
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import CountVectorizer

UNLABELLED = "Unlabelled"
DEPTH = 4
ACTIONS = ("accept", "remap", "unlabelled", "nearest")
# elenco dei topic creati dalla revisione, salvato nella cartella del modello
REVIEWED_FILE = "reviewed_topics.json"


class HierarchyError(ValueError):
    pass


class ReviewAborted(Exception):
    pass


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
            raise HierarchyError("esiste già un topic con questo percorso: usa la rimappatura")
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
# DECISIONI
# ==============================================================================
def batch_key(project_ids):
    ids = ",".join(str(int(p)) for p in sorted(int(p) for p in project_ids))
    return hashlib.sha1(ids.encode()).hexdigest()[:16]


def validate_decision(d):
    if d.get("action") not in ACTIONS:
        raise ValueError(f"azione non valida: {d.get('action')}")
    if not d.get("project_ids"):
        raise ValueError("decisione senza progetti")
    if d["action"] in ("accept", "remap") and not d.get("path"):
        raise ValueError(f"la decisione {d['action']} richiede un percorso")
    if d["action"] == "accept" and d.get("name") not in (None, d["path"][-1]):
        raise ValueError("il nome deve coincidere con l'ultimo nodo del percorso")
    if "existing_bonus" in d:
        if d["action"] != "accept":
            raise ValueError("existing_bonus vale solo per i topic accettati")
        bonus = d["existing_bonus"]
        if bonus is not None and (isinstance(bonus, bool) or not isinstance(bonus, (int, float))):
            raise ValueError(f"existing_bonus non valido: {bonus}")


class DecisionStore:
    """Decisioni salvate su file a ogni passo: la revisione si può interrompere e riprendere."""

    def __init__(self, path, batch, decisions=None):
        self.path = path
        self.batch = batch
        self.decisions = list(decisions or [])

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for d in data["decisions"]:
            validate_decision(d)
        return cls(path, data.get("batch"), data["decisions"])

    def add(self, decision):
        decision = dict(decision)
        decision["project_ids"] = [int(p) for p in decision["project_ids"]]
        if decision.get("path"):
            decision["path"] = list(decision["path"])
        validate_decision(decision)
        self.decisions.append(decision)
        self.save()

    def set_field(self, index, key, value):
        decision = {**self.decisions[index], key: value}
        validate_decision(decision)
        self.decisions[index] = decision
        self.save()

    def covered(self):
        return {p for d in self.decisions for p in d["project_ids"]}

    def save(self):
        if not self.path:
            return
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"batch": self.batch, "decisions": self.decisions}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def apply_decisions(decisions, project_ids, topics, embeddings, documents, model, hierarchy,
                    reviewed_topics=None):
    """Applica le decisioni in ordine. Restituisce i topic aggiornati e True se modello
    e gerarchia sono stati modificati (e vanno quindi salvati). I topic creati vengono
    aggiunti a reviewed_topics."""
    if reviewed_topics is None:
        reviewed_topics = set()
    topics = np.array(topics, copy=True)
    pos = {int(p): i for i, p in enumerate(project_ids)}
    changed = False
    for d in decisions:
        validate_decision(d)
        idx = [pos[int(p)] for p in d["project_ids"] if int(p) in pos]
        if not idx or d["action"] == "nearest":
            continue
        if d["action"] == "remap":
            target = hierarchy.topic_for_path(d["path"])
            if target is None:
                raise HierarchyError(f"nessun topic con percorso {' > '.join(d['path'])}")
            topics[idx] = target
        elif d["action"] == "unlabelled" and not d.get("alias", True):
            topics[idx] = -1
        else:
            new_id = next_topic_id(model)
            path = tuple(d["path"]) if d["action"] == "accept" else ()
            hierarchy.add(new_id, path)
            add_topic_to_model(model, embeddings[idx], [documents[i] for i in idx], new_id)
            reviewed_topics.add(new_id)
            topics[idx] = new_id
            changed = True
    return topics, changed


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
    key: object               # identifica il topic per chi chiama (indice della decisione, id...)
    centroid: np.ndarray
    path: tuple
    bonus: float
    topic_id: int = None      # id nel modello, se il topic è già stato aggiunto


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


def accept_targets(decisions, project_ids, embeddings, default_bonus=None, override=None):
    """Un Target per ogni decisione accept che può prendere progetti già nel db
    (key = indice della decisione). Il centroide è quello che add_topic_to_model
    mette nel modello. Bonus: override[i], altrimenti existing_bonus della
    decisione, altrimenti default_bonus; None esclude il topic."""
    override = override or {}
    pos = {int(p): i for i, p in enumerate(project_ids)}
    targets = []
    for i, d in enumerate(decisions):
        if d["action"] != "accept":
            continue
        bonus = override[i] if i in override else d.get("existing_bonus", default_bonus)
        idx = [pos[int(p)] for p in d["project_ids"] if int(p) in pos]
        if bonus is None or not idx:
            continue
        targets.append(Target(key=i, centroid=np.asarray(embeddings)[idx].mean(axis=0),
                              path=tuple(d["path"]), bonus=float(bonus)))
    return targets


# ==============================================================================
# SCHEDE DEI CLUSTER
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
    report: pd.DataFrame
    model: object
    hierarchy: Hierarchy
    reviewed_topics: set = field(default_factory=set)   # topic creati da revisioni precedenti
    existing: ExistingProjects = None   # progetti già nel db (None: non vengono toccati)
    similarity_threshold: float = 0.92
    existing_bonus: float = -0.005      # bonus proposto per i progetti già nel db


@dataclass
class ClusterSummary:
    cluster: int
    indices: list             # posizioni nel batch, dalle più vicine al centroide
    keywords: str
    mean_similarity: float
    similar_topics: list      # [(topic_id, percorso, similarità)]
    name_suggestions: list


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


def name_suggestions(titles, keywords, n=6):
    out = []
    try:
        vec = CountVectorizer(ngram_range=(2, 2), stop_words="english")
        counts = np.asarray(vec.fit_transform(titles).sum(axis=0)).ravel()
        words = vec.get_feature_names_out()
        out += [words[i].title() for i in np.argsort(counts)[::-1][:3] if counts[i] > 1]
    except ValueError:  # titoli senza bigrammi utili
        pass
    out += [k.strip().title() for k in keywords.split(",") if k.strip()][:3]
    return list(dict.fromkeys(out))[:n]


def summarize_clusters(ctx, n_similar=5):
    pos = {int(p): i for i, p in enumerate(ctx.project_ids)}
    out = []
    for cluster, group in ctx.report.groupby("cluster", sort=False):
        if cluster < 0:
            continue
        idx = [pos[int(p)] for p in group["projectID"]]
        centroid = ctx.embeddings[idx].mean(axis=0)
        order = np.argsort(_cos(ctx.embeddings[idx], centroid))[::-1]
        idx = [idx[i] for i in order]
        keywords = str(group["cluster_keywords"].iloc[0]) if group["cluster_keywords"].notna().any() else ""
        out.append(ClusterSummary(
            cluster=int(cluster),
            indices=idx,
            keywords=keywords,
            mean_similarity=float(ctx.similarity[idx].mean()),
            similar_topics=similar_topics(ctx.model, ctx.hierarchy, centroid, n_similar),
            name_suggestions=name_suggestions([ctx.titles[i] for i in idx], keywords),
        ))
    return out


def isolated_indices(ctx):
    pos = {int(p): i for i, p in enumerate(ctx.project_ids)}
    return [pos[int(p)] for p in ctx.report.loc[ctx.report["cluster"] < 0, "projectID"]]


# ==============================================================================
# PUNTO DI INGRESSO
# ==============================================================================
def review_and_apply(ctx, mode, decisions_path, model_dir, hier_path, backup_dir,
                     prompter=None, console=None):
    """mode: "none" (topic più vicino), "file" (riapplica decisions_path) o "interactive".
    Restituisce i topic finali e i progetti già nel db da spostare sui topic nuovi
    (vedi existing_moves); se servono, salva modello e gerarchia con backup."""
    no_moves = pd.DataFrame(columns=MOVE_COLUMNS)
    if mode == "none":
        return ctx.topics, no_moves
    if mode == "file":
        store = DecisionStore.load(decisions_path)
        if store.batch != batch_key(ctx.project_ids):
            print(f"WARNING: {decisions_path} was written for a different batch; "
                  "decisions are applied to the matching projects only.")
    elif mode == "interactive":
        if ctx.report.empty:
            print("No candidate new topics to review.")
            return ctx.topics, no_moves
        from topic_review_cli import run_review
        store = run_review(ctx, decisions_path, prompter=prompter, console=console)
    else:
        raise ValueError(f"modalità di revisione non valida: {mode}")

    previous_reviewed = set(ctx.reviewed_topics)
    topics, changed = apply_decisions(store.decisions, ctx.project_ids, ctx.topics, ctx.embeddings,
                                      ctx.documents, ctx.model, ctx.hierarchy, ctx.reviewed_topics)

    # progetti già nel db: stessi centroidi messi nel modello; i topic accettati senza
    # existing_bonus non concorrono, quelli delle revisioni precedenti sì
    targets = accept_targets(store.decisions, ctx.project_ids, ctx.embeddings)
    if targets and ctx.existing is None:
        print("WARNING: no Specter2 embeddings for the projects already in the db: "
              "they are not reassigned to the new topics.")
    for t in targets:
        t.topic_id = ctx.hierarchy.topic_for_path(t.path)
    moves = existing_moves(ctx.model, ctx.reviewed_topics, ctx.existing, targets,
                           ctx.similarity_threshold, ctx.existing_bonus, competitors=previous_reviewed)

    if changed:
        stamp = save_with_backup(ctx.model, model_dir, ctx.hierarchy, hier_path, backup_dir,
                                 ctx.reviewed_topics)
        print(f"Topic model and hierarchy updated (backup {stamp} in {backup_dir}).")
    return topics, moves
