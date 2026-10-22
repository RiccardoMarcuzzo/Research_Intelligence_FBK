# ------------------------------------------------------------------------------
# Calcolo degli embedding (Specter2 o bge-m3) dei progetti, salvati in un parquet
# con colonne projectID (int32) e vector (fixed_size_list<float>): ogni embedding è
# legato al suo progetto, non alla posizione in un file. È lo stesso formato di
# data/specter2.parquet (vedi specter_store.py).
#
#   python compute_embeddings.py --model specter2 --source new   # batch da caricare
#   python compute_embeddings.py --model bge --source new
#   python compute_embeddings.py --model specter2 --source db    # tutti i progetti del db
#
# --source new: i progetti della cartella new_data_folder_name di settings.config non
#               ancora in projects_uncase (gli stessi che update_db.py aggiungerà)
# --source db:  tutti i progetti di projects_uncase
#
# ------------------------------------------------------------------------------

import argparse
import os
import sys
from configparser import ConfigParser
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from cordis_loader import load_projects, CordisFormatError
from extract_embedding import extract_bgem3, extract_specter2, get_device

MODELS = {'specter2': 768, 'bge': 1024}

parser = argparse.ArgumentParser(description="Computes Specter2 or bge-m3 embeddings of projects.")
parser.add_argument("--model", choices=sorted(MODELS), required=True)
parser.add_argument("--source", choices=["new", "db"], required=True,
                    help="new: projects of the new CORDIS export not yet in the db; db: all projects in the db")
parser.add_argument("--out", type=Path,
                    help="output parquet (default: new_data/<model>_<export folder>.parquet "
                         "with --source new, '../backup data/<model>.parquet' with --source db)")
parser.add_argument("--config", type=Path, default=Path(__file__).with_name("settings.config"))
parser.add_argument("--device", help="mps, cuda or cpu (default: the fastest available)")
parser.add_argument("--batch-size", type=int, default=32, help="batch size for Specter2")
parser.add_argument("--limit", type=int, help="only the first N projects (for quick checks)")
args = parser.parse_args()

db = lancedb.connect("../data")
projects_tbl = db.open_table("projects_uncase")
db_ids = set(projects_tbl.to_arrow().column("projectID").to_pylist())

if args.source == "new":
    config = ConfigParser()
    if not config.read(args.config):
        print(f"Config file not found: {args.config}")
        sys.exit(1)
    folder = config["paths"]["new_data_folder_name"]
    columns = dict(config["columns"]) if config.has_section("columns") else {}
    try:
        corpus_df = load_projects(folder, columns)
    except CordisFormatError as e:
        print(e)
        sys.exit(1)
    # stessa selezione di update_db.py (0.2)
    corpus_df = corpus_df[~corpus_df["projectID"].isin(db_ids)].reset_index(drop=True)
    default_out = Path("new_data") / f"{args.model}_{Path(folder).name}.parquet"
else:
    corpus_df = (
        projects_tbl
        .search()
        .select(["projectID", "title", "objective"])
        .limit(projects_tbl.count_rows())
        .to_pandas()
    )
    default_out = Path("../backup data") / f"{args.model}.parquet"

if args.limit:
    corpus_df = corpus_df.head(args.limit)

if corpus_df.empty:
    print("No projects to embed.")
    sys.exit(1)

out = args.out or default_out
device = args.device or str(get_device())
print(f"{len(corpus_df)} projects, model {args.model}, device {device} -> {out}")

if args.model == "specter2":
    embs = extract_specter2(corpus_df, batch_size=args.batch_size, device=device, progress=True)
else:
    embs = extract_bgem3(corpus_df, device=device)

embs = np.asarray(embs, dtype=np.float32)
assert embs.shape == (len(corpus_df), MODELS[args.model]), embs.shape

vectors = pa.FixedSizeListArray.from_arrays(pa.array(embs.ravel()), embs.shape[1])
table = pa.table({
    "projectID": pa.array(corpus_df["projectID"].to_numpy(), pa.int32()),
    "vector": vectors,
})
out.parent.mkdir(parents=True, exist_ok=True)
tmp = f"{out}.tmp"
pq.write_table(table, tmp)
os.replace(tmp, out)
print(f"{len(table)} embeddings written to {out}")
