# ------------------------------------------------------------------------------
# Archivio degli embedding Specter2 di tutti i progetti del db (data/specter2.parquet,
# colonne projectID e vector). Serve a riassegnare i progetti già nel db quando la
# revisione crea un topic nuovo (vedi reassign_existing.py). update_db.py vi aggiunge
# gli embedding dei progetti nuovi a ogni aggiornamento.
# ------------------------------------------------------------------------------

import os

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def load_store(path):
    """Restituisce (projectID, embedding) oppure None se l'archivio non esiste.
    Legge anche i parquet scritti da pandas (vector come lista variabile, colonna
    dell'indice in più), purché tutti i vettori abbiano la stessa dimensione."""
    if not path or not os.path.exists(path):
        return None
    table = pq.read_table(path, columns=["projectID", "vector"])
    ids = table.column("projectID").to_numpy()
    vectors = table.column("vector").combine_chunks()
    if pa.types.is_fixed_size_list(vectors.type):
        dim = vectors.type.list_size
    else:
        lengths = np.unique(pc.list_value_length(vectors).to_numpy(zero_copy_only=False))
        if len(lengths) > 1:
            raise ValueError(f"{path}: vettori di dimensioni diverse {lengths.tolist()}")
        dim = int(lengths[0]) if len(lengths) else 0
    embs = vectors.flatten().to_numpy(zero_copy_only=False).reshape(-1, dim).astype(np.float32)
    return ids, embs


def embeddings_for(path, project_ids):
    """Embedding dei progetti dati, nello stesso ordine, letti dal parquet (projectID,
    vector) in path. Errore (ValueError) se il file non esiste, non è un parquet, ha
    projectID ripetuti o non ha l'embedding di qualche progetto."""
    if str(path).endswith(".npy"):
        raise ValueError(f"{path}: gli .npy (embedding per posizione) non sono più supportati, "
                         "usare un parquet projectID -> vector (vedi compute_embeddings.py)")
    store = load_store(path)
    if store is None:
        raise ValueError(f"{path} non trovato")
    ids, embs = store
    row = pd.Series(np.arange(len(ids)), index=ids)
    if row.index.duplicated().any():
        dup = sorted(set(row.index[row.index.duplicated()].tolist()))
        raise ValueError(f"{path}: projectID ripetuti, es. {dup[:5]}")
    wanted = pd.Index(np.asarray(project_ids, dtype=np.int64))
    missing = wanted[~wanted.isin(row.index)]
    if len(missing):
        raise ValueError(f"{path}: {len(missing)} progetti senza embedding, es. {missing[:5].tolist()}")
    return embs[row.loc[wanted].to_numpy()]


def update_store(path, project_ids, embeddings):
    """Aggiunge (o sostituisce) gli embedding dei progetti dati. La scrittura è atomica.
    Restituisce il numero di righe dell'archivio."""
    ids = np.asarray(project_ids, dtype=np.int32)
    embs = np.asarray(embeddings, dtype=np.float32)
    if embs.ndim != 2 or len(embs) != len(ids):
        raise ValueError(f"{len(ids)} progetti ma embedding di forma {embs.shape}")

    current = load_store(path)
    if current is not None:
        old_ids, old_embs = current
        if old_embs.shape[1] != embs.shape[1]:
            raise ValueError(f"embedding di dimensione {embs.shape[1]}, l'archivio ne ha {old_embs.shape[1]}")
        keep = ~np.isin(old_ids, ids)
        ids = np.concatenate([old_ids[keep].astype(np.int32), ids])
        embs = np.vstack([old_embs[keep], embs])

    vectors = pa.FixedSizeListArray.from_arrays(pa.array(embs.ravel()), embs.shape[1])
    table = pa.table({"projectID": pa.array(ids, pa.int32()), "vector": vectors})
    tmp = f"{path}.tmp"
    pq.write_table(table, tmp)
    os.replace(tmp, path)
    return len(ids)
