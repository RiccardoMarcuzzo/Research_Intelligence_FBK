import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import datamapplot
from umap import UMAP

from specter_store import load_store


def write_datamapplot(path):
    '''
    Prende gli embedding dei progetti nuovi, li inserisce nei totali,
    calcola i 2d embs di tutti, quindi salva la rappresentazione
    '''

    old_embs = pq.read_table('../data/specter_embs_all.parquet')

    # Uniforma il tipo della colonna 'projectID' in new_embs e mantiene solo i nuovi IDs
    new_embs = load_store(path)
    new_embs = new_embs.set_column(
        new_embs.schema.get_field_index("projectID"),
        "projectID",
        pc.cast(new_embs["projectID"], pa.string())
    )
    old_ids = set(old_embs["projectID"].to_pylist())
    mask = pc.invert(pc.is_in(new_embs["projectID"], value_set=pa.array(list(old_ids), type=pa.string())))
    new_unique = new_embs.filter(mask)

    # Concatena old_embs e new_embs
    all_embs = pa.concat_tables([old_embs, new_unique])

    # Riduce gli embedding in 2 dimensioni
    
    X = np.stack(all_embs["embedding"].to_pylist())
    data_map = UMAP(
        n_neighbors=15,
        n_components=2,
        min_dist=0.0,
        metric="cosine",
        random_state=1
    ).fit_transform(X)

    rotation_matrix = np.array([[0, -1],
                            [1,  0]])
    data_map = data_map @ rotation_matrix.T

    vector_2d = pa.array(data_map.tolist(), type=pa.list_(pa.float32()))
    all_embs = all_embs.append_column("vector_2d", vector_2d)

    new_ids = set(new_embs["projectID"].to_pylist())
    mask_all = pc.is_in(
        all_embs["projectID"],
        value_set=pa.array(list(new_ids), type=pa.string())
    )
    all_filtered = all_embs.filter(mask_all)

    # Riconverte projectID a int32
    idx = all_filtered.schema.get_field_index("projectID")
    all_filtered = all_filtered.set_column(
        idx,
        "projectID",
        pc.cast(all_filtered["projectID"], pa.int32())
    )


    pass

# ! NOTA: siccome la versione di datamapplot è vecchia, ma per non toccare l'ambiente di dash_app2, va lanciato nell'ambiente bertopic2
# abbiamo bisogno di: 
# (a) una matrice di coordinate per ciascun documento, 
# (b) un array dei topic per ciascun documento, 
# (c) un array dei titoli per ciascun documento

# (a) -> ricaviamo dagli embedding 2D
data_map = np.load('../data/specter_2d_embs_all.npy')

rotation_matrix = np.array([[0, -1],
                            [1,  0]])
data_map = data_map @ rotation_matrix.T

projects_df = pd.read_parquet('/data/rmarcuzzo/dash_viz_fbk_real/data/docs.parquet')

# (b) - (c) -> I topic per ogni documento li ricaviamo da topics_project_umap_15_hdbscan_100_3_TOT.csv
# Siccome i topic nel dataset dei progetti sono indicati con un codice numerico (da -1 a 119), recuperiamo i loro nomi e li mettiamo in un lookup table

topic_labels = [lst for lst in projects_df['topic_name_hierarchy']]
n_levels = len(topic_labels[0])
topic_labels_per_doc = list()

for i in range(n_levels):
    level = list()
    for lst in topic_labels:
        level.append(lst[i])
    topic_labels_per_doc.append(level)
topic_labels = np.array(topic_labels_per_doc)

proj_names = projects_df.loc[:, ['title']]

extra_point_data = projects_df.loc[:, ['id']]
on_click = """
window.top.postMessage(
  {{type: 'point-clicked', id: `{id}`}},
   '*'
);
"""

proj_names = projects_df['title'].tolist()

color_mapping = {}
color_mapping['Health & Medicine'] = '#1E88E5'
color_mapping['Social Sciences & Humanities'] = '#FF8C42'
color_mapping['Engineering & Technology'] = "#9383A6"
color_mapping['Physical & Mathematical Sciences'] = '#D32F2F'
color_mapping['Earth & Life Science'] = '#2D6A4F'
color_mapping['Unlabelled'] = "#A6A6A6"
marker_color_array = np.asarray([color_mapping[x] for x in topic_labels[3]])

# ORA basta plottare quanto fatto
plot = datamapplot.create_interactive_plot(
    data_map,
    *topic_labels,
    color_label_text=False,
    # marker_color_array = marker_color_array,
    hover_text = proj_names,
    extra_point_data=extra_point_data,
    on_click=on_click,
    point_radius_min_pixels=1,
    point_radius_max_pixels=8,
    darkmode=True,
)

plot.save('/data/rmarcuzzo/dash_viz_fbk_real/assets/dmp_for_dash.html')

