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
from topic_review import Hierarchy, ReviewContext, review_and_apply, load_reviewed_topics

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
                                similarity_threshold, min_cluster_size, report_path, auto_assigned=None):
    """Raccoglie i progetti sotto soglia, li clusterizza e salva il report da revisionare.
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

    if report_path:
        report.to_csv(report_path, index=False)

    n_clusters = report.loc[report['cluster'] >= 0, 'cluster'].nunique()
    print(f'{len(new_df)} new projects assigned to existing topics.\n'
          f'{len(report)} have similarity < {similarity_threshold}: '
          f'{n_clusters} candidate new topics, {(report["cluster"] == -1).sum()} isolated projects.')
    if report['auto_assigned'].any():
        print(f'{report["auto_assigned"].sum()} of them were assigned to topics created in previous reviews.')
    if report_path:
        print(f'Review the candidates in {report_path}')

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


@dataclass
class TopicAssignment:
    topics: pd.DataFrame      # projectID, topic_name, topic_name_hierarchy dei progetti nuovi
    moves: pd.DataFrame       # progetti già nel db che passano a un topic nuovo (topic_review.MOVE_COLUMNS)
    embeddings: np.ndarray    # embedding Specter2 dei progetti nuovi, nell'ordine di new_df


def assign_topics(new_df, specter_embs=None, similarity_threshold=0.92, min_cluster_size=5,
                  report_path=None, review='none', decisions_path=None, reviewed_bonus=0.02,
                  existing=None, existing_bonus=-0.005):
    """specter_embs: embedding Specter2 dei progetti di new_df, nello stesso ordine
    (None = calcolati qui).
    review: 'none' (topic più vicino), 'interactive' (revisione a terminale dei
    candidati) o 'file' (riapplica le decisioni salvate in decisions_path).
    reviewed_bonus: vedi assign_existing_topics.
    existing: progetti già nel db (topic_review.ExistingProjects) che un topic accettato
    nella revisione può prendere, con bonus existing_bonus (vedi topic_review.existing_moves)."""
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
                                         similarity, similarity_threshold, min_cluster_size, report_path,
                                         auto_assigned)

    # revisione dei candidati: può aggiungere topic a modello e gerarchia (con backup)
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
        existing=existing,
        similarity_threshold=similarity_threshold,
        existing_bonus=existing_bonus,
    )
    topics, moves = review_and_apply(ctx, review, decisions_path, OLD_TOPIC_MODEL_DIR,
                                     TOPIC_HIER_DICT_DIR, BACKUP_DIR)

    return TopicAssignment(topics=topics_to_frame(new_df['projectID'].values, topics, hierarchy),
                           moves=moves, embeddings=np.asarray(new_embs))
