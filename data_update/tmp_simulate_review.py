"""Simula un aggiornamento per vedere il foglio di review dei topic, senza scrivere nel db.

Prende N progetti dal db attuale (con i loro embedding Specter2 di data/specter2.parquet),
finge che siano nuovi e lancia la stessa assegnazione dei topic di update_db.py in modalità
"provisional". L'unica cosa che scrive è il foglio Excel. Il modello dei topic, topic2hier.json,
le tabelle e gli archivi sono solo letti (un salvataggio del modello farebbe fallire lo script).

Da lanciare da data_update/:

    python tmp_simulate_review.py                       # 500 progetti scelti a caso
    python tmp_simulate_review.py --lowest              # i 500 meno simili al loro topic: più candidati
    python tmp_simulate_review.py --n 800 --seed 3 --out new_data/prova.xlsx

Il foglio prodotto non si può applicare con update_db.py --review: i progetti sono già nel db
con il loro topic reale, che non coincide con il "Topic provvisorio" scritto nel foglio.
"""
import argparse
import os
import sys
from configparser import ConfigParser

import lancedb
import numpy as np

import topic_review
from extract_topic import assign_topics, assign_existing_topics, OLD_TOPIC_MODEL_DIR
from specter_store import load_store
from topic_review import load_reviewed_topics

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--n", type=int, default=500, help="quanti progetti fingere nuovi (default 500)")
parser.add_argument("--seed", type=int, default=0, help="seme della scelta casuale")
parser.add_argument("--lowest", action="store_true",
                    help="prende i progetti meno simili al loro topic invece di sceglierli a caso")
parser.add_argument("--out", default="new_data/tmp_topic_review_simulated.xlsx", help="foglio da scrivere")
parser.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.config"))
args = parser.parse_args()


def refuse_to_save(*_, **__):
    raise RuntimeError("la simulazione non deve modificare modello e gerarchia")


# rete di sicurezza: in modalità provisional non si salva nulla, ma se qualcosa cambiasse lo script si ferma
topic_review.save_with_backup = refuse_to_save

config = ConfigParser()
config.read(args.config)
threshold = config.getfloat("topics", "similarity_threshold", fallback=0.92)
min_cluster_size = config.getint("topics", "min_cluster_size", fallback=5)
bonus = config.getfloat("topics", "reviewed_topic_bonus", fallback=0.02)

store = load_store("../data/specter2.parquet")
if store is None:
    sys.exit("data/specter2.parquet non trovato")
store_ids, store_embs = store

projects = (lancedb.connect("../data").open_table("projects_uncase").search()
            .select(["projectID", "title", "objective"]).limit(None).to_pandas())
projects = projects[projects["projectID"].isin(set(store_ids.tolist()))].reset_index(drop=True)
row = {int(p): i for i, p in enumerate(store_ids)}
embs = store_embs[[row[int(p)] for p in projects["projectID"]]]

if args.lowest:
    from bertopic import BERTopic
    model = BERTopic.load(OLD_TOPIC_MODEL_DIR)
    _, similarity, _ = assign_existing_topics(model, embs, load_reviewed_topics(OLD_TOPIC_MODEL_DIR),
                                              threshold, bonus)
    pick = np.argsort(similarity)[:args.n]
else:
    pick = np.random.default_rng(args.seed).choice(len(projects), size=min(args.n, len(projects)), replace=False)
pick = np.sort(pick)

new_df = projects.iloc[pick].reset_index(drop=True)
print(f"{len(new_df)} projects of the current db treated as new ({'lowest similarity' if args.lowest else 'random'}).")

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
assign_topics(new_df, embs[pick], similarity_threshold=threshold, min_cluster_size=min_cluster_size,
              review="provisional", sheet_path=args.out, reviewed_bonus=bonus)
if os.path.exists(args.out):
    print(f"Sheet written: {os.path.abspath(args.out)}")
