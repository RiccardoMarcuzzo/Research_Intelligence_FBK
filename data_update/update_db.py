
# ------------------------------------------------------------------------------
# Questo script permette di aggiornare in maniera automatica i dati utilizzati
# in Research Intelligence. 
# Innanzitutto bisogna scaricare i dati da cordis in formato json (di seguito il 
# link per il programma Horizon Europe: https://data.europa.eu/data/datasets/cordis-eu-research-projects-under-horizon-europe-2021-2027?locale=en).
# Quindi si unzippa la cartella, quindi si inserisce in new_data (nella directory
# corrente). Quindi si inserisce in new_data_folder_name di settings.config il nome
# della cartella che si è aggiunta, infine si lancia lo script.
# Sono supportati sia il vecchio export (project.json, organization.json, ...) sia
# quello con un file json per progetto: il formato è riconosciuto da cordis_loader.py.
# ------------------------------------------------------------------------------

import os
import sys
import argparse
import json
from configparser import ConfigParser
from pathlib import Path

import lancedb
import pandas as pd
import pyarrow as pa
import stopwordsiso as stopwords
from lancedb.index import BTree, LabelList, Bitmap
from pandas.api.types import is_integer_dtype

from extract_embedding import extract_bgem3
from extract_topic import assign_topics
from topic_review import ReviewAborted
from format_name import format_name
from cordis_loader import load_projects, load_organizations, load_deliverables, detect_format, CordisFormatError
from lance_maintenance import repair_tables
from specter_store import update_store, embeddings_for
from reassign_existing import load_existing, write_moves, rebuild_project_graphs
from generate_treemap import write_treemap, load_topic2hier

parser = argparse.ArgumentParser(description="Updates Research Intelligence data.")
parser.add_argument("--projects", action="store_true", help="updates projects")
parser.add_argument("--participants", action="store_true", help="updates participants")
parser.add_argument("--deliverables", action="store_true", help="updates deliverables")
parser.add_argument("--publications", action="store_true", help="updates publications")
parser.add_argument("--config", type=Path,
                    default=Path(__file__).with_name("settings.config"),
                    help="percorso del file di configurazione (default: settings.config accanto allo script)")
parser.add_argument("--no-review", action="store_true",
                    help="non rivedere i possibili topic nuovi: ogni progetto tiene il topic esistente più vicino")
parser.add_argument("--decisions", type=Path,
                    help="riapplica le decisioni sui topic salvate in questo file, senza revisione interattiva")
args = parser.parse_args()

no_flags = not (args.projects or args.participants or args.deliverables or args.publications)
UPDATE_PROJECTS = args.projects or no_flags
UPDATE_PARTICIPANTS = args.participants or no_flags
UPDATE_DELIVERABLES = args.deliverables or no_flags
UPDATE_PUBLICATIONS = args.publications or no_flags

FP_DICT = {
    'HORIZON': 9,
}

CONFIG_PATH = args.config
config = ConfigParser()
if not config.read(CONFIG_PATH):
    print(f"File di configurazione non trovato: {CONFIG_PATH}")
    sys.exit(1)

# data directories
NEW_DATA_FOLDER_NAME = config["paths"]["new_data_folder_name"]
if not NEW_DATA_FOLDER_NAME:
    print('You did not provide any new data directory.\n'
          f'Please check the config file at {CONFIG_PATH}')
    sys.exit(1)
# embedding precalcolati dei progetti nuovi: parquet (projectID, vector) scritti da
# compute_embeddings.py; vuoto = calcolati qui
BGE_EMBS = config['paths']['bge_embedding_file']
SPECTER_EMBS = config['paths']['specter2_embedding_file']
ORG_JSON_PATH = os.path.join(os.path.dirname(__file__), '../data/organisations.json')
TOPIC_HIER_PATH = os.path.join(os.path.dirname(__file__), '../data/topic2hier.json')
# treemap della pagina Concept, rigenerata da topic2hier.json dopo lo step 1
TREEMAP_PATH = os.path.join(os.path.dirname(__file__), '../assets/treemap.json')
PROJECT_GRAPH_DIR = os.path.join(os.path.dirname(__file__), '../data/project_graphs')
# embedding Specter2 di tutti i progetti del db (projectID, vector): servono a
# riassegnare i progetti già nel db quando la revisione crea un topic nuovo
SPECTER_STORE_PATH = os.path.join(os.path.dirname(__file__), '../data/specter2.parquet')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), '../data/backups')

# topic modelling dei nuovi progetti
TOPIC_SIM_THRESHOLD = config.getfloat('topics', 'similarity_threshold', fallback=0.92)
TOPIC_MIN_CLUSTER_SIZE = config.getint('topics', 'min_cluster_size', fallback=5)
TOPIC_REPORT_PATH = config.get('topics', 'candidates_report_file', fallback='new_data/topic_candidates.csv')
TOPIC_DECISIONS_PATH = config.get('topics', 'decisions_file', fallback='new_data/topic_decisions.json')
TOPIC_REVIEWED_BONUS = config.getfloat('topics', 'reviewed_topic_bonus', fallback=0.02)
TOPIC_EXISTING_BONUS = config.getfloat('topics', 'reviewed_topic_bonus_existing', fallback=-0.005)

# revisione dei possibili topic nuovi: interattiva solo se c'è un terminale
if args.decisions:
    TOPIC_REVIEW, TOPIC_DECISIONS_PATH = 'file', str(args.decisions)
elif args.no_review or not sys.stdin.isatty():
    TOPIC_REVIEW = 'none'
else:
    TOPIC_REVIEW = 'interactive'

# nomi delle colonne del vecchio export (project.json, organization.json); il formato
# con un file per progetto non li usa
COLUMNS = dict(config['columns']) if config.has_section('columns') else {}

db = lancedb.connect("../data")

# tabelle lette dalla dashboard: niente indici vettoriali (distanze approssimate) né
# colonne dictionary (to_pandas fallisce sulle righe aggiunte); vedi lance_maintenance.py
repair_tables(db)

projects_tbl = db.open_table("projects_uncase")


def count_deliverables(project_ids):
    """Numero di deliverables per progetto (righe di deliverables, compresi quelli senza
    link), 0 per chi non ne ha. È lo stesso valore di n_deliverables in projects_uncase."""
    ids = sorted({int(p) for p in project_ids})
    counts = pd.Series(0, index=ids, dtype="int64")
    if not ids:
        return counts
    deliverables_tbl = db.open_table("deliverables")
    found = (
        deliverables_tbl.search()
        .where(f"projectID IN ({', '.join(map(str, ids))})")
        .select(["projectID"])
        .limit(max(deliverables_tbl.count_rows(), 1))
        .to_pandas()
        .groupby("projectID")
        .size()
    )
    counts.update(found)
    return counts

# 0.1: caricamento df project (vecchio export o un file per progetto, vedi cordis_loader.py)
try:
    print(f"Reading {NEW_DATA_FOLDER_NAME} ({detect_format(NEW_DATA_FOLDER_NAME)} format)")
    new_proj_df = load_projects(NEW_DATA_FOLDER_NAME, COLUMNS)
except CordisFormatError as e:
    print(e)
    sys.exit(1)

new_proj_df['fp'] = new_proj_df['fp'].map(FP_DICT)

if not is_integer_dtype(new_proj_df['projectID']):
    print(
        "ATTENTION: project ids in new data are not int "
        f"(actual dtype: {new_proj_df['projectID'].dtype}). "
        "Please check it yourself and convert it before running this script."
    )
    print(new_proj_df[new_proj_df['projectID'].isna()])
    sys.exit(1)

# tutti i progetti dell'export, anche quelli già nel db: lo step 3 ne allinea i deliverables
export_project_ids = set(new_proj_df['projectID'])

# 0.2: recupero progetti nuovi
done_projectIDs = set(projects_tbl.to_arrow().column("projectID").unique().to_pylist())

new_proj_df = new_proj_df[~new_proj_df['projectID'].isin(done_projectIDs)]


#* STEP 1: AGGIORNAMENTO PROJECTS_TBL
if UPDATE_PROJECTS:
    if new_proj_df.empty:
        print("There are no new projects. Aborting session.")
        sys.exit(1)

    # 1.1: embedding precalcolati, letti per projectID: ogni progetto nuovo deve avere il
    # suo, altrimenti ci si ferma (Specter2 prima di calcolare bge-m3, che è lento)
    def precomputed_embeddings(path, name):
        try:
            return embeddings_for(path, new_proj_df['projectID'])
        except ValueError as e:
            print(f"{name} embeddings: {e}\nPlease revise your data (see compute_embeddings.py).")
            sys.exit(1)

    specter_embs = precomputed_embeddings(SPECTER_EMBS, 'Specter2') if SPECTER_EMBS else None

    # embedding per ricerca semantica
    bge_dim = projects_tbl.schema.field('vector').type.list_size
    if BGE_EMBS:
        bge_embs = precomputed_embeddings(BGE_EMBS, 'bge-m3')
        if bge_embs.shape[1] != bge_dim:
            print(f"bge-m3 embeddings in {BGE_EMBS} have dimension {bge_embs.shape[1]}, "
                  f"projects_uncase.vector has {bge_dim}.")
            sys.exit(1)
    else:
        bge_embs = extract_bgem3(new_proj_df)

    # 1.2: topic modelling
    # i progetti sotto soglia finiscono nel report dei possibili topic nuovi e vengono
    # revisionati prima di scrivere qualsiasi cosa nei db (vedi topic_review_cli.py).
    # Un topic accettato può prendere anche progetti già nel db (con una penalità)
    existing = None
    if TOPIC_REVIEW != 'none':
        existing = load_existing(projects_tbl, SPECTER_STORE_PATH, exclude_ids=new_proj_df['projectID'])
        if existing is None:
            print(f"WARNING: {SPECTER_STORE_PATH} not found: projects already in the db "
                  "will not be reassigned to new topics.")
    try:
        assignment = assign_topics(new_proj_df, specter_embs,
                                   similarity_threshold=TOPIC_SIM_THRESHOLD,
                                   min_cluster_size=TOPIC_MIN_CLUSTER_SIZE,
                                   report_path=TOPIC_REPORT_PATH,
                                   review=TOPIC_REVIEW,
                                   decisions_path=TOPIC_DECISIONS_PATH,
                                   reviewed_bonus=TOPIC_REVIEWED_BONUS,
                                   existing=existing,
                                   existing_bonus=TOPIC_EXISTING_BONUS)
    except (ReviewAborted, KeyboardInterrupt) as e:
        print(f"\n{e or 'Review interrupted'}. No database was modified; "
              f"decisions taken so far are in {TOPIC_DECISIONS_PATH}.")
        sys.exit(1)

    new_proj_df = new_proj_df.merge(assignment.topics, on='projectID', how='left')

    # 1.3 inserimento campi vuoti
    new_proj_df['participants'] = [[] for _ in range(len(new_proj_df))]
    # i deliverables possono essere stati caricati prima dei progetti (--deliverables)
    new_proj_df['n_deliverables'] = new_proj_df['projectID'].map(count_deliverables(new_proj_df['projectID']))
    new_proj_df['n_publications'] = 0
    new_proj_df['vector'] = list(bge_embs)

    # 1.4 inserimento nel lancedb originale
    projects_tbl.add(new_proj_df)
    print('projects_uncase successfully updated!')

    # 1.5 embedding Specter2 dei progetti nuovi nell'archivio, per le riassegnazioni future
    n_store = update_store(SPECTER_STORE_PATH, new_proj_df['projectID'], assignment.embeddings)
    print(f'Specter2 embeddings stored ({n_store} projects in {SPECTER_STORE_PATH}).')

    # 1.6 progetti già nel db passati ai topic nuovi (projects_uncase e participants)
    if not assignment.moves.empty:
        log = write_moves(db, assignment.moves, BACKUP_DIR)
        projects_tbl = db.open_table("projects_uncase")   # handle aggiornato dopo la scrittura
        print(f'{len(assignment.moves)} projects already in the db moved to new topics (log: {log}).')
        if not UPDATE_PARTICIPANTS:
            # altrimenti i grafi vengono rigenerati dallo step 2
            rebuild_project_graphs(projects_tbl, PROJECT_GRAPH_DIR)
            print('project graph successfully updated!')


#* STEP 2: AGGIORNAMENTO PARTICIPANTS_TBL
if UPDATE_PARTICIPANTS:
    lowercase_stopwords = stopwords.stopwords(['bg','ca','cs','da','de','nl','el','en','fi','fr','ga','gl','he','hr','hu','it','la','lv','lt','no','pl','pt','ro','ru','sk','sl','es','sv','tr','uk'])

    with open(ORG_JSON_PATH, "r", encoding="utf-8") as f:
        org_dict = {int(k): v for k, v in json.load(f).items()}

    # 2.1: recupero progetti senza participants
    participants_tbl = db.open_table("participants")
    new_org_proj_df = load_organizations(NEW_DATA_FOLDER_NAME, COLUMNS)
    new_org_proj_df = new_org_proj_df.rename(columns={'name': 'old_name'})

    # organizzazioni con più paesi nello stesso campo (es. "DE;HU"): una riga per paese
    new_org_proj_df['countryCode'] = new_org_proj_df['countryCode'].str.split(';')
    new_org_proj_df = new_org_proj_df.explode('countryCode', ignore_index=True)
    new_org_proj_df['countryCode'] = new_org_proj_df['countryCode'].str.strip()

    todo_df = (
        projects_tbl
        .search()
        .where("array_length(participants) = 0")
        .select(["projectID", "topic_name", "fp", "topic_name_hierarchy"])
        .limit(projects_tbl.count_rows())
        .to_pandas()
    )

    todo_projectIDs = todo_df['projectID'].tolist()
    new_org_proj_df = new_org_proj_df[new_org_proj_df['projectID'].isin(todo_projectIDs)]

    new_org_proj_df = new_org_proj_df.merge(todo_df, on='projectID', how='left')

    # 2.2: inserimento dei nomi corretti 
    new_org_proj_df['name'] = new_org_proj_df['organisationID'].map(org_dict)
    mask = new_org_proj_df["name"].isna()
    new_org_proj_df.loc[mask, "name"] = (
        new_org_proj_df.loc[mask, "old_name"].astype(str).apply(format_name, args=(lowercase_stopwords,))
    )
    new_org_proj_df = new_org_proj_df.drop(columns='old_name')

    new_orgs = (
        new_org_proj_df
        .loc[~new_org_proj_df['organisationID'].isin(org_dict.keys()), ['organisationID', 'name']]
        .drop_duplicates('organisationID')
    )

    for org_id, name in zip(new_orgs['organisationID'], new_orgs['name']):
        org_dict[int(org_id)] = name

    with open(ORG_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in org_dict.items()}, f, ensure_ascii=False, indent=2)

    # 2.3: aggiornamento di participants_tbl
    new_org_proj_df['netEcContribution'] = (
        pd.to_numeric(new_org_proj_df['netEcContribution'], errors='coerce')
        .round()
        .astype('Int64')
    )
    participants_tbl.add(new_org_proj_df)
    print('participants successfully updated!')


    # 2.4: aggiornamento di projects_tbl
    participants_by_project = (
        new_org_proj_df
        .dropna(subset=['name'])
        .groupby('projectID')['name']
        .apply(lambda s: list(dict.fromkeys(s)))   # rimuove i duplicati mantenendo l'ordine
        .to_dict()
    )

    update_df = pd.DataFrame({
        'projectID': list(participants_by_project.keys()),
        'participants': list(participants_by_project.values()),
    })

    (
        projects_tbl
        .merge_insert("projectID")
        .when_matched_update_all()
        .execute(update_df)
    )

    # 2.5: aggiornamento di projects_graph
    rebuild_project_graphs(projects_tbl, PROJECT_GRAPH_DIR)
    print('project graph successfully updated!')


#* STEP 3: AGGIORNAMENTO DELIVERABLES_TBL
# Per i progetti dell'export la tabella segue l'export: titolo ufficiale e physUrl
# aggiornato, deliverables tolti da CORDIS cancellati. Gli autori (estratti dai pdf, vedi
# legacy_extract_deliverables.py) si conservano: per id, oppure per physUrl dalle righe
# scritte prima che la tabella avesse la colonna id. I progetti assenti dall'export
# (es. H2020) non vengono toccati. Al primo run vengono riscritti tutti i deliverables dei
# progetti dell'export, dai successivi solo quelli nuovi o cambiati.
if UPDATE_DELIVERABLES:
    # 3.1 deliverables dell'export (solo formato records: il vecchio non ha i titoli)
    if detect_format(NEW_DATA_FOLDER_NAME) == 'legacy':
        print('Deliverables can only be updated from an export with one file per project '
              f'(project-rcn-*.json): {NEW_DATA_FOLDER_NAME} is in the old format.')
        if args.deliverables:
            sys.exit(1)
    else:
        try:
            export_deliv = load_deliverables(NEW_DATA_FOLDER_NAME)
        except CordisFormatError as e:
            print(e)
            sys.exit(1)
        if not is_integer_dtype(export_deliv['projectID']):
            print("ATTENTION: some deliverables have a non-numeric project id:")
            print(export_deliv[export_deliv['projectID'].isna()])
            sys.exit(1)

        deliverables_tbl = db.open_table("deliverables")
        # colonna id: chiave dei deliverables tra un aggiornamento e l'altro (la dashboard
        # non la legge); le righe scritte prima restano con id null
        if 'id' not in deliverables_tbl.schema.names:
            deliverables_tbl.add_columns(pa.field('id', pa.string()))
        current = deliverables_tbl.to_pandas()

        # 3.2 righe attese per i progetti dell'export, con gli autori già estratti
        authors_by_id = current.dropna(subset=['id']).set_index('id')['authors']
        authors_by_url = current.dropna(subset=['physUrl']).drop_duplicates('physUrl').set_index('physUrl')['authors']
        target = export_deliv.copy()
        authors = target['id'].map(authors_by_id)
        authors = authors.where(authors.notna(), target['physUrl'].map(authors_by_url))
        target['authors'] = authors.where(authors.notna(), '{}')
        target = target[deliverables_tbl.schema.names]

        # 3.3 nuovi o cambiati (titolo, link o progetto): inseriti o aggiornati per id
        cols = ['projectID', 'title', 'physUrl', 'authors']
        old = current.dropna(subset=['id']).set_index('id')[cols].reindex(target['id'])
        same = pd.Series(True, index=target.index)
        for col in cols:
            a, b = target[col].reset_index(drop=True), old[col].reset_index(drop=True)
            same &= ((a == b) | (a.isna() & b.isna())).to_numpy()
        changed = target[~same]

        # 3.4 da cancellare: righe senza id dei progetti dell'export (sostituite da quelle
        # con id) e deliverables non più presenti nell'export
        export_projects = export_project_ids | set(export_deliv['projectID'])
        in_scope = current['projectID'].isin(export_projects)
        stale_ids = current.loc[in_scope & current['id'].notna() & ~current['id'].isin(set(target['id'])), 'id'].tolist()
        unkeyed = in_scope & current['id'].isna()
        unkeyed_projects = sorted(int(p) for p in current.loc[unkeyed, 'projectID'].unique())

        # prima le scritture e poi le cancellazioni: se il run si interrompe a metà, gli
        # autori delle righe senza id sono già passati su quelle con id
        if len(changed):
            (
                deliverables_tbl
                .merge_insert("id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(pa.Table.from_pandas(changed, schema=deliverables_tbl.schema, preserve_index=False))
            )
        for i in range(0, len(unkeyed_projects), 1000):
            ids = ', '.join(map(str, unkeyed_projects[i:i + 1000]))
            deliverables_tbl.delete(f"id IS NULL AND projectID IN ({ids})")
        for i in range(0, len(stale_ids), 1000):
            ids = ', '.join("'" + str(x).replace("'", "''") + "'" for x in stale_ids[i:i + 1000])
            deliverables_tbl.delete(f"id IN ({ids})")

        n_with_authors = int((target['authors'] != '{}').sum())
        print(f'deliverables: {len(changed)} added or updated, {int(unkeyed.sum()) + len(stale_ids)} '
              f'old rows removed; {n_with_authors} of {len(target)} export deliverables have authors.')

        if len(changed) or len(stale_ids) or len(unkeyed_projects):
            deliverables_tbl.create_index("projectID", config=BTree())
            deliverables_tbl.create_index("id", config=BTree())

        # 3.5 n_deliverables dei progetti dell'export (la dashboard lo mostra): si scrivono
        # solo i conteggi cambiati
        counts = count_deliverables(export_projects)
        current_counts = (
            projects_tbl.search().select(['projectID', 'n_deliverables']).limit(None).to_pandas()
            .set_index('projectID')['n_deliverables']
        )
        counts = counts[counts.index.isin(current_counts.index)]
        counts = counts[counts != current_counts.reindex(counts.index)]
        # i progetti non ancora in projects_uncase non vengono creati: prenderanno il
        # conteggio quando saranno aggiunti (step 1)
        if len(counts):
            update_df = pd.DataFrame({
                'projectID': counts.index.astype(projects_tbl.schema.field('projectID').type.to_pandas_dtype()),
                'n_deliverables': counts.values.astype(projects_tbl.schema.field('n_deliverables').type.to_pandas_dtype()),
            })
            (
                projects_tbl
                .merge_insert("projectID")
                .when_matched_update_all()
                .execute(update_df)
            )
            print(f'n_deliverables updated for {len(counts)} projects.')


#* STEP 4: AGGIORNAMENTO PUBLICATIONS_TBL
if UPDATE_PUBLICATIONS:
    publications_tbl = db.open_table("publications")


#* STEP 5: CONVERSIONE E INDEXING FINALE
if UPDATE_PROJECTS:
    projects_tbl.create_index("topic_name_hierarchy",config=LabelList())
    projects_tbl.create_index("projectID", config=BTree())
    # nessun indice sulla colonna vector: la dashboard filtra i risultati con una soglia
    # sulla distanza, che deve essere esatta (vedi lance_maintenance.py)

    # topic nuovi, progetti nuovi e spostati cambiano la treemap della pagina Concept
    write_treemap(projects_tbl, load_topic2hier(TOPIC_HIER_PATH), TREEMAP_PATH)
    print(f'treemap successfully updated ({TREEMAP_PATH})!')


if UPDATE_PARTICIPANTS:
    participants_tbl.create_index("countryCode", config=Bitmap())
    participants_tbl.create_index("activityType", config=Bitmap())
    participants_tbl.create_index("fp", config=Bitmap())         
    participants_tbl.create_index("projectID", config=BTree())