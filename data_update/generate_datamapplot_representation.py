"""Genera assets/dmp_for_dash.html (mappa della pagina Concept) con datamapplot.

Le coordinate 2D stanno in data/umap_2d.parquet (projectID, vector_2d), NON ruotate. I progetti
che hanno l'embedding Specter2 in data/specter2.parquet ma non ancora le coordinate vengono
proiettati con transform() del modello UMAP fittato in origine (data/umap_model.joblib): i punti
già presenti non si muovono. Poi la mappa si ridisegna con i titoli e i topic di projects_uncase.

update_db.py chiama update_datamapplot() insieme a write_treemap. Si può lanciare anche da sola:

    python generate_datamapplot_representation.py [--data ../data] [--out ../assets/dmp_for_dash.html]
    python generate_datamapplot_representation.py --bootstrap FILE   # una tantum, vedi bootstrap_umap_2d
"""
import argparse
import os

import joblib
import lancedb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from specter_store import load_store

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, '..', 'data')
DMP_PATH = os.path.join(HERE, '..', 'assets', 'dmp_for_dash.html')

# rotazione antioraria della mappa, in gradi (le coordinate salvate non sono ruotate)
ROTATION_DEGREES = 0


def rotation_matrix(degrees):
    a = np.radians(degrees)
    return np.round([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]], 12)


ROTATION = rotation_matrix(ROTATION_DEGREES)
# al click la pagina Concept riceve l'id del progetto (vedi docs/02-dashboard/pagina-concept.md)
ON_CLICK = """
window.top.postMessage(
  {{type: 'point-clicked', id: `{id}`}},
   '*'
);
"""


def load_coords(path):
    """(projectID int32, coordinate float32 [n, 2]) oppure None se il file non esiste."""
    if not os.path.exists(path):
        return None
    table = pq.read_table(path, columns=['projectID', 'vector_2d'])
    ids = table.column('projectID').to_numpy().astype(np.int32)
    coords = table.column('vector_2d').combine_chunks().flatten().to_numpy(zero_copy_only=False)
    return ids, coords.reshape(-1, 2).astype(np.float32)


def write_coords(path, ids, coords):
    """Scrittura atomica."""
    table = pa.table({
        'projectID': pa.array(np.asarray(ids), pa.int32()),
        'vector_2d': pa.FixedSizeListArray.from_arrays(pa.array(np.asarray(coords, np.float32).ravel()), 2),
    })
    tmp = f'{path}.tmp'
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def bootstrap_umap_2d(src, out, store_path):
    """Una tantum: crea umap_2d.parquet da un parquet (projectID stringa, vector 2D) nello stesso
    ordine del training del modello. Tiene solo gli id numerici presenti in specter2.parquet."""
    table = pq.read_table(src, columns=['projectID', 'vector'])
    raw_ids = table.column('projectID').to_pylist()
    coords = table.column('vector').combine_chunks().flatten().to_numpy(zero_copy_only=False).reshape(-1, 2)
    in_db = set(load_store(store_path)[0].tolist())
    keep = [i for i, p in enumerate(raw_ids) if str(p).isdigit() and int(p) in in_db]
    ids = np.array([int(raw_ids[i]) for i in keep], dtype=np.int32)
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f'{src}: projectID ripetuti')
    write_coords(out, ids, coords[keep])
    return len(ids), len(in_db)


def update_umap_coordinates(store_path, coords_path, model_path):
    """Proietta con il modello UMAP i progetti di specter2.parquet senza coordinate e li aggiunge a
    umap_2d.parquet. Restituisce quanti ne ha aggiunti. Il modello (~1 GB) si carica solo se serve."""
    store = load_store(store_path)
    if store is None:
        raise FileNotFoundError(f'{store_path} non trovato')
    store_ids, embs = store
    current = load_coords(coords_path)
    if current is None:
        raise FileNotFoundError(f'{coords_path} non trovato (vedi --bootstrap)')
    known_ids, known_coords = current

    missing = ~np.isin(store_ids, known_ids)
    if not missing.any():
        return 0
    if not os.path.exists(model_path):
        raise FileNotFoundError(f'{model_path} non trovato')

    model = joblib.load(model_path)
    new_coords = np.asarray(model.transform(embs[missing]), dtype=np.float32)
    write_coords(coords_path,
                 np.concatenate([known_ids, store_ids[missing].astype(np.int32)]),
                 np.vstack([known_coords, new_coords]))
    return int(missing.sum())


def write_datamapplot(projects_tbl, coords_path, out_path=DMP_PATH, degrees=ROTATION_DEGREES):
    """Disegna la mappa dei progetti di projects_uncase che hanno coordinate. Restituisce il numero di punti."""
    import datamapplot   # solo qui: serve nell'ambiente giusto, vedi requirements

    projects = (
        projects_tbl.search()
        .select(['projectID', 'title', 'topic_name_hierarchy'])
        .limit(max(projects_tbl.count_rows(), 1))
        .to_pandas()
    )
    ids, coords = load_coords(coords_path)
    order = {int(p): i for i, p in enumerate(ids)}
    projects = projects[projects['projectID'].isin(order)].reset_index(drop=True)
    data_map = coords[[order[int(p)] for p in projects['projectID']]] @ rotation_matrix(degrees).T

    # un livello di etichette per colonna, foglia per prima (come topic_name_hierarchy)
    topic_labels = np.array([list(h) for h in projects['topic_name_hierarchy']]).T

    plot = datamapplot.create_interactive_plot(
        data_map,
        *topic_labels,
        color_label_text=False,
        hover_text=projects['title'].tolist(),
        extra_point_data=projects[['projectID']].rename(columns={'projectID': 'id'}),
        on_click=ON_CLICK,
        point_radius_min_pixels=1,
        point_radius_max_pixels=8,
        darkmode=True,
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    plot.save(out_path)
    return len(projects)


def rotate_datamapplot(degrees, data_dir=DATA_DIR, out_path=DMP_PATH):
    """Ridisegna la mappa con un'altra rotazione (assoluta, in gradi), senza toccare le coordinate."""
    return write_datamapplot(lancedb.connect(data_dir).open_table('projects_uncase'),
                             os.path.join(data_dir, 'umap_2d.parquet'), out_path, degrees)


def update_datamapplot(projects_tbl, data_dir=DATA_DIR, out_path=DMP_PATH):
    """Coordinate dei progetti nuovi + mappa. Non interrompe mai la pipeline: la mappa è accessoria,
    se qualcosa manca o fallisce stampa un avviso (la mappa vecchia resta dov'è)."""
    try:
        n_new = update_umap_coordinates(os.path.join(data_dir, 'specter2.parquet'),
                                        os.path.join(data_dir, 'umap_2d.parquet'),
                                        os.path.join(data_dir, 'umap_model.joblib'))
        n_points = write_datamapplot(projects_tbl, os.path.join(data_dir, 'umap_2d.parquet'), out_path)
        print(f'datamapplot successfully updated ({out_path}): {n_points} projects, {n_new} new coordinates.')
    except Exception as e:
        print(f'WARNING: datamapplot not updated ({type(e).__name__}: {e}).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=DATA_DIR)
    parser.add_argument('--out', default=DMP_PATH)
    parser.add_argument('--bootstrap', metavar='FILE',
                        help='crea data/umap_2d.parquet da FILE (projectID, vector 2D nell\'ordine del training)')
    parser.add_argument('--rotate', type=float, metavar='GRADI',
                        help='ridisegna la mappa con questa rotazione antioraria assoluta (default: ROTATION_DEGREES)')
    args = parser.parse_args()

    if args.rotate is not None:
        print(f'{rotate_datamapplot(args.rotate, args.data, args.out)} projects, rotation {args.rotate}°.')
    elif args.bootstrap:
        n, n_db = bootstrap_umap_2d(args.bootstrap, os.path.join(args.data, 'umap_2d.parquet'),
                                    os.path.join(args.data, 'specter2.parquet'))
        print(f'umap_2d.parquet: {n} projects with coordinates ({n_db} in specter2.parquet).')
    else:
        update_datamapplot(lancedb.connect(args.data).open_table('projects_uncase'), args.data, args.out)
