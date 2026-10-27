import os
from dataclasses import dataclass

import pandas as pd
import numpy as np
from bertopic import BERTopic
from umap import UMAP
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from nltk.corpus import stopwords

from extract_embedding import extract_specter2
from specter_store import embeddings_for
from topic_review import (Hierarchy, ReviewContext, ReviewAborted, review_and_apply, load_reviewed_topics,
                          load_existing, MOVE_COLUMNS, UNSET)
from topic_review_sheet import sheet_project_ids

OLD_TOPIC_MODEL_DIR = os.path.join(os.path.dirname(__file__), '../data/old_topic_model')
TOPIC_HIER_DICT_DIR = os.path.join(os.path.dirname(__file__), '../data/topic2hier.json')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), '../data/backups')

# UMAP sui soli candidati: sotto questo numero di vicini i cluster diventano rumore
N_NEIGHBORS = 10


def cluster_candidates(document_list, embeddings, min_cluster_size=5):
    """Raggruppa i progetti poco simili ai topic esistenti: ogni cluster è un possibile topic nuovo."""
    umap_model = UMAP(n_neighbors=N_NEIGHBORS,
                      min_dist=0.0,
                      n_components=5,
                      metric='cosine',
                      random_state=1)

    hdbscan_model = HDBSCAN(min_cluster_size=min_cluster_size,
                            metric='euclidean',
                            prediction_data=True)

    vectorizer_model = CountVectorizer(stop_words=stopwords.words('english'))

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        top_n_words=10,
        calculate_probabilities=False
        )

    topics, _ = topic_model.fit_transform(document_list, embeddings)

    return topic_model, topics


def assign_existing_topics(topic_model, embeddings, reviewed_topics=(), similarity_threshold=0.92,
                           reviewed_bonus=0.02):
    """Assegna ogni documento al topic più simile per coseno, come fa BERTopic.transform
    per un modello salvato senza HDBSCAN (la prima riga di topic_embeddings_ è l'outlier -1).

    I topic creati dalla revisione (reviewed_topics) sono centroidi di pochi documenti e
    perderebbero contro i topic originali, molto più "generici": per questo concorrono
    solo per i documenti sotto soglia, e vincono se la loro similarità è almeno quella del
    miglior topic originale meno reviewed_bonus. I documenti sopra soglia restano ai topic
    originali.

    Restituisce i topic, la similarità con il miglior topic originale (usata per la soglia)
    e la maschera dei documenti assegnati a un topic revisionato."""
    embs = np.asarray(embeddings, dtype=float)
    topic_embs = np.asarray(topic_model.topic_embeddings_, dtype=float)
    sims = ((embs / np.linalg.norm(embs, axis=1, keepdims=True))
            @ (topic_embs / np.linalg.norm(topic_embs, axis=1, keepdims=True)).T)
    ids = np.arange(len(topic_embs)) - topic_model._outliers
    is_reviewed = np.isin(ids, list(reviewed_topics))

    original = np.where(is_reviewed, -np.inf, sims)
    best_original = original.max(axis=1)
    topics = ids[original.argmax(axis=1)]
    auto = np.zeros(len(embs), dtype=bool)
    if is_reviewed.any():
        reviewed = np.where(is_reviewed, sims, -np.inf)
        auto = ((best_original < similarity_threshold)
                & (reviewed.max(axis=1) >= best_original - reviewed_bonus))
        topics = np.where(auto, ids[reviewed.argmax(axis=1)], topics)
    return topics, best_original, auto


def first_labelled(h):
    for name in h:
        if name != "Unlabelled":
            return name
    return "Unlabelled"


def report_new_topic_candidates(new_df, document_list, embeddings, nearest_names, similarity,
                                similarity_threshold, min_cluster_size, auto_assigned=None):
    """Raccoglie i progetti sotto soglia e li clusterizza: è il report da revisionare.
    Ci sono anche quelli già assegnati a un topic revisionato (auto_assigned), così
    un'assegnazione automatica sbagliata si vede e si corregge."""
    mask = similarity < similarity_threshold
    idx = np.flatnonzero(mask)
    if auto_assigned is None:
        auto_assigned = np.zeros(len(similarity), dtype=bool)

    report = pd.DataFrame({
        'cluster': -1,
        'cluster_keywords': '',
        'projectID': new_df['projectID'].values[idx],
        'title': new_df['title'].values[idx],
        'similarity': similarity[idx].round(4),
        'nearest_topic': np.asarray(nearest_names, dtype=object)[idx],
        'auto_assigned': np.asarray(auto_assigned, dtype=bool)[idx],
    })

    # UMAP e HDBSCAN hanno bisogno di un minimo di documenti per dare cluster sensati
    if len(idx) >= max(2 * min_cluster_size, N_NEIGHBORS + 2):
        cand_model, labels = cluster_candidates([document_list[i] for i in idx],
                                                embeddings[idx], min_cluster_size)
        info = cand_model.get_topic_info()
        keywords = {row.Topic: ', '.join(row.Representation)
                    for row in info.itertuples() if row.Topic >= 0}
        report['cluster'] = labels
        report['cluster_keywords'] = report['cluster'].map(keywords).fillna('')

    report.insert(1, 'cluster_size',
                  report.groupby('cluster')['projectID'].transform('size').where(report['cluster'] >= 0, 0))
    # prima i cluster più grandi, in fondo i progetti isolati
    report = report.sort_values(['cluster_size', 'cluster', 'similarity'],
                                ascending=[False, True, True]).reset_index(drop=True)

    n_clusters = report.loc[report['cluster'] >= 0, 'cluster'].nunique()
    print(f'{len(new_df)} new projects assigned to existing topics.\n'
          f'{len(report)} have similarity < {similarity_threshold}: '
          f'{n_clusters} candidate new topics, {(report["cluster"] == -1).sum()} isolated projects.')
    if report['auto_assigned'].any():
        print(f'{report["auto_assigned"].sum()} of them were assigned to topics created in previous reviews.')

    return report


def topics_to_frame(project_ids, topics, hierarchy):
    """topic_name e topic_name_hierarchy (allineata a destra) per ogni progetto.
    Un topic assente da topic2hier resta senza nome."""
    known = [int(t) in hierarchy.paths for t in topics]
    return pd.DataFrame({
        'projectID': project_ids,
        'topic_name': [hierarchy.name(t) if k else None for t, k in zip(topics, known)],
        'topic_name_hierarchy': [np.array(hierarchy.pad(hierarchy.path(t))) if k else None
                                 for t, k in zip(topics, known)],
    })


def provisional_topics(topics, report, project_ids, embeddings, model, reviewed_topics,
                       similarity_threshold, reviewed_bonus, auto_assigned):
    """Topic provvisori in attesa della revisione: i candidati di un cluster vanno tutti al
    topic più simile al centroide del cluster (stessa regola dei progetti singoli, vedi
    assign_existing_topics), gli isolati a Unlabelled (-1). I candidati già assegnati
    in automatico a un topic di una revisione precedente restano dove sono."""
    topics = np.array(topics, copy=True)
    pos = {int(p): i for i, p in enumerate(project_ids)}
    for cluster, group in report.groupby('cluster'):
        idx = [pos[int(p)] for p in group['projectID']]
        free = [i for i in idx if not auto_assigned[i]]
        if not free:
            continue
        if cluster < 0:
            topics[free] = -1
        else:
            centroid = np.asarray(embeddings, dtype=float)[idx].mean(axis=0, keepdims=True)
            nearest, _, _ = assign_existing_topics(model, centroid, reviewed_topics,
                                                   similarity_threshold, reviewed_bonus)
            topics[free] = nearest[0]
    return topics


@dataclass
class TopicAssignment:
    topics: pd.DataFrame      # projectID, topic_name, topic_name_hierarchy dei progetti nuovi
    embeddings: np.ndarray    # embedding Specter2 dei progetti nuovi, nell'ordine di new_df


def assign_topics(new_df, specter_embs=None, similarity_threshold=0.92, min_cluster_size=5,
                  review='none', sheet_path=None, reviewed_bonus=0.02):
    """specter_embs: embedding Specter2 dei progetti di new_df, nello stesso ordine
    (None = calcolati qui).
    review: 'none' (ogni progetto al topic più vicino) o 'provisional' (i candidati a un
    topic nuovo hanno un topic provvisorio, vedi provisional_topics, e il foglio Excel da
    compilare viene scritto in sheet_path; il modello e la gerarchia non cambiano: li
    modifica apply_review_sheet).
    reviewed_bonus: vedi assign_existing_topics."""
    if review not in ('none', 'provisional'):
        raise ValueError(f"modalità di revisione non valida: {review}")
    if specter_embs is not None:
        new_embs = np.asarray(specter_embs, dtype=np.float32)
        if new_embs.shape[0] != len(new_df):
            raise ValueError(f"{new_embs.shape[0]} Specter2 embeddings for {len(new_df)} projects")
    else:
        new_embs = extract_specter2(new_df)

    new_document_list = (
        new_df['title'].fillna('').astype(str) + ' ' +
        new_df['objective'].fillna('').astype(str)
    ).to_list()

    # ogni progetto nuovo va al topic esistente più simile; i topic creati dalle revisioni
    # precedenti concorrono solo per i progetti sotto soglia (vedi assign_existing_topics)
    old_topic_model = BERTopic.load(OLD_TOPIC_MODEL_DIR)
    reviewed_topics = load_reviewed_topics(OLD_TOPIC_MODEL_DIR)
    topics, similarity, auto_assigned = assign_existing_topics(
        old_topic_model, new_embs, reviewed_topics, similarity_threshold, reviewed_bonus)

    hierarchy = Hierarchy.load(TOPIC_HIER_DICT_DIR)
    nearest = topics_to_frame(new_df['projectID'].values, topics, hierarchy)

    # i progetti poco simili ai topic esistenti finiscono nel report dei possibili topic nuovi
    report = report_new_topic_candidates(new_df, new_document_list, new_embs, nearest['topic_name'],
                                         similarity, similarity_threshold, min_cluster_size,
                                         auto_assigned)

    if review == 'provisional' and not report.empty:
        topics = provisional_topics(topics, report, new_df['projectID'].values, new_embs, old_topic_model,
                                    reviewed_topics, similarity_threshold, reviewed_bonus, auto_assigned)
        names = topics_to_frame(new_df['projectID'].values, topics, hierarchy).set_index('projectID')['topic_name']
        report['nearest_topic'] = report['projectID'].map(names)

    ctx = ReviewContext(
        project_ids=[int(p) for p in new_df['projectID']],
        titles=new_df['title'].fillna('').astype(str).tolist(),
        objectives=new_df['objective'].fillna('').astype(str).tolist(),
        documents=new_document_list,
        embeddings=new_embs,
        topics=topics,
        similarity=similarity,
        report=report,
        model=old_topic_model,
        hierarchy=hierarchy,
        reviewed_topics=reviewed_topics,
        similarity_threshold=similarity_threshold,
    )
    topics, _ = review_and_apply(ctx, review, sheet_path, OLD_TOPIC_MODEL_DIR,
                                 TOPIC_HIER_DICT_DIR, BACKUP_DIR)

    return TopicAssignment(topics=topics_to_frame(new_df['projectID'].values, topics, hierarchy),
                           embeddings=np.asarray(new_embs))


def apply_review_sheet(db, sheet_path, store_path, similarity_threshold=0.92, existing_bonus=-0.005):
    """Applica il foglio compilato ai progetti già nel db (quelli che elenca): aggiunge i
    topic nuovi a modello e gerarchia (con backup) e restituisce i cambi di topic da
    scrivere, nel formato di topic_review.MOVE_COLUMNS: i progetti del foglio che cambiano
    rispetto al topic provvisorio e i progetti già nel db che passano ai topic nuovi.
    Se il foglio ha errori solleva SheetError e non cambia nulla."""
    ids = sheet_project_ids(sheet_path)
    projects_tbl = db.open_table("projects_uncase")
    rows = (projects_tbl.search()
            .where(f"projectID IN ({', '.join(map(str, ids))})")
            .select(["projectID", "title", "objective", "topic_name", "topic_name_hierarchy"])
            .limit(max(len(ids), 1))
            .to_pandas()
            .sort_values("projectID").reset_index(drop=True)) if ids else pd.DataFrame()
    found = [int(p) for p in rows["projectID"]] if len(rows) else []
    # i progetti che non sono nel db li segnala il foglio (read_review_sheet); qui servono
    # solo quelli trovati
    try:
        embs = embeddings_for(store_path, found) if found else np.empty((0, 0))
    except ValueError as e:
        raise ReviewAborted(f"Specter2 embeddings: {e}")

    titles = rows["title"].fillna("").astype(str).tolist() if found else []
    objectives = rows["objective"].fillna("").astype(str).tolist() if found else []
    model = BERTopic.load(OLD_TOPIC_MODEL_DIR)
    hierarchy = Hierarchy.load(TOPIC_HIER_DICT_DIR)
    ctx = ReviewContext(
        project_ids=found,
        titles=titles,
        objectives=objectives,
        documents=[f"{t} {o}" for t, o in zip(titles, objectives)],
        embeddings=embs,
        topics=np.full(len(found), UNSET),
        similarity=np.zeros(len(found)),
        report=pd.DataFrame(),
        model=model,
        hierarchy=hierarchy,
        reviewed_topics=load_reviewed_topics(OLD_TOPIC_MODEL_DIR),
        existing=load_existing(projects_tbl, store_path, exclude_ids=found),
        similarity_threshold=similarity_threshold,
        existing_bonus=existing_bonus,
        current_names=dict(zip(found, rows["topic_name"])) if found else {},
    )
    if ctx.existing is None:
        print(f"WARNING: {store_path} not found: projects already in the db will not be reassigned.")
    topics, old_moves = review_and_apply(ctx, 'sheet', sheet_path, OLD_TOPIC_MODEL_DIR,
                                         TOPIC_HIER_DICT_DIR, BACKUP_DIR)

    changes = []
    for i, topic_id in enumerate(topics):
        if topic_id == UNSET:
            continue
        to_hier = Hierarchy.pad(hierarchy.path(topic_id))
        from_hier = [str(x) for x in rows["topic_name_hierarchy"].iloc[i]]
        if from_hier == to_hier:
            continue
        changes.append({
            "projectID": found[i], "title": titles[i],
            "from_topic": first_labelled(from_hier), "from_hierarchy": from_hier,
            "key": int(topic_id), "topic_id": int(topic_id),
            "topic_name": hierarchy.name(topic_id), "topic_name_hierarchy": to_hier,
            "similarity": np.nan, "best_original": np.nan,
        })
    print(f"{len(changes)} projects of the sheet changed topic; "
          f"{len(old_moves)} projects already in the db move to the new topics.")
    return pd.concat([pd.DataFrame(changes, columns=MOVE_COLUMNS), old_moves], ignore_index=True)
