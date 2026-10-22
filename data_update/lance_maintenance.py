# ------------------------------------------------------------------------------
# Manutenzione delle tabelle LanceDB lette dalla dashboard. È idempotente: viene
# eseguita da update_db.py a ogni aggiornamento e si può lanciare anche da sola
# (ad esempio su un db aggiornato con una versione precedente della pipeline):
#
#     python lance_maintenance.py [--data ../data]
#
# 1. Nessun indice vettoriale su projects_uncase. La dashboard scarta i risultati
#    con distanza > 0.45 (scripts/_rag.py) e un indice IVF_PQ restituisce distanze
#    approssimate molto più alte di quelle vere (0.76 invece di 0.41), quindi la
#    ricerca libera resta vuota. Senza indice la ricerca è esatta, come nel db
#    originale, e su ~55k progetti resta veloce.
# 2. Nessuna colonna dictionary (topic_name, role). Le righe aggiunte in seguito
#    hanno un dizionario loro, e to_pandas() su risultati che mescolano righe vecchie
#    e nuove fallisce con "Categorical categories must be unique". Le colonne
#    vengono riscritte come stringhe; per la dashboard non cambia nulla.
# ------------------------------------------------------------------------------

import argparse

import lancedb
import pyarrow as pa
from lancedb.index import BTree, LabelList, Bitmap

TABLES = ("projects_uncase", "participants")

# indici scalari da ricreare dopo la riscrittura di una tabella (gli stessi di update_db.py)
SCALAR_INDEXES = {
    "projects_uncase": [("projectID", BTree), ("topic_name_hierarchy", LabelList)],
    "participants": [("countryCode", Bitmap), ("activityType", Bitmap), ("fp", Bitmap), ("projectID", BTree)],
}


def dictionary_columns(schema):
    return [f.name for f in schema if pa.types.is_dictionary(f.type)]


def vector_indexes(tbl):
    return [i.name for i in tbl.list_indices() if i.index_type.lower().startswith(("ivf", "hnsw"))]


def decode_dictionaries(data):
    for i, field in enumerate(data.schema):
        if pa.types.is_dictionary(field.type):
            value_type = field.type.value_type
            data = data.set_column(i, pa.field(field.name, value_type, field.nullable, field.metadata),
                                   data.column(i).cast(value_type))
    return data


def repair_table(db, name, verbose=True):
    """Rimuove gli indici vettoriali e converte le colonne dictionary in stringhe.
    Restituisce l'elenco delle modifiche fatte (vuoto se la tabella era già a posto)."""
    tbl = db.open_table(name)
    changes = []

    dict_cols = dictionary_columns(tbl.schema)
    if dict_cols:
        n_rows = tbl.count_rows()
        data = decode_dictionaries(tbl.to_arrow())
        tbl = db.create_table(name, data=data, mode="overwrite")
        if tbl.count_rows() != n_rows:
            raise RuntimeError(f"{name}: {tbl.count_rows()} righe dopo la riscrittura invece di {n_rows}")
        for column, index in SCALAR_INDEXES.get(name, ()):
            tbl.create_index(column, config=index())
        changes.append(f"columns {dict_cols} converted to string")

    for index_name in vector_indexes(tbl):
        tbl.drop_index(index_name)
        changes.append(f"vector index {index_name} dropped")

    if changes and verbose:
        print(f"{name}: " + "; ".join(changes))
    return changes


def repair_tables(db, names=TABLES, verbose=True):
    return {name: repair_table(db, name, verbose) for name in names}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ripara le tabelle LanceDB lette dalla dashboard.")
    parser.add_argument("--data", default="../data", help="cartella del db (default: ../data)")
    args = parser.parse_args()
    result = repair_tables(lancedb.connect(args.data))
    if not any(result.values()):
        print("Tables already OK: nothing to do.")
