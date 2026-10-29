"""
Test della pipeline di aggiornamento dati (data_update/). La dashboard non ha test.

ESECUZIONE (da data_update/, con il virtual env attivo)

    pytest test.py                      # test veloci (~1 min): i modelli ML sono sostituiti da fake
    RUN_SLOW=1 pytest test.py           # anche i test con i modelli reali (bge-m3, Specter2, BERTopic)
    pytest test.py -rs                  # stampa anche il motivo di ogni test saltato (skipped)
    pytest test.py -k TestRealDbState   # una sola classe (o un solo test, o una parola nel nome)
    pytest test.py -x                   # si ferma al primo fallimento

ORGANIZZAZIONE (ogni sezione inizia con un banner "# ====" numerato)

    0. Infrastruttura: costanti, helper, fixture, sandbox, esecuzione di update_db.py con
       modelli finti. Non contiene test.
    1. DATI REALI. Leggono settings.config, l'export configurato in new_data/ e data/ così
       come sono, senza scrivere nulla. Un fallimento qui NON è un bug del codice: i dati o
       la configurazione non sono nello stato richiesto dalla documentazione. Il messaggio
       dice cosa fare e dove è spiegato in docs/.
    2. UNIT TEST, un modulo della pipeline per sottosezione, su dati piccoli scritti dai test.
       Un fallimento qui è un bug (o un cambio di comportamento) del modulo indicato.
    3. INTEGRAZIONE: update_db.py e compute_embeddings.py eseguiti davvero in una sandbox (vedi
       sotto). Un fallimento qui è un bug della pipeline, salvo i casi elencati più sotto.
    4. TEST LENTI con i modelli reali (solo con RUN_SLOW=1).

COME LEGGERE IL RISULTATO

    passed   tutto bene.
    skipped  il test non si applica allo stato attuale; è normale. Per esempio: TestExportsAgree
             (serve un export per formato in new_data/), i controlli su deliverables_file o sugli
             embedding precalcolati quando non sono configurati, test_there_are_new_projects
             quando l'export è già tutto nel db, i test lenti senza RUN_SLOW=1. Con -rs si vede
             il motivo di ognuno. Anche molte varianti [legacy] o [records] dei test di
             integrazione sono saltate: deliverables e pubblicazioni esistono solo nel formato
             records, e alcuni test riguardano solo il formato legacy.
    failed   sezione 1: sistemare dati o configurazione seguendo il messaggio.
             sezioni 2-4: c'è un problema nel codice.

FALLIMENTI NELLE SEZIONI 3-4 CHE NON SONO BUG DEL CODICE

    - Errori di schema o "Categorical categories must be unique": data/ non è passata da
      lance_maintenance.py (la sandbox copia il db così com'è). Lo segnala anche
      TestRealDbState. Rimedio: python lance_maintenance.py --data ../data
    - Quasi tutto skipped con "database LanceDB non trovato" o "cartella dei nuovi dati non
      trovata": mancano data/ o l'export configurato in new_data/ (non sono in git). La sandbox
      si costruisce a partire da entrambi.

ISOLAMENTO

Nessun test scrive su ../data o su new_data/. Per i test di integrazione viene costruita una
sandbox temporanea (una sola volta per sessione e per formato) con:
    <tmp>/data/          tabelle LanceDB ridotte, copiate dal db reale (stesso schema),
                         copie di organisations.json e topic2hier.json, project_graphs/ vuota
    <tmp>/data_update/   copia degli script della pipeline, settings.config dedicato e un
                         sottoinsieme dei nuovi dati CORDIS, embedding parquet (projectID,
                         vector)
Il batch della sandbox viene scritto in entrambi i formati dell'export CORDIS, qualunque
sia quello configurato: 'legacy' (project.json, organization.json) e 'records' (un file
per progetto; copie dei file reali se l'export configurato è in questo formato, altrimenti
record sintetici). I test d'integrazione girano quindi due volte, [legacy] e [records].
I dati dell'export vengono letti con cordis_loader.py, come in update_db.py.
Ogni test lavora su una copia fresca della sandbox. update_db.py viene eseguito
in-process con runpy, con cwd e sys.argv impostati come da riga di comando.

VARIABILI D'AMBIENTE (facoltative)

    RUN_SLOW=1       abilita la sezione 4
    TEST_N_NEW       numero di progetti nuovi usati nella sandbox (default 60)
    TEST_N_OLD       numero di progetti già esistenti copiati nella sandbox (default 400)
    TEST_N_NEW_SLOW  numero di progetti nuovi per i test lenti (default 300; BERTopic usa
                     min_cluster_size=50, quindi con pochi documenti trova solo outlier)
"""
from __future__ import annotations

import ast
import asyncio
import io
import importlib
import importlib.util
import inspect
import json
import os
import re
import runpy
import shutil
import sys
import types
from configparser import ConfigParser
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")


# ==============================================================================
# 0.1 COSTANTI
# ==============================================================================
HERE = Path(__file__).resolve().parent
REAL_DATA = HERE.parent / "data"
REAL_CONFIG = HERE / "settings.config"

PIPELINE_FILES = [
    "update_db.py",
    "cordis_loader.py",
    "compute_embeddings.py",
    "create_projgraph.py",
    "extract_deliverables.py",
    "extract_embedding.py",
    "extract_topic.py",
    "format_name.py",
    "generate_treemap.py",
    "generate_datamapplot_representation.py",
    "lance_maintenance.py",
    "specter_store.py",
    "topic_review.py",
    "topic_review_sheet.py",
]
PIPELINE_MODULES = [f[:-3] for f in PIPELINE_FILES]

TODAY = date.today().isoformat()
N_NEW = int(os.environ.get("TEST_N_NEW", 60))
N_OLD = int(os.environ.get("TEST_N_OLD", 400))
N_NEW_SLOW = int(os.environ.get("TEST_N_NEW_SLOW", 300))
N_DUP = 5  # progetti già presenti nel db reinseriti nel project.json della sandbox
RUN_SLOW = os.environ.get("RUN_SLOW") == "1"

slow = pytest.mark.skipif(not RUN_SLOW, reason="test con modelli reali: abilitare con RUN_SLOW=1")

# stesse lingue usate in update_db.py (step 2)
STOPWORD_LANGS = ['bg', 'ca', 'cs', 'da', 'de', 'nl', 'el', 'en', 'fi', 'fr', 'ga', 'gl', 'he',
                  'hr', 'hu', 'it', 'la', 'lv', 'lt', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl',
                  'es', 'sv', 'tr', 'uk']

REQUIRED_CONFIG = {
    "paths": ["new_data_folder_name", "bge_embedding_file", "specter2_embedding_file",
              "deliverables_file", "deliverables_env_path"],
    "columns": ["proj_id", "proj_title", "proj_objective", "proj_fp", "proj_acronym",
                "org_id", "org_name", "org_country_code", "org_activity_type", "org_role",
                "org_proj_ec_contribution", "org_proj_id"],
    "topics": ["similarity_threshold", "min_cluster_size", "review_file",
               "reviewed_topic_bonus"],
}

# colonne che update_db.py (step 3) richiede in deliverables_file, scritto da extract_deliverables.py
DELIVERABLES_REQUIRED = {"id", "projectID", "title", "physUrl", "authors"}


# ==============================================================================
# 0.2 HELPER GENERICI
# ==============================================================================
def read_config(path=REAL_CONFIG):
    cfg = ConfigParser()
    if not cfg.read(path):
        pytest.skip(f"settings.config non trovato: {path}")
    return cfg


def resolve(rel):
    """I path di settings.config sono relativi a data_update/."""
    return HERE / rel if rel else None


def read_fp_dict():
    """Legge FP_DICT da update_db.py senza eseguirlo (lo script lavora a import-time)."""
    tree = ast.parse((HERE / "update_db.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FP_DICT" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("FP_DICT non trovato in update_db.py")


def load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


def stub_modules(monkeypatch, *names, only_missing=False):
    """Sostituisce moduli (anche dotted) con MagicMock. Con only_missing=True
    stubba solo quelli non installati."""
    for name in names:
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            sub = ".".join(parts[:i])
            if only_missing:
                try:
                    importlib.import_module(sub)
                    continue
                except ImportError:
                    pass
            monkeypatch.setitem(sys.modules, sub, MagicMock(name=sub))


def first_labelled(h):
    for name in h:
        if name != "Unlabelled":
            return name
    return "Unlabelled"


def same(a, b):
    """Uguaglianza che tratta None/NaN come equivalenti."""
    a_na = a is None or (isinstance(a, float) and np.isnan(a))
    b_na = b is None or (isinstance(b, float) and np.isnan(b))
    return (a_na and b_na) or a == b


def ids_sql(ids):
    return ", ".join(str(int(i)) for i in ids)


def connect(path):
    lancedb = pytest.importorskip("lancedb")
    return lancedb.connect(str(path))


def scan(tbl, columns=None, where=None):
    q = tbl.search()
    if where:
        q = q.where(where)
    if columns:
        q = q.select(columns)
    return q.limit(max(tbl.count_rows(), 1)).to_arrow()


def indexed_columns(tbl):
    return {c for idx in tbl.list_indices() for c in idx.columns}


def call_format_name(fn, text, stopwords):
    """Chiama format_name sia con la firma (text) sia con (text, lowercase_stopwords)."""
    required = [p for p in inspect.signature(fn).parameters.values()
                if p.default is inspect.Parameter.empty]
    return fn(text, stopwords) if len(required) >= 2 else fn(text)


# ==============================================================================
# 0.3 FIXTURE DI SESSIONE: CONFIG E DATI REALI (sola lettura)
# ==============================================================================
@pytest.fixture(scope="session")
def real_cfg():
    return read_config()


@pytest.fixture(scope="session")
def cols(real_cfg):
    return dict(real_cfg["columns"])


@pytest.fixture(scope="session")
def new_data_dir(real_cfg):
    d = resolve(real_cfg["paths"]["new_data_folder_name"])
    if d is None or not d.is_dir():
        pytest.skip(f"cartella dei nuovi dati non trovata: {d} (vedi new_data_folder_name in settings.config)")
    return d


def _loader():
    """cordis_loader.py della pipeline, caricato una sola volta con un nome diverso da
    quello che update_db importa nella sandbox (run_update lo toglie da sys.modules)."""
    name = "cordis_loader_under_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / "cordis_loader.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


@pytest.fixture(scope="session")
def export_format(new_data_dir):
    """'legacy' (project.json, organization.json, ...) o 'records' (un file per progetto)."""
    return _loader().detect_format(str(new_data_dir))


@pytest.fixture(scope="session")
def export_projects(new_data_dir, export_format, cols):
    """Progetti dell'export configurato, letti come li legge update_db.py."""
    return _loader().load_projects(str(new_data_dir), cols)


@pytest.fixture(scope="session")
def export_orgs(new_data_dir, export_format, cols):
    return _loader().load_organizations(str(new_data_dir), cols)


@pytest.fixture(scope="session")
def export_weblinks(new_data_dir, export_format):
    return _loader().load_weblinks(str(new_data_dir))


@pytest.fixture(scope="session")
def record_files(new_data_dir, export_format):
    """projectID -> file del progetto, per un export nel formato records (vuoto per legacy)."""
    if export_format != "records":
        return {}
    files = {}
    for path in sorted(new_data_dir.glob(_loader().RECORD_PATTERN)):
        with open(path, encoding="utf-8") as f:
            files[int(json.load(f)["id"])] = path
    return files


@pytest.fixture(scope="session")
def real_db():
    if not (REAL_DATA / "projects_uncase.lance").exists():
        pytest.skip(f"database LanceDB non trovato in {REAL_DATA}")
    return connect(REAL_DATA)


@pytest.fixture(scope="session")
def real_project_ids(real_db):
    tbl = real_db.open_table("projects_uncase")
    return set(scan(tbl, ["projectID"]).column("projectID").to_pylist())


@pytest.fixture(scope="session")
def unloaded_projects(export_projects, real_project_ids):
    """Progetti dell'export non ancora nel db, nell'ordine in cui li seleziona update_db.py."""
    return export_projects[~export_projects["projectID"].isin(real_project_ids)]


@pytest.fixture(scope="session")
def aligned_new_projects(unloaded_projects, export_projects, real_bge, real_specter):
    """Progetti dell'export che hanno sia l'embedding bge-m3 sia quello Specter2 precalcolati
    (gli embedding sono legati al projectID). Senza embedding precalcolati sono i progetti
    non ancora nel db."""
    if real_bge is None or real_specter is None:
        return unloaded_projects
    both = set(real_bge.ids) & set(real_specter.ids)
    return export_projects[export_projects["projectID"].isin(both)]


@dataclass
class Embeddings:
    """Embedding letti da un parquet (projectID, vector)."""
    ids: list
    vectors: "np.ndarray"

    def for_ids(self, ids):
        row = {pid: i for i, pid in enumerate(self.ids)}
        return self.vectors[[row[pid] for pid in ids]]


def read_embeddings(path):
    import pyarrow.parquet as pq
    table = pq.read_table(path, columns=["projectID", "vector"])
    return Embeddings(ids=table.column("projectID").to_pylist(),
                      vectors=np.array(table.column("vector").to_pylist(), dtype="float32"))


def write_embeddings(path, ids, vectors):
    import pyarrow as pa
    import pyarrow.parquet as pq
    vectors = np.asarray(vectors, dtype="float32")
    pq.write_table(pa.table({
        "projectID": pa.array(ids, pa.int32()),
        "vector": pa.FixedSizeListArray.from_arrays(pa.array(vectors.ravel()), vectors.shape[1]),
    }), path)


def _load_embeddings(real_cfg, key):
    path = resolve(real_cfg["paths"][key])
    if path is None or not path.exists() or path.suffix != ".parquet":
        return None
    return read_embeddings(path)


@pytest.fixture(scope="session")
def real_bge(real_cfg):
    return _load_embeddings(real_cfg, "bge_embedding_file")


@pytest.fixture(scope="session")
def real_specter(real_cfg):
    return _load_embeddings(real_cfg, "specter2_embedding_file")


# ==============================================================================
# 0.4 SANDBOX (copia ridotta di data/ e del batch dell'export, vedi la docstring)
# ==============================================================================
@dataclass
class Sandbox:
    root: Path
    fmt: str                # formato del batch: 'legacy' o 'records'
    new_ids: list           # progetti nuovi, nell'ordine atteso da update_db (per projectID)
    new_projects: "pd.DataFrame"  # i loro campi (projectID, title, objective, fp, acronym)
    dup_ids: list           # progetti già nel db (con participants) reinseriti nei nuovi dati
    old_ids: list           # progetti già presenti nel db della sandbox
    vector_dim: int
    columns: dict
    real_embeddings: bool   # True se gli embedding sono quelli reali dei progetti

    @property
    def data(self):
        return self.root / "data"

    @property
    def du(self):
        return self.root / "data_update"

    @property
    def batch_dir(self):
        return self.du / "new_data" / "batch"

    @property
    def bge(self):
        return self.du / "new_data" / "bge.parquet"

    @property
    def specter(self):
        return self.du / "new_data" / "specter.parquet"

    def bge_vectors(self):
        """Embedding bge-m3 dei progetti nuovi, nell'ordine di new_ids."""
        return read_embeddings(self.bge).for_ids(self.new_ids)

    def specter_vectors(self):
        return read_embeddings(self.specter).for_ids(self.new_ids)

    @property
    def store(self):
        return self.data / "specter2.parquet"

    @property
    def org_json(self):
        return self.data / "organisations.json"

    @property
    def graph_dir(self):
        return self.data / "project_graphs"

    def db(self):
        return connect(self.data)

    def table(self, name):
        return self.db().open_table(name)

    def df(self, name):
        # to_pandas semplice, come la dashboard: deve funzionare anche con righe vecchie e nuove
        return self.table(name).to_pandas()

    def new_orgs(self):
        """Organizzazioni del batch, lette come le legge update_db (nomi di colonna standard)."""
        return _loader().load_organizations(str(self.batch_dir), self.columns)

    def append_project(self, **project):
        """Aggiunge un progetto al batch (campi: projectID, title, objective, fp, acronym)."""
        if self.fmt == "legacy":
            _append_json(self.batch_dir / "project.json", [to_legacy(project, PROJECT_KEYS, self.columns)])
        else:
            write_record(self.batch_dir, project)

    def append_org(self, **org):
        """Aggiunge una partecipazione al batch (campi: vedi ORG_KEYS)."""
        if self.fmt == "legacy":
            _append_json(self.batch_dir / "organization.json", [to_legacy(org, ORG_KEYS, self.columns)])
            return
        self._edit_record(org["projectID"], lambda assoc: assoc.append(org_association(org)))

    def _record_path(self, project_id):
        for path in self.batch_dir.glob(_loader().RECORD_PATTERN):
            if json.loads(path.read_text(encoding="utf-8"))["id"] == str(project_id):
                return path
        return None

    def _edit_record(self, project_id, edit):
        """Applica edit(associations) al record del progetto nel batch (formato records)."""
        path = self._record_path(project_id)
        if path is None:
            raise AssertionError(f"progetto {project_id} non trovato nel batch")
        record = json.loads(path.read_text(encoding="utf-8"))
        edit(record["relations"].setdefault("associations", []))
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def _ensure_record(self, projectID):
        """Un progetto già nel db ma assente dal batch viene aggiunto al batch, come
        nell'export reale."""
        if self._record_path(projectID) is None:
            row = self.df("projects_uncase").set_index("projectID").loc[projectID]
            write_record(self.batch_dir, {"projectID": projectID, "title": row["title"],
                                          "objective": row["objective"], "fp": "HORIZON",
                                          "acronym": row["acronym"]})

    def append_publication(self, projectID, id, title, authors, doi=None):
        """Aggiunge una pubblicazione al batch (solo formato records); authors è il testo
        del campo <authors>."""
        assert self.fmt == "records", "le pubblicazioni ci sono solo nel formato records"
        self._ensure_record(projectID)
        self._edit_record(projectID, lambda assoc: assoc.append(
            publication_association({"id": id, "title": title, "authors": authors, "doi": doi})))

    def export_publications(self):
        return _loader().load_publications(str(self.batch_dir))

    def append_deliverable(self, projectID, id, title, physUrl):
        """Aggiunge un deliverable al batch (solo formato records). Un progetto già nel db
        ma assente dal batch viene aggiunto al batch, come nell'export reale."""
        assert self.fmt == "records", "i deliverables ci sono solo nel formato records"
        self._ensure_record(projectID)
        self._edit_record(projectID, lambda assoc: assoc.append(
            deliverable_association({"id": id, "title": title, "physUrl": physUrl})))

    def edit_deliverable(self, projectID, id, **fields):
        """Cambia title / physUrl di un deliverable del batch."""
        def edit(assoc):
            for a in assoc:
                if a.get("contenttype") == "result" and a.get("id") == id:
                    new = deliverable_association({"id": id, "title": a.get("title"),
                                                   "physUrl": next((l["physUrl"] for l in a["relations"]["associations"]
                                                                    if l.get("contenttype") == "webLink"), None),
                                                   **fields})
                    a.clear()
                    a.update(new)
                    return
            raise AssertionError(f"deliverable {id} non trovato")
        self._edit_record(projectID, edit)

    def remove_deliverable(self, projectID, id):
        self._edit_record(projectID, lambda assoc: assoc.remove(
            next(a for a in assoc if a.get("contenttype") == "result" and a.get("id") == id)))

    def export_deliverables(self):
        return _loader().load_deliverables(str(self.batch_dir))


# nomi standard (quelli restituiti da cordis_loader) -> chiavi di [columns] in settings.config
PROJECT_KEYS = {"projectID": "proj_id", "title": "proj_title", "objective": "proj_objective",
                "fp": "proj_fp", "acronym": "proj_acronym"}
ORG_KEYS = {"organisationID": "org_id", "name": "org_name", "countryCode": "org_country_code",
            "activityType": "org_activity_type", "role": "org_role",
            "netEcContribution": "org_proj_ec_contribution", "projectID": "org_proj_id"}


def _native(v):
    """Valore pronto per json.dump: NaN -> None, numpy -> tipi Python."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, np.generic):
        v = v.item()
        return None if isinstance(v, float) and np.isnan(v) else v
    return v


def to_legacy(row, keys, columns):
    """Riga con nomi standard -> record del vecchio formato (nomi di colonna del config)."""
    return {columns[k]: _native(row.get(std)) for std, k in keys.items()}


def _append_json(path, rows):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    path.write_text(json.dumps(data + rows, ensure_ascii=False), encoding="utf-8")


def org_association(org):
    """Partecipazione come association 'organization' di un record del formato nuovo."""
    ec = _native(org.get("netEcContribution"))
    item = {
        "contenttype": "organization",
        "id": str(org["organisationID"]),
        "legalName": _native(org.get("name")),
        "attributes": {"type": _native(org.get("role")),
                       "netEcContribution": "" if ec is None else str(ec)},
    }
    if _native(org.get("countryCode")) is not None:
        item["address"] = {"country": org["countryCode"]}
    if _native(org.get("activityType")):
        item["relations"] = {"categories": [{
            "code": "/" + org["activityType"],
            "attributes": {"classification": "organizationActivityType",
                           "type": "relatedOrganizationActivityType"}}]}
    return item


def deliverable_association(d):
    """Deliverable (id, title, physUrl o None) come association 'result' di un record del
    formato nuovo, con il webLink del pdf annidato."""
    links = [] if d.get("physUrl") is None else [
        {"contenttype": "webLink", "id": f"link-{d['id']}", "physUrl": d["physUrl"],
         "attributes": {"type": "projectDeliverable"}}]
    return {
        "contenttype": "result", "id": d["id"], "title": d.get("title"),
        "relations": {
            "categories": [{"code": "/deliverable", "attributes": {"classification": "collection"}}],
            "associations": links},
        "attributes": {"type": "relatedResult"}}


def publication_association(p, collection="/publication"):
    """Pubblicazione (id, title, authors, doi o None) come association 'result' di un record
    del formato nuovo: autori in 'details' (frammento xml), doi in 'identifiers'."""
    item = {
        "contenttype": "result", "id": p["id"], "title": p.get("title"),
        "details": f"\r\n    <authors>{p.get('authors', '')}</authors>\r\n    <publishedYear>2024</publishedYear>\r\n  ",
        "relations": {"categories": [{"code": collection, "attributes": {"classification": "collection"}}]},
        "attributes": {"type": "relatedResult"}}
    if p.get("doi"):
        item["identifiers"] = {"doi": p["doi"]}
    return item


def make_record(project, orgs=(), weblinks=(), deliverables=()):
    """Record sintetico del formato nuovo (un file per progetto), con la stessa struttura
    annidata dei file reali per i campi letti da cordis_loader."""
    pid = _native(project.get("projectID"))
    associations = [{"contenttype": "programme", "frameworkProgramme": _native(project.get("fp")),
                     "attributes": {"type": "relatedLegalBasis"}}]
    associations += [org_association(o) for o in orgs]
    for w in weblinks:
        associations.append({
            "contenttype": "result",
            "relations": {
                "categories": [{"code": "/deliverable", "attributes": {"classification": "collection"}}],
                "associations": [{"contenttype": "webLink", "id": w["id"], "physUrl": w["physUrl"],
                                  "attributes": {"type": w["type"]}}]},
            "attributes": {"type": "relatedResult"}})
    associations += [deliverable_association(d) for d in deliverables]
    return {
        "contenttype": "project", "language": "en",
        "id": None if pid is None else str(pid),
        "title": _native(project.get("title")),
        "objective": _native(project.get("objective")),
        "acronym": _native(project.get("acronym")),
        "relations": {"associations": associations},
    }


def write_record(folder, project, orgs=(), weblinks=(), deliverables=()):
    path = Path(folder) / f"project-rcn-test{project['projectID']}_en.json"
    path.write_text(json.dumps(make_record(project, orgs, weblinks, deliverables), ensure_ascii=False),
                    encoding="utf-8")
    return path


_DEFAULT_PATHS = {
    "folder": "new_data/batch",
    "bge": "new_data/bge.parquet",
    "specter": "new_data/specter.parquet",
    "deliverables": "",
    "publications": "",
    "threshold": "0.92",
    "min_cluster_size": "5",
    "review": "new_data/topic_review.xlsx",
    "bonus": "0.02",
    "bonus_existing": "-0.005",
}


def write_config(sb, path=None, **overrides):
    """Scrive settings.config della sandbox. overrides: folder, bge, specter, deliverables,
    threshold, min_cluster_size, review."""
    p = {**_DEFAULT_PATHS, **overrides}
    cfg = ConfigParser()
    cfg["paths"] = {
        "new_data_folder_name": p["folder"],
        "bge_embedding_file": p["bge"],
        "specter2_embedding_file": p["specter"],
        "deliverables_file": p["deliverables"],
        "deliverables_env_path": ".env",
        "publications_file": p["publications"],
    }
    cfg["topics"] = {
        "similarity_threshold": p["threshold"],
        "min_cluster_size": p["min_cluster_size"],
        "review_file": p["review"],
        "reviewed_topic_bonus": p["bonus"],
        "reviewed_topic_bonus_existing": p["bonus_existing"],
    }
    cfg["columns"] = sb.columns
    path = path or sb.du / "settings.config"
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return path


def build_sandbox(root, n_new, fmt, real_db, real_cfg, aligned_new, export_projects, export_orgs,
                  record_files, real_bge, real_specter):
    """fmt: formato del batch scritto nella sandbox ('legacy' o 'records'), indipendente da
    quello dell'export configurato. Nel formato records i progetti nuovi sono copie dei file
    reali quando l'export è in quel formato, altrimenti record sintetici."""
    pytest.importorskip("stopwordsiso")
    cols = dict(real_cfg["columns"])
    data = root / "data"
    du = root / "data_update"
    batch = du / "new_data" / "batch"
    batch.mkdir(parents=True)
    data.mkdir(exist_ok=True)

    # --- db ridotto con lo schema reale
    sdb = connect(data)
    old = real_db.open_table("projects_uncase").head(N_OLD)
    sdb.create_table("projects_uncase", data=old)
    old_ids = old.column("projectID").to_pylist()
    old_parts = old.column("participants").to_pylist()
    dup_ids = [pid for pid, p in zip(old_ids, old_parts) if p][:N_DUP]
    vector_dim = old.schema.field("vector").type.list_size

    in_old = f"projectID IN ({ids_sql(old_ids)})"
    for name in ("participants", "deliverables"):
        t = real_db.open_table(name)
        sub = scan(t, where=in_old)
        if sub.num_rows == 0:
            sub = t.head(50)
        sdb.create_table(name, data=sub)
    sdb.create_table("publications", data=real_db.open_table("publications").head(20))

    for f in ("organisations.json", "topic2hier.json"):
        shutil.copy2(REAL_DATA / f, data / f)
    (data / "project_graphs").mkdir()
    # copia (non symlink): la revisione dei topic riscrive il modello
    if (REAL_DATA / "old_topic_model").exists():
        shutil.copytree(REAL_DATA / "old_topic_model", data / "old_topic_model")

    for f in PIPELINE_FILES:
        shutil.copy2(HERE / f, du / f)

    # --- archivio Specter2 dei progetti del db: righe reali se c'è, altrimenti casuali
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    store = pq.read_table(REAL_DATA / "specter2.parquet") if (REAL_DATA / "specter2.parquet").exists() else None
    if store is not None and set(old_ids) <= set(store.column("projectID").to_pylist()):
        store = store.filter(pc.is_in(store.column("projectID"), pa.array(old_ids, pa.int32())))
        pq.write_table(store, data / "specter2.parquet")
    else:
        rng = np.random.default_rng(7)
        fake = rng.normal(size=(len(old_ids), 768)).astype("float32")
        pq.write_table(pa.table({"projectID": pa.array(old_ids, pa.int32()),
                                 "vector": pa.FixedSizeListArray.from_arrays(pa.array(fake.ravel()), 768)}),
                       data / "specter2.parquet")

    # --- selezione dei nuovi progetti
    old_set = set(old_ids)
    is_int = lambda v: isinstance(v, (int, np.integer)) and not isinstance(v, bool)
    real_embeddings = (
        real_bge is not None and real_specter is not None
        and real_bge.vectors.shape[1] == vector_dim
        and (~aligned_new["projectID"].isin(old_set)).any()
    )
    candidates = aligned_new if real_embeddings else export_projects
    new_projects = candidates[candidates["projectID"].map(is_int) & ~candidates["projectID"].isin(old_set)]
    # in ordine di projectID: è l'ordine in cui update_db li aggiunge con entrambi i formati
    new_projects = new_projects.head(n_new).sort_values("projectID").reset_index(drop=True)
    if new_projects.empty:
        pytest.skip("nessun progetto nuovo disponibile per la sandbox")
    new_ids = [int(p) for p in new_projects["projectID"]]
    new_projects["projectID"] = new_ids
    if real_embeddings:
        bge = real_bge.for_ids(new_ids)
        specter = real_specter.for_ids(new_ids)
    else:
        # embedding reali non disponibili: si usano vettori casuali
        rng = np.random.default_rng(42)
        bge = rng.normal(size=(len(new_ids), vector_dim)).astype("float32")
        bge /= np.linalg.norm(bge, axis=1, keepdims=True)
        spec_dim = real_specter.vectors.shape[1] if real_specter is not None else 768
        specter = rng.normal(size=(len(new_ids), spec_dim)).astype("float32")

    # progetti già esistenti reinseriti (devono essere scartati da update_db)
    old_rows = {r["projectID"]: r for r in old.select(["projectID", "title", "objective", "acronym"]).to_pylist()}
    dup_projects = [{"projectID": pid, "title": old_rows[pid]["title"], "objective": old_rows[pid]["objective"],
                     "fp": "HORIZON", "acronym": old_rows[pid]["acronym"]} for pid in dup_ids]

    orgs = export_orgs[export_orgs["projectID"].isin(new_ids)]
    # organizzazioni fittizie per progetti che hanno già participants: non vanno reinserite
    dup_orgs = [{**orgs.iloc[0].to_dict(), "projectID": pid} for pid in dup_ids] if len(orgs) else []

    # organizzazioni "mai viste": si tolgono dal dizionario della sandbox quelle dei primi
    # progetti nuovi, così update_db deve formattarne il nome (step 2.2)
    unseen = {str(int(o)) for o in orgs.loc[orgs["projectID"].isin(new_ids[:10]), "organisationID"]}
    with open(data / "organisations.json", encoding="utf-8") as f:
        org_dict = json.load(f)
    with open(data / "organisations.json", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in org_dict.items() if k not in unseen}, f, ensure_ascii=False, indent=2)

    if fmt == "legacy":
        project_json = []
        rows = new_projects.to_dict("records")
        for i, rec in enumerate(rows):
            if i % 10 == 0 and dup_projects:
                project_json.append(dup_projects.pop())
            project_json.append(rec)
        project_json.extend(dup_projects)
        _append_json(batch / "project.json", [to_legacy(r, PROJECT_KEYS, cols) for r in project_json])
        _append_json(batch / "organization.json",
                     [to_legacy(r, ORG_KEYS, cols) for r in orgs.to_dict("records") + dup_orgs])
    else:
        by_project = {pid: g.to_dict("records") for pid, g in orgs.groupby("projectID")}
        for rec in new_projects.to_dict("records"):
            src = record_files.get(rec["projectID"])
            if src is not None:
                shutil.copy2(src, batch / src.name)
            else:
                write_record(batch, rec, by_project.get(rec["projectID"], []))
        for rec in dup_projects:
            write_record(batch, rec, [o for o in dup_orgs if o["projectID"] == rec["projectID"]])

    # embedding salvati in ordine inverso: update_db deve leggerli per projectID, non per posizione
    write_embeddings(du / "new_data" / "bge.parquet", new_ids[::-1], bge[::-1])
    write_embeddings(du / "new_data" / "specter.parquet", new_ids[::-1], specter[::-1])

    sb = Sandbox(root=root, fmt=fmt, new_ids=new_ids, new_projects=new_projects, dup_ids=dup_ids,
                 old_ids=old_ids, vector_dim=vector_dim, columns=cols,
                 real_embeddings=real_embeddings)
    write_config(sb)
    return sb


SANDBOX_FORMATS = ["legacy", "records"]


@pytest.fixture(scope="session", params=SANDBOX_FORMATS)
def pristine_sandbox(request, tmp_path_factory, real_db, real_cfg, aligned_new_projects, export_projects,
                     export_orgs, record_files, real_bge, real_specter):
    """Sandbox con il batch in uno dei due formati: i test d'integrazione girano con entrambi."""
    return build_sandbox(tmp_path_factory.mktemp(f"pristine_{request.param}"), N_NEW, request.param,
                         real_db, real_cfg, aligned_new_projects, export_projects, export_orgs,
                         record_files, real_bge, real_specter)


@pytest.fixture(scope="session")
def pristine_sandbox_slow(tmp_path_factory, real_db, real_cfg, aligned_new_projects, export_projects,
                          export_orgs, record_files, real_bge, real_specter):
    return build_sandbox(tmp_path_factory.mktemp("pristine_slow"), N_NEW_SLOW, "records", real_db, real_cfg,
                         aligned_new_projects, export_projects, export_orgs, record_files,
                         real_bge, real_specter)


def _copy_sandbox(src, dst):
    shutil.copytree(src.root, dst, symlinks=True)
    return replace(src, root=dst)


@pytest.fixture
def sandbox(pristine_sandbox, tmp_path):
    return _copy_sandbox(pristine_sandbox, tmp_path / "sb")


# ==============================================================================
# 0.5 ESECUZIONE DI update_db.py CON MODELLI FAKE
# ==============================================================================
class FakeModels:
    """Sostituti deterministici di extract_embedding / extract_topic."""

    def __init__(self, sb, topic_error=None, moves=None):
        self.bge_calls = []
        self.topic_calls = []
        self.review_calls = []
        self.topic_error = topic_error
        with open(sb.data / "topic2hier.json", encoding="utf-8") as f:
            self.topic2hier = json.load(f)
        self.topic_keys = sorted(self.topic2hier, key=int)
        dim = sb.vector_dim

        emb = types.ModuleType("extract_embedding")

        def extract_bgem3(df):
            self.bge_calls.append(df.copy())
            v = np.random.default_rng(0).normal(size=(len(df), dim)).astype("float32")
            return v / np.linalg.norm(v, axis=1, keepdims=True)

        def extract_specter2(df, batch_size=32):
            raise AssertionError("extract_specter2 non dovrebbe essere chiamato dai fake")

        emb.extract_bgem3 = extract_bgem3
        emb.extract_specter2 = extract_specter2
        self.embedding_module = emb

        top = types.ModuleType("extract_topic")

        def assign_topics(new_df, specter_embs=None, **kwargs):
            embs = None if specter_embs is None else np.asarray(specter_embs)
            self.topic_calls.append({
                "df": new_df.copy(),
                "embs": embs,
                "embs_shape": None if embs is None else embs.shape,
                "kwargs": kwargs,
            })
            if self.topic_error == "ReviewAborted":
                # stessa classe che update_db importa dalla copia di topic_review nella sandbox
                raise sys.modules["topic_review"].ReviewAborted("revisione annullata")
            if self.topic_error == "KeyboardInterrupt":
                raise KeyboardInterrupt
            hier = [self.expected_hierarchy(i) for i in range(len(new_df))]
            topics = pd.DataFrame({
                "projectID": new_df["projectID"].values,
                "topic_name": [first_labelled(h) for h in hier],
                "topic_name_hierarchy": hier,
            })
            if embs is None:
                embs = np.random.default_rng(1).normal(size=(len(new_df), 768)).astype("float32")
            return SimpleNamespace(topics=topics, embeddings=embs)

        def apply_review_sheet(db, sheet_path, store_path, **kwargs):
            self.review_calls.append({"sheet_path": sheet_path, "store_path": store_path, "kwargs": kwargs})
            if self.topic_error == "ReviewAborted":
                raise sys.modules["topic_review"].ReviewAborted("foglio non valido")
            if self.topic_error == "KeyboardInterrupt":
                raise KeyboardInterrupt
            return self.moves if self.moves is not None else pd.DataFrame(columns=["projectID"])

        top.assign_topics = assign_topics
        top.apply_review_sheet = apply_review_sheet
        top.first_labelled = first_labelled
        self.topic_module = top
        self.moves = moves

    def expected_hierarchy(self, i):
        return np.array(self.topic2hier[self.topic_keys[i % len(self.topic_keys)]])


@dataclass
class RunResult:
    code: int
    fakes: FakeModels | None


@pytest.fixture
def run_update(monkeypatch):
    def _run(sb, *flags, config=None, fake_models=True, topic_error=None, moves=None):
        fakes = FakeModels(sb, topic_error, moves) if fake_models else None
        with monkeypatch.context() as m:
            m.chdir(sb.du)
            m.syspath_prepend(str(sb.du))
            for name in PIPELINE_MODULES:
                m.delitem(sys.modules, name, raising=False)
            if fakes:
                m.setitem(sys.modules, "extract_embedding", fakes.embedding_module)
                m.setitem(sys.modules, "extract_topic", fakes.topic_module)
            argv = ["update_db.py", *flags]
            if config is not None:
                argv += ["--config", str(config)]
            m.setattr(sys, "argv", argv)
            try:
                runpy.run_path(str(sb.du / "update_db.py"), run_name="__main__")
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            finally:
                for name in PIPELINE_MODULES:
                    sys.modules.pop(name, None)
        return RunResult(code, fakes)

    return _run


@pytest.fixture
def sb_with_projects(sandbox, run_update):
    res = run_update(sandbox, "--projects")
    assert res.code == 0, "lo step --projects deve completarsi prima di testare --participants"
    return sandbox


# ==============================================================================
# 1. DATI REALI: CONFIGURAZIONE, EXPORT, FILE PRECALCOLATI E STATO DEL DB
#
# Leggono settings.config, new_data/ e data/ così come sono, senza scrivere nulla.
# Un fallimento qui non è un bug del codice: dati o configurazione non sono nello stato
# richiesto dalla documentazione. Il messaggio dice cosa fare.
# ==============================================================================
class TestConfig:
    def test_config_has_required_keys(self, real_cfg):
        for section, keys in REQUIRED_CONFIG.items():
            assert section in real_cfg, f"sezione [{section}] mancante"
            for k in keys:
                assert k in real_cfg[section], f"chiave {section}.{k} mancante"

    def test_new_data_folder_exists(self, real_cfg):
        rel = real_cfg["paths"]["new_data_folder_name"]
        assert rel, "new_data_folder_name è vuoto"
        assert resolve(rel).is_dir(), f"la cartella {resolve(rel)} non esiste"

    def test_topic_settings_valid(self, real_cfg):
        t = real_cfg["topics"]
        assert 0 < t.getfloat("similarity_threshold") < 1
        assert t.getint("min_cluster_size") >= 2
        review = resolve(t["review_file"])
        assert review.suffix == ".xlsx" and review.parent.is_dir()
        assert 0 <= t.getfloat("reviewed_topic_bonus") < 0.1

    @pytest.mark.parametrize("key", ["bge_embedding_file", "specter2_embedding_file", "deliverables_file"])
    def test_configured_files_exist(self, real_cfg, key):
        rel = real_cfg["paths"][key]
        if not rel:
            pytest.skip(f"{key} non configurato (verrà calcolato dalla pipeline)")
        hint = {"bge_embedding_file": "python compute_embeddings.py --model bge --source new",
                "specter2_embedding_file": "python compute_embeddings.py --model specter2 --source new",
                "deliverables_file": "python extract_deliverables.py"}[key]
        assert resolve(rel).exists(), (f"{key}: {resolve(rel)} non esiste. Crearlo con '{hint}' oppure "
                                       "lasciare vuoto il parametro in settings.config "
                                       "(docs/03-aggiornamento-dati/eseguire-update-db.md, P3-P4)")


class TestNewDataInputs:
    """Controlli sull'export configurato, letto con cordis_loader come in update_db.py:
    valgono per entrambi i formati."""

    def test_format_recognised(self, export_format):
        assert export_format in ("legacy", "records")

    @pytest.mark.parametrize("name", ["project.json", "organization.json", "webLink.json"])
    def test_legacy_files_exist(self, new_data_dir, export_format, name):
        if export_format != "legacy":
            pytest.skip("export nel formato con un file per progetto")
        assert (new_data_dir / name).exists()

    def test_project_ids_are_unique_integers(self, export_projects):
        ids = export_projects["projectID"]
        assert pd.api.types.is_integer_dtype(ids), f"projectID non interi (dtype {ids.dtype})"
        assert not ids.duplicated().any(), "projectID duplicati"

    def test_project_titles_not_empty(self, export_projects):
        titles = export_projects["title"]
        assert titles.notna().all() and (titles.astype(str).str.strip() != "").all()

    def test_framework_programmes_are_mapped(self, export_projects):
        fp_dict = read_fp_dict()
        unknown = set(export_projects["fp"].dropna().unique()) - set(fp_dict)
        assert not unknown, f"programmi non presenti in FP_DICT (diventerebbero NaN): {unknown}"
        assert export_projects["fp"].notna().all(), "progetti senza framework programme"

    def test_org_ids_are_integers(self, export_orgs):
        ids = pd.to_numeric(export_orgs["organisationID"], errors="coerce")
        assert ids.notna().all(), "organisationID non convertibili a int"

    def test_org_project_ids_reference_projects(self, export_orgs, export_projects):
        missing = set(export_orgs["projectID"]) - set(export_projects["projectID"])
        assert not missing, f"{len(missing)} partecipazioni di progetti assenti dall'export"

    def test_org_names_not_empty(self, export_orgs):
        names = export_orgs["name"]
        assert names.notna().all() and (names.astype(str).str.strip() != "").all()

    def test_roles_known(self, export_orgs):
        unknown = set(export_orgs["role"].dropna()) - {"coordinator", "participant", "associatedPartner",
                                                        "thirdParty"}
        assert not unknown, f"ruoli inattesi: {unknown}"

    def test_activity_types_are_codes(self, export_orgs):
        act = export_orgs["activityType"].dropna().astype(str)
        act = act[act != ""]
        bad = act[~act.str.fullmatch(r"[A-Z]{3}")]
        assert bad.empty, f"activityType anomali (es. con lo slash del formato nuovo): {sorted(bad.unique())[:10]}"

    def test_country_codes_format(self, export_orgs):
        # update_db separa i paesi multipli ("DE;HU") in una riga per paese
        cc = export_orgs["countryCode"].dropna().astype(str).str.split(";").explode().str.strip()
        cc = cc[cc != ""]
        bad = cc[~cc.str.fullmatch(r"[A-Z]{2}")]
        assert bad.empty, f"country code anomali: {sorted(bad.unique())[:10]}"

    def test_ec_contribution_is_numeric(self, export_orgs):
        raw = export_orgs["netEcContribution"]
        non_empty = raw[raw.notna() & (raw.astype(str).str.strip() != "")]
        coerced = pd.to_numeric(non_empty, errors="coerce")
        bad = non_empty[coerced.isna()]
        assert bad.empty, f"netEcContribution non numerici (verrebbero persi): {bad.unique()[:10]}"

    def test_weblinks_have_deliverables(self, export_weblinks):
        assert {"type", "physUrl", "projectID"} <= set(export_weblinks.columns)
        deliverables = export_weblinks[export_weblinks["type"] == "projectDeliverable"]
        assert not deliverables.empty
        assert deliverables["physUrl"].notna().all()

    def test_export_deliverables(self, new_data_dir, export_format, export_projects):
        if export_format != "records":
            pytest.skip("il vecchio export non ha i titoli dei deliverables")
        d = _loader().load_deliverables(str(new_data_dir))
        assert not d.empty
        assert pd.api.types.is_integer_dtype(d["projectID"]), "update_db si fermerebbe"
        assert not d["id"].duplicated().any()
        assert (d["title"].fillna("").str.strip() != "").all(), "deliverables senza titolo"
        assert set(d["projectID"]) <= set(export_projects["projectID"])
        urls = d["physUrl"].dropna()
        assert not urls.duplicated().any()
        assert d["physUrl"].notna().mean() > 0.9

    def test_there_are_new_projects(self, unloaded_projects):
        """Serve prima di un aggiornamento: senza progetti nuovi update_db.py si ferma."""
        if unloaded_projects.empty:
            pytest.skip("l'export configurato è già tutto nel db (normale dopo un aggiornamento): "
                        "update_db.py senza flag si fermerebbe con 'There are no new projects'. "
                        "Per un nuovo aggiornamento scaricare un export più recente e aggiornare "
                        "new_data_folder_name (docs/03-aggiornamento-dati/eseguire-update-db.md, P2)")


class TestPrecomputedArtifacts:
    @pytest.mark.parametrize("which", ["bge", "specter"])
    def test_embeddings_cover_new_projects(self, real_bge, real_specter, unloaded_projects, which):
        """Ogni progetto che update_db aggiungerà ha il suo embedding (altrimenti si ferma)."""
        emb = real_bge if which == "bge" else real_specter
        if emb is None:
            pytest.skip("embedding precalcolati non configurati")
        have = set(emb.ids)
        missing = [p for p in unloaded_projects["projectID"] if p not in have]
        assert not missing, (f"{which}: {len(missing)} progetti nuovi senza embedding, es. {missing[:5]}. "
                             "Gli embedding sono stati calcolati su un altro export o con --limit: rifarli "
                             "con compute_embeddings.py --source new (eseguire-update-db.md, P4)")

    @pytest.mark.parametrize("which", ["bge", "specter"])
    def test_embedding_ids_unique(self, real_bge, real_specter, which):
        emb = real_bge if which == "bge" else real_specter
        if emb is None:
            pytest.skip("embedding precalcolati non configurati")
        assert len(emb.ids) == len(set(emb.ids))

    def test_bge_dim_matches_db(self, real_bge, real_db):
        if real_bge is None:
            pytest.skip("bge non configurato")
        dim = real_db.open_table("projects_uncase").schema.field("vector").type.list_size
        assert real_bge.vectors.ndim == 2 and real_bge.vectors.shape[1] == dim

    def test_specter_dim(self, real_specter):
        if real_specter is None:
            pytest.skip("specter non configurato")
        assert real_specter.vectors.ndim == 2 and real_specter.vectors.shape[1] == 768

    @pytest.mark.parametrize("which", ["bge", "specter"])
    def test_embeddings_are_finite(self, real_bge, real_specter, which):
        arr = real_bge if which == "bge" else real_specter
        if arr is None:
            pytest.skip("embedding non configurati")
        assert np.isfinite(arr.vectors).all()
        assert (np.linalg.norm(arr.vectors, axis=1) > 0).all(), "embedding nulli"

    def test_deliverables_file_format(self, real_cfg):
        """deliverables_file deve essere l'output di extract_deliverables.py: update_db.py
        controlla le stesse cose e si ferma senza scrivere."""
        path = resolve(real_cfg["paths"]["deliverables_file"])
        if path is None:
            pytest.skip("deliverables_file non configurato: lo step 3 usa l'export")
        df = pd.read_parquet(path)
        hint = ("deliverables_file deve essere scritto da extract_deliverables.py "
                "(docs/03-aggiornamento-dati/eseguire-update-db.md, P3)")
        assert DELIVERABLES_REQUIRED <= set(df.columns), \
            f"mancano le colonne {sorted(DELIVERABLES_REQUIRED - set(df.columns))}: {hint}"
        assert df["id"].notna().all() and not df["id"].duplicated().any(), f"id nulli o ripetuti: {hint}"
        assert pd.api.types.is_integer_dtype(df["projectID"]), f"projectID non interi: {hint}"
        for a in df["authors"].dropna():
            assert isinstance(json.loads(a), dict), f"authors non è un JSON {{nome: affiliazione}}: {a[:80]}"

    def test_deliverables_file_complete(self, real_cfg):
        """Righe pending/error: update_db.py prosegue, ma quei deliverables restano senza autori."""
        path = resolve(real_cfg["paths"]["deliverables_file"])
        if path is None:
            pytest.skip("deliverables_file non configurato: lo step 3 usa l'export")
        df = pd.read_parquet(path)
        if "status" not in df.columns:
            pytest.skip("il file non ha la colonna status")
        todo = int(df["status"].isin(["pending", "error"]).sum())
        assert not todo, (f"{todo} deliverables ancora senza autori (status pending/error): rilanciare "
                          "python extract_deliverables.py, che riprova solo quelli")

    def test_topic2hier_is_consistent(self):
        path = REAL_DATA / "topic2hier.json"
        if not path.exists():
            pytest.skip("topic2hier.json non trovato")
        with open(path, encoding="utf-8") as f:
            t2h = json.load(f)
        assert t2h
        for k, v in t2h.items():
            int(k)
            assert isinstance(v, list) and v and all(isinstance(x, str) for x in v)

    def test_every_model_topic_in_hierarchy(self):
        """Un topic del modello senza voce in topic2hier.json lascerebbe i suoi progetti senza nome."""
        bertopic = pytest.importorskip("bertopic")
        model_dir, hier_path = REAL_DATA / "old_topic_model", REAL_DATA / "topic2hier.json"
        if not model_dir.exists() or not hier_path.exists():
            pytest.skip("old_topic_model o topic2hier.json non trovati")
        model = bertopic.BERTopic.load(str(model_dir))
        with open(hier_path, encoding="utf-8") as f:
            hier_ids = {int(k) for k in json.load(f)}
        missing = set(model.topic_representations_) - hier_ids
        assert not missing, (f"topic del modello assenti da topic2hier.json: {sorted(missing)}. Probabile "
                             "--review interrotto: ripristinare modello e gerarchia da data/backups/ "
                             "(eseguire-update-db.md, D1 'Tornare indietro')")
        reviewed_path = model_dir / "reviewed_topics.json"
        if reviewed_path.exists():
            assert set(json.loads(reviewed_path.read_text())) <= hier_ids

    def test_specter_store_covers_db(self, real_db):
        """Ogni progetto del db deve avere il suo embedding Specter2, altrimenti non può
        passare a un topic nuovo (update_db aggiunge quelli dei progetti nuovi)."""
        pq = pytest.importorskip("pyarrow.parquet")
        path = REAL_DATA / "specter2.parquet"
        if not path.exists():
            pytest.skip("data/specter2.parquet non trovato")
        table = pq.read_table(path)
        ids = table.column("projectID").to_numpy()
        db_ids = scan(real_db.open_table("projects_uncase"), ["projectID"]).column("projectID").to_numpy()
        assert len(set(ids)) == len(ids), "projectID duplicati nell'archivio"
        missing = set(db_ids.tolist()) - set(ids.tolist())
        assert not missing, (f"{len(missing)} progetti del db senza embedding, es. {sorted(missing)[:5]}: "
                             "non potranno passare a topic nuovi. Ricostruire l'archivio con "
                             "python compute_embeddings.py --model specter2 --source db "
                             "(review-topic.md, 2.11)")
        vectors = table.column("vector").combine_chunks().flatten().to_numpy().reshape(len(ids), -1)
        assert np.isfinite(vectors).all() and (np.linalg.norm(vectors, axis=1) > 0).all()

    def test_organisations_json_keys_are_int(self):
        path = REAL_DATA / "organisations.json"
        if not path.exists():
            pytest.skip("organisations.json non trovato")
        with open(path, encoding="utf-8") as f:
            orgs = json.load(f)
        for k, v in orgs.items():
            int(k)
            assert isinstance(v, str)


def _find_exports():
    """Ultima cartella di ciascun formato in new_data/ (per il confronto tra formati)."""
    found = {}
    root = HERE / "new_data"
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        try:
            found[_loader().detect_format(str(d))] = d
        except _loader().CordisFormatError:
            pass
    return found


@pytest.fixture(scope="session")
def pair(real_cfg):
    """Ultimo export di ciascun formato in new_data/, letti dal loader: (legacy, records,
    projectID in comune)."""
    exports = _find_exports()
    if {"legacy", "records"} - set(exports):
        pytest.skip(f"servono un export per formato in new_data/ (trovati: {sorted(exports)})")
    cols = dict(real_cfg["columns"])
    loader = _loader()
    out = {}
    for fmt, d in exports.items():
        out[fmt] = SimpleNamespace(projects=loader.load_projects(str(d), cols),
                                   orgs=loader.load_organizations(str(d), cols))
    common = set(out["legacy"].projects["projectID"]) & set(out["records"].projects["projectID"])
    assert len(common) > 1000, "gli export dovrebbero avere in comune quasi tutti i progetti"
    return out["legacy"], out["records"], common


class TestExportsAgree:
    """Gli export reali nei due formati, letti dal loader, descrivono gli stessi progetti.
    Le differenze ammesse sono gli aggiornamenti di CORDIS tra un export e l'altro
    (objective emendati, contributi rivisti, partner aggiunti o tolti)."""

    def test_project_fields(self, pair):
        old, new, common = pair
        m = old.projects[old.projects["projectID"].isin(common)].merge(
            new.projects, on="projectID", suffixes=("_o", "_n"))
        assert (m["fp_o"] == m["fp_n"]).all()
        for col, min_share in (("title", 0.99), ("acronym", 0.99), ("objective", 0.9)):
            share = (m[f"{col}_o"].fillna("") == m[f"{col}_n"].fillna("")).mean()
            assert share >= min_share, f"{col}: solo {share:.1%} uguali"

    def test_participations(self, pair):
        old, new, common = pair
        key = ["projectID", "organisationID", "role"]
        a = old.orgs[old.orgs["projectID"].isin(common)]
        b = new.orgs[new.orgs["projectID"].isin(common)]
        m = a.merge(b, on=key, how="outer", suffixes=("_o", "_n"), indicator=True)
        both = m[m["_merge"] == "both"]
        assert len(both) / len(a) >= 0.97, "partecipazioni del vecchio export non ritrovate"
        for col, min_share in (("countryCode", 0.995), ("activityType", 0.99)):
            share = (both[f"{col}_o"].fillna("").astype(str) == both[f"{col}_n"].fillna("").astype(str)).mean()
            assert share >= min_share, f"{col}: solo {share:.1%} uguali"
        ec_o = pd.to_numeric(both["netEcContribution_o"], errors="coerce").fillna(0)
        ec_n = both["netEcContribution_n"].fillna(0)
        assert ((ec_o - ec_n).abs() <= 1).mean() >= 0.9


# nomi di topic diversi da quelli di topic2hier.json, noti e da lasciare come sono
# (CLAUDE.md, "Projects already in the db and new topics"): (topic_name, nome nella gerarchia)
KNOWN_NAME_DRIFT = {("Molecular Biology", "RNA Biology")}


@pytest.fixture(scope="session")
def real_projects(real_db):
    tbl = real_db.open_table("projects_uncase")
    return scan(tbl, ["projectID", "topic_name", "topic_name_hierarchy", "fp", "n_deliverables",
                      "n_publications"]).to_pandas()


def _rows_per_project(db, table):
    return scan(db.open_table(table), ["projectID"]).to_pandas().groupby("projectID").size()


class TestRealDbState:
    """Lo stato di data/ che la dashboard e la pipeline si aspettano (docs/01-panoramica/
    struttura-dati.md). Sola lettura."""

    REPAIR = "eseguire python lance_maintenance.py --data ../data (struttura-dati.md, 'Due regole che la dashboard richiede')"

    def test_no_vector_index_on_projects(self, real_db):
        """Con un indice IVF_PQ le distanze sono approssimate e la ricerca libera torna vuota."""
        tbl = real_db.open_table("projects_uncase")
        vector = [i.name for i in tbl.list_indices() if i.index_type.lower().startswith(("ivf", "hnsw"))]
        assert not vector, f"indice vettoriale su projects_uncase ({vector}): {self.REPAIR}"

    @pytest.mark.parametrize("table", ["projects_uncase", "participants"])
    def test_no_dictionary_columns(self, real_db, table):
        """Le colonne dictionary fanno fallire to_pandas() sulle righe aggiunte dopo."""
        pa = pytest.importorskip("pyarrow")
        cols = [f.name for f in real_db.open_table(table).schema if pa.types.is_dictionary(f.type)]
        assert not cols, f"{table}: colonne dictionary {cols}: {self.REPAIR}"

    def test_project_ids_unique(self, real_projects):
        dup = real_projects["projectID"][real_projects["projectID"].duplicated()]
        assert dup.empty, f"projectID ripetuti in projects_uncase: {sorted(dup.unique())[:10]}"

    def test_n_deliverables_matches_rows(self, real_db, real_projects):
        """La dashboard mostra n_deliverables: deve essere il numero di righe in deliverables."""
        counts = _rows_per_project(real_db, "deliverables")
        n = real_projects.set_index("projectID")["n_deliverables"]
        bad = n[n != counts.reindex(n.index).fillna(0)]
        assert bad.empty, (f"{len(bad)} progetti con n_deliverables diverso dalle righe di deliverables, "
                           f"es. {bad.index[:5].tolist()}. Lo step 3 riallinea i progetti dell'export: "
                           "python update_db.py --deliverables (struttura-dati.md, 'Deliverables')")
        orphans = set(counts.index) - set(n.index)
        assert not orphans, f"deliverables di progetti assenti da projects_uncase: {sorted(orphans)[:10]}"

    def test_n_publications_matches_rows(self, real_db, real_projects):
        """n_publications = righe in publications; con n_publications 0 e righe presenti lo
        step 4 salterebbe il progetto."""
        counts = _rows_per_project(real_db, "publications")
        n = real_projects.set_index("projectID")["n_publications"]
        bad = n[n != counts.reindex(n.index).fillna(0)]
        assert bad.empty, (f"{len(bad)} progetti con n_publications diverso dalle righe di publications, "
                           f"es. {bad.index[:5].tolist()} (struttura-dati.md, 'Publications (step 4)')")

    def test_participants_copy_project_fields(self, real_db, real_projects):
        """fp e topic sono copiati in participants: un cambio di topic va scritto in entrambe."""
        parts = scan(real_db.open_table("participants"), ["projectID", "topic_name", "fp"]).to_pandas()
        m = parts.merge(real_projects[["projectID", "topic_name", "fp"]], on="projectID",
                        how="left", suffixes=("", "_project"))
        orphans = m["topic_name_project"].isna()
        assert not orphans.any(), f"participants di progetti assenti: {sorted(m.loc[orphans, 'projectID'].unique())[:10]}"
        bad = m[(m["topic_name"] != m["topic_name_project"]) | (m["fp"] != m["fp_project"])]
        assert bad.empty, (f"{bad['projectID'].nunique()} progetti con topic o fp diversi tra projects_uncase "
                           f"e participants, es. {sorted(bad['projectID'].unique())[:5]}. Se è stata "
                           "ripristinata una sola tabella, ripristinare anche l'altra alla versione del "
                           "log reassign (eseguire-update-db.md, D1 'Tornare indietro')")

    def test_topic_name_matches_hierarchy(self, real_projects):
        """topic_name è il primo nome non Unlabelled di topic_name_hierarchy (salvo KNOWN_NAME_DRIFT)."""
        h = real_projects["topic_name_hierarchy"]
        assert (h.map(len) == 4).all(), "topic_name_hierarchy deve avere 4 livelli"
        pairs = set(zip(real_projects["topic_name"], h.map(first_labelled)))
        bad = {(a, b) for a, b in pairs if a != b} - KNOWN_NAME_DRIFT
        assert not bad, f"topic_name diverso dalla gerarchia (topic_name, gerarchia): {sorted(bad)[:10]}"

    def test_hierarchies_exist_in_topic2hier(self, real_projects):
        path = REAL_DATA / "topic2hier.json"
        if not path.exists():
            pytest.skip("topic2hier.json non trovato")
        paths = {tuple(v) for v in json.loads(path.read_text(encoding="utf-8")).values()}
        bad = real_projects[~real_projects["topic_name_hierarchy"].map(tuple).isin(paths)]
        assert bad.empty, (f"{len(bad)} progetti con un percorso assente da topic2hier.json, es. "
                           f"{bad['projectID'].head().tolist()}: modello/gerarchia e tabelle non "
                           "allineati (ripristino in eseguire-update-db.md, D1)")

    def test_every_topic_has_a_graph(self, real_projects):
        """Il tab Project graph legge data/project_graphs/; li rigenerano lo step 2 e --review."""
        index = REAL_DATA / "project_graphs" / "_index.json"
        if not index.exists():
            pytest.skip("data/project_graphs/_index.json non trovato")
        missing = set(real_projects["topic_name"]) - set(json.loads(index.read_text(encoding="utf-8")))
        assert not missing, (f"topic senza grafo: {sorted(missing)[:10]}. Rigenerare i grafi con "
                             "python update_db.py --participants o ripristinarli da data/backups/ "
                             "(struttura-dati.md, 'Grafi in data/project_graphs/')")

    def test_concept_map_coordinates_cover_store(self):
        """Ogni progetto di specter2.parquet ha le sue coordinate sulla mappa di Concept."""
        pq = pytest.importorskip("pyarrow.parquet")
        store, coords = REAL_DATA / "specter2.parquet", REAL_DATA / "umap_2d.parquet"
        if not store.exists() or not coords.exists():
            pytest.skip("specter2.parquet o umap_2d.parquet non trovati")
        missing = (set(pq.read_table(store, columns=["projectID"]).column("projectID").to_pylist())
                   - set(pq.read_table(coords, columns=["projectID"]).column("projectID").to_pylist()))
        assert not missing, (f"{len(missing)} progetti senza coordinate: python "
                             "generate_datamapplot_representation.py (struttura-dati.md, 'Mappa dei progetti')")

    def test_treemap_counts_projects(self, real_projects):
        """assets/treemap.json conta i progetti di projects_uncase (la rigenera lo step 1)."""
        treemap, hier = HERE.parent / "assets" / "treemap.json", REAL_DATA / "topic2hier.json"
        if not treemap.exists() or not hier.exists():
            pytest.skip("treemap.json o topic2hier.json non trovati")
        trace = json.loads(treemap.read_text(encoding="utf-8"))["data"][0]
        paths = {tuple(p) for p in json.loads(hier.read_text(encoding="utf-8")).values()}
        labelled = sum(1 for p in real_projects["topic_name_hierarchy"]
                       if any(n != "Unlabelled" for n in p) and tuple(p) in paths)
        roots = sum(v for v, parent in zip(trace["values"], trace["parents"]) if parent == "")
        assert roots == labelled, (f"la treemap conta {roots} progetti, il db {labelled}: "
                                   "python generate_treemap.py (pagina-concept.md, 'Treemap')")

    @pytest.mark.parametrize("table", ["deliverables", "publications"])
    def test_authors_are_json_objects(self, real_db, table):
        """La dashboard legge authors come JSON {nome: affiliazione}."""
        bad = [a for a in scan(real_db.open_table(table), ["authors"]).column("authors").to_pylist()
               if a is None or not isinstance(json.loads(a), dict)]
        assert not bad, f"{table}: {len(bad)} valori di authors non validi, es. {bad[:3]}"


# ==============================================================================
# 2. UNIT TEST: un modulo della pipeline per sottosezione, su dati piccoli scritti dai test
#
# 2.1 cordis_loader.py (i due formati dell'export CORDIS)
# ==============================================================================
LEGACY_COLUMNS = {"proj_id": "id", "proj_title": "title", "proj_objective": "objective",
                  "proj_fp": "frameworkProgramme", "proj_acronym": "acronym",
                  "org_id": "organisationID", "org_name": "name", "org_country_code": "country",
                  "org_activity_type": "activityType", "org_role": "role",
                  "org_proj_ec_contribution": "netEcContribution", "org_proj_id": "projectID"}

ORG_A = {"organisationID": 999000001, "name": "ALPHA UNIVERSITY", "countryCode": "IT",
         "activityType": "HES", "role": "coordinator", "netEcContribution": 1000.5, "projectID": 101}
ORG_B = {"organisationID": 999000002, "name": "BETA SRL", "countryCode": "DE",
         "activityType": "PRC", "role": "participant", "netEcContribution": None, "projectID": 101}
WEBLINK = {"id": "w1", "physUrl": "https://example.org/d1.pdf", "type": "projectDeliverable"}
DELIV_A = {"id": "101_1_DELIVHORIZON", "title": "Data Management Plan", "physUrl": "https://example.org/a.pdf"}
DELIV_NO_LINK = {"id": "101_2_DELIVHORIZON", "title": "Final report", "physUrl": None}
PUB_A = {"id": "101_10_PUBLIHORIZON", "title": "On computable numbers",
         "authors": "Ada Lovelace; Alan Turing", "doi": "10.1000/xyz"}
PUB_NO_DOI = {"id": "101_11_PUBLIHORIZON", "title": "Notes", "authors": "", "doi": None}


def _project(pid, **kw):
    return {"projectID": pid, "title": f"Title {pid}", "objective": f"Objective {pid}",
            "fp": "HORIZON", "acronym": f"ACR{pid}", **kw}


class TestCordisLoader:
    @pytest.fixture
    def records_dir(self, tmp_path):
        d = tmp_path / "records"
        d.mkdir()
        write_record(d, _project(102))
        write_record(d, _project(101), orgs=[ORG_A, ORG_B], weblinks=[WEBLINK])
        return d

    @pytest.fixture
    def legacy_dir(self, tmp_path):
        d = tmp_path / "legacy"
        d.mkdir()
        _append_json(d / "project.json", [to_legacy(_project(p), PROJECT_KEYS, LEGACY_COLUMNS) for p in (102, 101)])
        _append_json(d / "organization.json", [to_legacy(o, ORG_KEYS, LEGACY_COLUMNS) for o in (ORG_A, ORG_B)])
        _append_json(d / "webLink.json", [{**WEBLINK, "projectID": 101, "status": ""}])
        return d

    def test_detect_format(self, records_dir, legacy_dir, tmp_path):
        loader = _loader()
        assert loader.detect_format(str(records_dir)) == "records"
        assert loader.detect_format(str(legacy_dir)) == "legacy"
        (tmp_path / "empty").mkdir()
        with pytest.raises(loader.CordisFormatError, match="neither"):
            loader.detect_format(str(tmp_path / "empty"))
        with pytest.raises(loader.CordisFormatError, match="not found"):
            loader.detect_format(str(tmp_path / "missing"))
        shutil.copy2(legacy_dir / "project.json", records_dir / "project.json")
        with pytest.raises(loader.CordisFormatError, match="both"):
            loader.detect_format(str(records_dir))

    def test_records_projects(self, records_dir):
        df = _loader().load_projects(str(records_dir), {})
        assert list(df.columns) == ["projectID", "title", "objective", "fp", "acronym"]
        assert df["projectID"].tolist() == [101, 102], "ordinati per projectID"
        assert pd.api.types.is_integer_dtype(df["projectID"])
        assert df["fp"].tolist() == ["HORIZON", "HORIZON"], "fp dai programmi collegati"
        assert df.loc[0, "title"] == "Title 101" and df.loc[0, "acronym"] == "ACR101"

    def test_fp_prefers_legal_basis(self, tmp_path):
        rec = make_record(_project(5, fp=None))
        rec["relations"]["associations"] = [
            {"contenttype": "programme", "frameworkProgramme": "H2020", "attributes": {"type": "relatedTopic"}},
            {"contenttype": "programme", "frameworkProgramme": "HORIZON", "attributes": {"type": "relatedLegalBasis"}},
        ]
        (tmp_path / "project-rcn-5_en.json").write_text(json.dumps(rec))
        assert _loader().load_projects(str(tmp_path), {})["fp"].tolist() == ["HORIZON"]

    def test_records_organizations(self, records_dir):
        df = _loader().load_organizations(str(records_dir), {})
        assert list(df.columns) == ["organisationID", "name", "countryCode", "activityType", "role",
                                    "netEcContribution", "projectID"]
        a, b = df.sort_values("organisationID").to_dict("records")
        assert a == {**ORG_A}
        assert b["activityType"] == "PRC", "codice senza lo slash del formato nuovo"
        assert pd.isna(b["netEcContribution"]), "contributo vuoto -> NaN"
        assert pd.api.types.is_integer_dtype(df["organisationID"]) and pd.api.types.is_integer_dtype(df["projectID"])

    def test_org_without_address_or_activity(self, tmp_path):
        org = {**ORG_A, "countryCode": None, "activityType": None}
        write_record(tmp_path, _project(101), orgs=[org])
        row = _loader().load_organizations(str(tmp_path), {}).iloc[0]
        assert row["countryCode"] is None and row["activityType"] is None

    def test_records_weblinks(self, records_dir):
        df = _loader().load_weblinks(str(records_dir))
        assert df.to_dict("records") == [{"id": "w1", "projectID": 101, "physUrl": WEBLINK["physUrl"],
                                          "type": "projectDeliverable"}]

    def test_records_deliverables(self, tmp_path):
        rec = make_record(_project(101), deliverables=[DELIV_A, DELIV_NO_LINK])
        # una pubblicazione con un webLink non è un deliverable
        rec["relations"]["associations"].append({
            "contenttype": "result", "id": "101_9_PUBLIHORIZON", "title": "A paper",
            "relations": {"categories": [{"code": "/publication", "attributes": {"classification": "collection"}}],
                          "associations": [{"contenttype": "webLink", "physUrl": "https://example.org/p",
                                            "attributes": {"type": "projectDeliverable"}}]}})
        (tmp_path / "project-rcn-101_en.json").write_text(json.dumps(rec))
        write_record(tmp_path, _project(102))
        df = _loader().load_deliverables(str(tmp_path))
        assert list(df.columns) == ["id", "projectID", "title", "physUrl"]
        assert pd.api.types.is_integer_dtype(df["projectID"])
        assert df.to_dict("records") == [{**DELIV_A, "projectID": 101}, {**DELIV_NO_LINK, "projectID": 101}]

    def test_deliverables_ignore_other_weblinks(self, tmp_path):
        rec = make_record(_project(101), deliverables=[DELIV_A])
        rec["relations"]["associations"][-1]["relations"]["associations"].insert(0, {
            "contenttype": "webLink", "physUrl": "https://example.org/site",
            "attributes": {"type": "relatedWebsite"}})
        (tmp_path / "project-rcn-101_en.json").write_text(json.dumps(rec))
        assert _loader().load_deliverables(str(tmp_path))["physUrl"].tolist() == [DELIV_A["physUrl"]]

    def test_duplicate_deliverable_rejected(self, tmp_path):
        write_record(tmp_path, _project(101), deliverables=[DELIV_A])
        write_record(tmp_path, _project(102), deliverables=[DELIV_A])
        with pytest.raises(_loader().CordisFormatError, match="more than one project"):
            _loader().load_deliverables(str(tmp_path))

    def test_records_publications(self, tmp_path):
        rec = make_record(_project(101), deliverables=[DELIV_A])
        rec["relations"]["associations"] += [
            publication_association(PUB_A), publication_association(PUB_NO_DOI),
            publication_association({"id": "101_3_PUBLIHORIZON", "title": "Summary"}, "/pubsum"),
            publication_association({"id": "101_4_IPR", "title": "A patent"}, "/ipr")]
        (tmp_path / "project-rcn-101_en.json").write_text(json.dumps(rec))
        write_record(tmp_path, _project(102))
        df = _loader().load_publications(str(tmp_path))
        assert list(df.columns) == ["id", "projectID", "title", "authors", "physUrl"]
        assert pd.api.types.is_integer_dtype(df["projectID"])
        assert df["id"].tolist() == [PUB_A["id"], PUB_NO_DOI["id"]], "solo la collection /publication"
        assert df["physUrl"].tolist() == ["https://doi.org/10.1000/xyz", None]
        assert json.loads(df.loc[0, "authors"]) == {"Ada Lovelace": "Unknown", "Alan Turing": "Unknown"}
        assert df.loc[1, "authors"] == "{}", "senza autori il JSON è vuoto, come in deliverables"

    @pytest.mark.parametrize("text, names", [
        ("Ada Lovelace, Alan Turing and Grace Hopper", ["Ada Lovelace", "Alan Turing", "Grace Hopper"]),
        ("Lovelace, Ada; Turing, Alan", ["Lovelace, Ada", "Turing, Alan"]),
        ('"Knox EG, Aburto MR#, Cryan JF#"', ["Knox EG", "Aburto MR", "Cryan JF"]),
        ("Ada Lovelace &amp; Alan Turing", ["Ada Lovelace", "Alan Turing"]),
        ("Ada Lovelace, Ada Lovelace", ["Ada Lovelace"]),
        ("", []),
        (None, []),
    ])
    def test_split_authors(self, text, names):
        assert _loader()._split_authors(text) == names

    def test_duplicate_publication_rejected(self, tmp_path):
        for pid in (101, 102):
            rec = make_record(_project(pid))
            rec["relations"]["associations"].append(publication_association(PUB_A))
            (tmp_path / f"project-rcn-{pid}_en.json").write_text(json.dumps(rec))
        with pytest.raises(_loader().CordisFormatError, match="more than one project"):
            _loader().load_publications(str(tmp_path))

    def test_legacy_has_no_publications(self, legacy_dir):
        with pytest.raises(_loader().CordisFormatError, match="old-format"):
            _loader().load_publications(str(legacy_dir))

    def test_legacy_has_no_deliverables(self, legacy_dir):
        with pytest.raises(_loader().CordisFormatError, match="old-format"):
            _loader().load_deliverables(str(legacy_dir))

    def test_same_frames_from_both_formats(self, records_dir, legacy_dir):
        loader = _loader()
        for fn in ("load_projects", "load_organizations"):
            r = getattr(loader, fn)(str(records_dir), LEGACY_COLUMNS)
            l = getattr(loader, fn)(str(legacy_dir), LEGACY_COLUMNS)
            key = list(r.columns)[0]
            r, l = r.sort_values(key).reset_index(drop=True), l.sort_values(key).reset_index(drop=True)
            assert list(r.columns) == list(l.columns), fn
            for col in r.columns:
                assert [_native(v) for v in r[col]] == [_native(v) for v in l[col]], (fn, col)
        r = loader.load_weblinks(str(records_dir))
        l = loader.load_weblinks(str(legacy_dir))
        assert r.to_dict("records") == l.to_dict("records")

    def test_duplicate_project_rejected(self, records_dir):
        rec = make_record(_project(101))
        (records_dir / "project-rcn-other_en.json").write_text(json.dumps(rec))
        with pytest.raises(_loader().CordisFormatError, match="more than one file"):
            _loader().load_projects(str(records_dir), {})

    def test_non_project_record_rejected(self, records_dir):
        (records_dir / "project-rcn-x_en.json").write_text(json.dumps({"contenttype": "result", "id": "1"}))
        with pytest.raises(_loader().CordisFormatError, match="not a project"):
            _loader().load_projects(str(records_dir), {})

    def test_non_numeric_id_leaves_float_column(self, records_dir):
        write_record(records_dir, _project("abc"))
        df = _loader().load_projects(str(records_dir), {})
        assert not pd.api.types.is_integer_dtype(df["projectID"]), "update_db controlla il dtype e si ferma"

    def test_legacy_requires_columns_section(self, legacy_dir):
        with pytest.raises(_loader().CordisFormatError, match="columns"):
            _loader().load_projects(str(legacy_dir), {})


# ==============================================================================
# 2.2 UNIT TEST: format_name.py
# ==============================================================================
@pytest.fixture
def format_name_mod(monkeypatch):
    return load_module(monkeypatch, "format_name", HERE / "format_name.py")


class TestFormatName:
    SW = {"di", "degli", "of", "the", "and", "de", "la"}

    def fmt(self, mod, text):
        return call_format_name(mod.format_name, text, self.SW)

    def test_title_case_with_stopwords(self, format_name_mod):
        assert self.fmt(format_name_mod, "UNIVERSITA DEGLI STUDI DI TRENTO") == "Universita degli Studi di Trento"

    def test_first_word_always_capitalized(self, format_name_mod):
        assert self.fmt(format_name_mod, "THE UNIVERSITY OF OXFORD") == "The University of Oxford"

    def test_quotes_removed(self, format_name_mod):
        assert self.fmt(format_name_mod, 'FONDAZIONE "BRUNO KESSLER"') == "Fondazione Bruno Kessler"
        assert self.fmt(format_name_mod, "«FONDAZIONE» KESSLER") == "Fondazione Kessler"

    def test_apostrophe_removed(self, format_name_mod):
        assert self.fmt(format_name_mod, "AGENCE DE L'ENERGIE") == "Agence de Lenergie"

    def test_whitespace_normalized(self, format_name_mod):
        assert self.fmt(format_name_mod, "  fbk   trento \n") == "Fbk Trento"

    @pytest.mark.parametrize("text", ["", "   ", '""'])
    def test_empty(self, format_name_mod, text):
        assert self.fmt(format_name_mod, text) == ""

    def test_idempotent(self, format_name_mod):
        once = self.fmt(format_name_mod, "ISTITUTO NAZIONALE DI FISICA NUCLEARE")
        assert self.fmt(format_name_mod, once) == once

    def test_compatible_with_update_db_call(self, format_name_mod):
        """update_db.py chiama format_name tramite Series.apply: la firma deve essere compatibile."""
        tree = ast.parse((HERE / "update_db.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "apply" and n.args
                 and isinstance(n.args[0], ast.Name) and n.args[0].id == "format_name"]
        assert calls, "update_db.py non usa più .apply(format_name)"
        required = [p for p in inspect.signature(format_name_mod.format_name).parameters.values()
                    if p.default is inspect.Parameter.empty]
        for call in calls:
            extra = len(call.args) - 1 + len(call.keywords)
            assert len(required) <= 1 + extra, (
                f"format_name richiede {len(required)} argomenti ma update_db.py "
                f"(riga {call.lineno}) gliene passa {1 + extra}")


# ==============================================================================
# 2.3 UNIT TEST: create_projgraph.py
# ==============================================================================
@pytest.fixture
def projgraph_mod(monkeypatch):
    return load_module(monkeypatch, "create_projgraph", HERE / "create_projgraph.py")


def _read_graphs(out_dir):
    with open(out_dir / "_index.json", encoding="utf-8") as f:
        index = json.load(f)
    graphs = {}
    for topic, fname in index.items():
        with open(out_dir / fname, encoding="utf-8") as f:
            graphs[topic] = json.load(f)
    return index, graphs


def _edge_pairs(graph):
    return {(e["source"], e["target"]) for e in graph["edges"]}


class TestCreateProjectGraph:
    @pytest.mark.parametrize("name,expected", [
        ("Aero Engineering", "Aero_Engineering"),
        ("Africa-EU Cooperation", "Africa-EU_Cooperation"),
        ("a/b?c", "a_b_c"),
        ("  ", "unnamed_topic"),
        ("v1.2", "v1.2"),
    ])
    def test_slugify(self, projgraph_mod, name, expected):
        assert projgraph_mod.slugify(name) == expected

    def test_edges_from_shared_participants(self, projgraph_mod, tmp_path):
        df = pd.DataFrame({
            "projectID": [1, 2, 3],
            "title": ["P1", "P2", "P3"],
            "topic_name": ["A", "A", "A"],
            "participants": [["o1", "o2"], ["o2", "o3", "o1"], ["o4"]],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        index, graphs = _read_graphs(tmp_path)
        assert index == {"A": "A.json"}
        g = graphs["A"]
        assert g["topic_name"] == "A"
        assert g["nodes"] == {"1": {"title": "P1"}, "2": {"title": "P2"}, "3": {"title": "P3"}}
        assert g["edges"] == [{"source": 1, "target": 2, "weight": 2, "collaborators": ["o1", "o2"]}]

    def test_topics_are_separated(self, projgraph_mod, tmp_path):
        df = pd.DataFrame({
            "projectID": [1, 2],
            "title": ["P1", "P2"],
            "topic_name": ["A", "B"],
            "participants": [["o1"], ["o1"]],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        _, graphs = _read_graphs(tmp_path)
        assert set(graphs) == {"A", "B"}
        assert graphs["A"]["edges"] == [] and graphs["B"]["edges"] == []

    def test_slug_collisions_get_distinct_files(self, projgraph_mod, tmp_path):
        df = pd.DataFrame({
            "projectID": [1, 2],
            "title": ["P1", "P2"],
            "topic_name": ["B/x", "B x"],
            "participants": [[], []],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        index, graphs = _read_graphs(tmp_path)
        assert len(set(index.values())) == 2
        assert set(index.values()) == {"B_x.json", "B_x_.json"}
        assert graphs["B/x"]["nodes"] == {"1": {"title": "P1"}}
        assert graphs["B x"]["nodes"] == {"2": {"title": "P2"}}

    def test_projects_without_participants(self, projgraph_mod, tmp_path):
        df = pd.DataFrame({
            "projectID": [1, 2],
            "title": ["P1", "P2"],
            "topic_name": ["A", "A"],
            "participants": [[], []],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        _, graphs = _read_graphs(tmp_path)
        assert set(graphs["A"]["nodes"]) == {"1", "2"}
        assert graphs["A"]["edges"] == []

    def test_min_shared_collaborators(self, projgraph_mod, tmp_path, monkeypatch):
        monkeypatch.setattr(projgraph_mod, "MIN_SHARED_COLLABORATORS", 2)
        df = pd.DataFrame({
            "projectID": [1, 2, 3],
            "title": ["P1", "P2", "P3"],
            "topic_name": ["A"] * 3,
            "participants": [["o1", "o2"], ["o1", "o2"], ["o1"]],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        _, graphs = _read_graphs(tmp_path)
        assert _edge_pairs(graphs["A"]) == {(1, 2)}

    def test_top_k_neighbors(self, projgraph_mod, tmp_path, monkeypatch):
        monkeypatch.setattr(projgraph_mod, "TOP_K_NEIGHBORS", 1)
        df = pd.DataFrame({
            "projectID": [1, 2, 3],
            "title": ["P1", "P2", "P3"],
            "topic_name": ["A"] * 3,
            "participants": [["o1", "o2", "o3"], ["o1", "o2"], ["o3", "o4"]],
        })
        # archi: (1,2,w=2), (1,3,w=1); 2 e 3 non condividono nulla
        projgraph_mod.create_project_graph(df, str(tmp_path))
        _, graphs = _read_graphs(tmp_path)
        assert _edge_pairs(graphs["A"]) == {(1, 2), (1, 3)}

    def test_categorical_unused_categories_are_skipped(self, projgraph_mod, tmp_path):
        df = pd.DataFrame({
            "projectID": [1],
            "title": ["P1"],
            "topic_name": pd.Categorical(["A"], categories=["A", "Unused"]),
            "participants": [["o1"]],
        })
        projgraph_mod.create_project_graph(df, str(tmp_path))
        index, _ = _read_graphs(tmp_path)
        assert set(index) == {"A"}

    def test_output_dir_created(self, projgraph_mod, tmp_path):
        out = tmp_path / "nested" / "graphs"
        df = pd.DataFrame({"projectID": [1], "title": ["P1"], "topic_name": ["A"], "participants": [[]]})
        projgraph_mod.create_project_graph(df, str(out))
        assert (out / "_index.json").exists()


# ==============================================================================
# 2.4 UNIT TEST: generate_treemap.py
# ==============================================================================
@pytest.fixture
def treemap_mod(monkeypatch):
    return load_module(monkeypatch, "generate_treemap", HERE / "generate_treemap.py")


TREEMAP_HIER = {
    "-1": ["Unlabelled", "Unlabelled", "Unlabelled", "Unlabelled"],
    "0": ["Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"],
    "1": ["Unlabelled", "Unlabelled", "Botany", "Earth & Life Science"],
    "2": ["Wireless", "Telecom", "Computer Engineering", "Engineering & Technology"],
    "3": ["Unlabelled", "Unlabelled", "Unused Topic", "Engineering & Technology"],
}


def _treemap_nodes(fig):
    t = fig.data[0]
    return {i: (l, p, v) for i, l, p, v in zip(t.ids, t.labels, t.parents, t.values)}


class TestGenerateTreemap:
    def test_tree_and_values(self, treemap_mod):
        paths = [TREEMAP_HIER[k] for k in ("0", "0", "1", "2", "-1")]
        nodes = _treemap_nodes(treemap_mod.generate_treemap(TREEMAP_HIER, paths))
        assert nodes == {
            "Earth & Life Science": ("Earth & Life Science", "", 3),
            "Engineering & Technology": ("Engineering & Technology", "", 1),
            "Earth & Life Science/Climatology": ("Climatology", "Earth & Life Science", 2),
            "Earth & Life Science/Botany": ("Botany", "Earth & Life Science", 1),
            "Engineering & Technology/Computer Engineering":
                ("Computer Engineering", "Engineering & Technology", 1),
            "Earth & Life Science/Climatology/Climate Modelling":
                ("Climate Modelling", "Earth & Life Science/Climatology", 2),
            "Engineering & Technology/Computer Engineering/Telecom":
                ("Telecom", "Engineering & Technology/Computer Engineering", 1),
            "Engineering & Technology/Computer Engineering/Telecom/Wireless":
                ("Wireless", "Engineering & Technology/Computer Engineering/Telecom", 1),
        }

    def test_unknown_paths_are_skipped(self, treemap_mod, capsys):
        paths = [TREEMAP_HIER["0"], ["Unlabelled", "Unlabelled", "Ghost", "Health & Medicine"]]
        nodes = _treemap_nodes(treemap_mod.generate_treemap(TREEMAP_HIER, paths))
        assert not any("Ghost" in i for i in nodes)
        assert "Ghost" in capsys.readouterr().out

    def test_colors_by_root(self, treemap_mod):
        fig = treemap_mod.generate_treemap(TREEMAP_HIER, [TREEMAP_HIER["0"], TREEMAP_HIER["2"]])
        t = fig.data[0]
        for node_id, color in zip(t.ids, t.marker.colors):
            assert color == treemap_mod.ROOT_COLORS[node_id.split("/")[0]]

    def test_real_hierarchy_covers_db(self, treemap_mod):
        """Ogni topic_name_hierarchy della db reale deve essere un percorso di topic2hier.json."""
        hier_path = REAL_DATA / "topic2hier.json"
        if not hier_path.exists() or not (REAL_DATA / "projects_uncase.lance").exists():
            pytest.skip("dati reali non trovati")
        tbl = connect(REAL_DATA).open_table("projects_uncase")
        with open(hier_path, encoding="utf-8") as f:
            hier = json.load(f)
        paths = scan(tbl, columns=["topic_name_hierarchy"]).column("topic_name_hierarchy").to_pylist()
        nodes = _treemap_nodes(treemap_mod.generate_treemap(hier, paths))
        n_labelled = sum(1 for p in paths if any(n != "Unlabelled" for n in p))
        assert sum(v for _, parent, v in nodes.values() if parent == "") == n_labelled


# ==============================================================================
# 2.5 UNIT TEST: generate_datamapplot_representation.py (modello UMAP e datamapplot finti)
# ==============================================================================
@pytest.fixture
def dmp_mod(monkeypatch):
    return load_module(monkeypatch, "generate_datamapplot_representation",
                       HERE / "generate_datamapplot_representation.py")


class _FakeUmap:
    def transform(self, X):
        return np.stack([X[:, 0], X[:, 1]], axis=1) * 10


def _dmp_data(tmp_path, dmp_mod, store_ids=(1, 2, 3, 4), coord_ids=(1, 2)):
    import pyarrow as pa
    import pyarrow.parquet as pq
    embs = np.arange(len(store_ids) * 4, dtype="float32").reshape(-1, 4)
    pq.write_table(pa.table({"projectID": pa.array(store_ids, pa.int32()),
                             "vector": pa.FixedSizeListArray.from_arrays(pa.array(embs.ravel()), 4)}),
                   tmp_path / "specter2.parquet")
    dmp_mod.write_coords(str(tmp_path / "umap_2d.parquet"), list(coord_ids),
                         np.arange(len(coord_ids) * 2, dtype="float32").reshape(-1, 2) - 100)
    (tmp_path / "umap_model.joblib").write_bytes(b"x")
    return embs


class TestDatamapplot:
    def test_only_missing_projects_are_projected(self, dmp_mod, tmp_path, monkeypatch):
        embs = _dmp_data(tmp_path, dmp_mod)
        monkeypatch.setattr(dmp_mod.joblib, "load", lambda p: _FakeUmap())
        n = dmp_mod.update_umap_coordinates(*(str(tmp_path / f) for f in
                                              ("specter2.parquet", "umap_2d.parquet", "umap_model.joblib")))
        ids, coords = dmp_mod.load_coords(str(tmp_path / "umap_2d.parquet"))
        assert n == 2 and ids.tolist() == [1, 2, 3, 4]
        assert np.allclose(coords[:2].ravel(), [-100, -99, -98, -97])      # i vecchi non si muovono
        assert np.allclose(coords[2:], embs[2:, :2] * 10)

    def test_nothing_to_do_does_not_load_model(self, dmp_mod, tmp_path, monkeypatch):
        _dmp_data(tmp_path, dmp_mod, coord_ids=(1, 2, 3, 4))
        monkeypatch.setattr(dmp_mod.joblib, "load", lambda p: pytest.fail("modello caricato"))
        assert dmp_mod.update_umap_coordinates(*(str(tmp_path / f) for f in
                                                 ("specter2.parquet", "umap_2d.parquet", "umap_model.joblib"))) == 0

    def test_missing_model_is_a_warning_not_an_error(self, dmp_mod, tmp_path, capsys):
        _dmp_data(tmp_path, dmp_mod)
        (tmp_path / "umap_model.joblib").unlink()
        dmp_mod.update_datamapplot(None, str(tmp_path), str(tmp_path / "out.html"))
        assert "WARNING: datamapplot not updated" in capsys.readouterr().out
        assert not (tmp_path / "out.html").exists()

    def test_bootstrap_keeps_numeric_ids_in_db(self, dmp_mod, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq
        _dmp_data(tmp_path, dmp_mod, store_ids=(1, 2, 3))
        pq.write_table(pa.table({"projectID": ["RI1B0234", "2", "9", "1"],
                                 "vector": pa.FixedSizeListArray.from_arrays(
                                     pa.array(np.arange(8, dtype="float32")), 2)}), tmp_path / "all.parquet")
        n, n_db = dmp_mod.bootstrap_umap_2d(str(tmp_path / "all.parquet"), str(tmp_path / "boot.parquet"),
                                            str(tmp_path / "specter2.parquet"))
        ids, coords = dmp_mod.load_coords(str(tmp_path / "boot.parquet"))
        assert (n, n_db) == (2, 3) and ids.tolist() == [2, 1]
        assert coords.tolist() == [[2.0, 3.0], [6.0, 7.0]]

    def test_plot_gets_rotated_coords_titles_and_topic_levels(self, dmp_mod, tmp_path, monkeypatch):
        import lancedb
        _dmp_data(tmp_path, dmp_mod, coord_ids=(1, 2, 3))
        hier = ["Unlabelled", "B", "C", "D"]
        tbl = lancedb.connect(str(tmp_path / "db")).create_table("p", data=pd.DataFrame({
            "projectID": [1, 2, 3, 99], "title": ["t1", "t2", "t3", "t99"],
            "topic_name_hierarchy": [hier] * 4}))
        calls = {}
        fake = MagicMock()
        fake.create_interactive_plot.side_effect = lambda data_map, *labels, **kw: calls.update(
            data_map=data_map, labels=labels, kw=kw) or MagicMock()
        monkeypatch.setitem(sys.modules, "datamapplot", fake)
        n = dmp_mod.write_datamapplot(tbl, str(tmp_path / "umap_2d.parquet"), str(tmp_path / "o" / "m.html"))
        assert n == 3                                                    # il 99 non ha coordinate
        ids, coords = dmp_mod.load_coords(str(tmp_path / "umap_2d.parquet"))
        assert np.allclose(calls["data_map"], coords @ dmp_mod.ROTATION.T)
        assert len(calls["labels"]) == 4 and list(calls["labels"][1]) == ["B"] * 3
        assert calls["kw"]["hover_text"] == ["t1", "t2", "t3"]
        assert calls["kw"]["extra_point_data"]["id"].tolist() == [1, 2, 3]


# ==============================================================================
# 2.6 UNIT TEST: extract_embedding.py (modelli stubbati)
# ==============================================================================
@pytest.fixture
def embedding_mod(monkeypatch):
    stub_modules(monkeypatch, "FlagEmbedding", "adapters")
    stub_modules(monkeypatch, "torch", "transformers", only_missing=True)
    return load_module(monkeypatch, "extract_embedding", HERE / "extract_embedding.py")


class TestExtractEmbedding:
    def test_build_corpus(self, embedding_mod):
        df = pd.DataFrame({
            "title": ["  Hello   World ", None, "T", "", "A\nB"],
            "objective": ["OBJ", "only obj", None, "", "C\tD"],
        })
        assert embedding_mod.build_corpus(df) == ["hello world. obj", "only obj", "t", "", "a b. c d"]

    def test_build_corpus_custom_separator(self, embedding_mod):
        df = pd.DataFrame({"title": ["Title"], "objective": ["Objective"]})
        assert embedding_mod.build_corpus(df, sep_value="[SEP]") == ["title[SEP]objective"]

    def test_build_corpus_non_default_index(self, embedding_mod):
        df = pd.DataFrame({"title": ["A", "B"], "objective": ["x", ""]}, index=[10, 3])
        assert embedding_mod.build_corpus(df) == ["a. x", "b"]

    def test_extract_bgem3(self, embedding_mod, monkeypatch):
        seen = {}

        class FakeBGE:
            def __init__(self, name, use_fp16):
                seen["name"] = name

            def encode(self, corpus, batch_size, max_length):
                seen["corpus"] = corpus
                return {"dense_vecs": np.ones((len(corpus), 4), dtype="float32")}

        monkeypatch.setattr(embedding_mod, "BGEM3FlagModel", FakeBGE)
        df = pd.DataFrame({"title": ["A", "B"], "objective": ["x", "y"]})
        out = embedding_mod.extract_bgem3(df)
        assert seen["name"] == "BAAI/bge-m3"
        assert seen["corpus"] == embedding_mod.build_corpus(df)
        assert out.shape == (2, 4)


# ==============================================================================
# 2.7 UNIT TEST: extract_topic.py (BERTopic stubbato)
# ==============================================================================
@pytest.fixture
def topic_mod(monkeypatch):
    fake_emb = types.ModuleType("extract_embedding")
    fake_emb.extract_specter2 = MagicMock(name="extract_specter2")
    monkeypatch.setitem(sys.modules, "extract_embedding", fake_emb)
    stub_modules(monkeypatch, "bertopic", "umap", "hdbscan", "nltk", "nltk.corpus")
    stub_modules(monkeypatch, "sklearn.feature_extraction.text", only_missing=True)
    return load_module(monkeypatch, "extract_topic", HERE / "extract_topic.py")


# embedding dei topic del modello finto: riga 0 = outlier (-1), poi topic 0, 1, 2
TOPIC_EMBS = np.array([
    [0, 0, 0, 1],
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
], dtype="float32")


class FakeOldTopicModel:
    _outliers = 1

    def __init__(self, assigned):
        self.assigned = list(assigned)
        self.topic_embeddings_ = TOPIC_EMBS
        self.calls = []

    def transform(self, docs, embeddings):
        self.calls.append({"docs": docs, "embs_shape": np.asarray(embeddings).shape})
        return list(self.assigned), None


def _install_old_model(mod, monkeypatch, assigned=(), model_dir="/nonexistent/old_topic_model"):
    """Modello finto: i topic si assegnano per coseno con TOPIC_EMBS. model_dir senza
    reviewed_topics.json = nessun topic revisionato."""
    model = FakeOldTopicModel(assigned)
    loaded = []
    monkeypatch.setattr(mod, "BERTopic", SimpleNamespace(load=lambda path: loaded.append(path) or model))
    monkeypatch.setattr(mod, "OLD_TOPIC_MODEL_DIR", str(model_dir))
    model.loaded = loaded
    return model


class FakeClusterModel:
    def __init__(self, keywords):
        self.keywords = keywords

    def get_topic_info(self):
        topics = [-1] + list(self.keywords)
        return pd.DataFrame({"Topic": topics,
                             "Representation": [["outlier"]] + list(self.keywords.values())})


SMALL_HIER_T2H = {
    "-1": ["Unlabelled", "Unlabelled"],
    "0": ["Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"],
    "1": ["Wireless Networks", "Telecommunications", "Computer Engineering", "Engineering & Technology"],
    "2": ["Unlabelled", "Unlabelled"],
}


@pytest.fixture
def topic2hier_file(tmp_path):
    path = tmp_path / "topic2hier.json"
    path.write_text(json.dumps(SMALL_HIER_T2H))
    return path


def _f32(arr):
    return np.asarray(arr, dtype="float32")


def _report_of(mod, monkeypatch, df, embs, **kw):
    """Il report dei candidati che assign_topics passa alla revisione."""
    seen = {}
    monkeypatch.setattr(mod, "review_and_apply",
                        lambda ctx, *a: seen.update(report=ctx.report.copy()) or (ctx.topics, pd.DataFrame()))
    mod.assign_topics(df, embs, **kw)
    return seen["report"]


class TestExtractTopic:
    @pytest.mark.parametrize("h,expected", [
        (["Unlabelled", "A", "B"], "A"),
        (["X", "Unlabelled"], "X"),
        (["Unlabelled"], "Unlabelled"),
        ([], "Unlabelled"),
    ])
    def test_first_labelled(self, topic_mod, h, expected):
        assert topic_mod.first_labelled(h) == expected
        assert topic_mod.first_labelled(np.array(h, dtype=object)) == expected

    def _new_df(self):
        return pd.DataFrame({
            "projectID": [11, 12, 13, 14],
            "title": ["T1", None, "T3", "T4"],
            "objective": ["O1", "O2", None, "O4"],
        }, index=[5, 7, 9, 2])

    # embedding dei 4 progetti: identici al topic assegnato, tranne il terzo (similarità 0.707)
    EMBS = [[1, 0, 0, 0], [0, 1, 0, 0], [1, 1, 0, 0], [0, 0, 1, 0]]
    ASSIGNED = [0, 1, 0, 2]

    @pytest.fixture
    def setup(self, topic_mod, monkeypatch, tmp_path, topic2hier_file):
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        model = _install_old_model(topic_mod, monkeypatch, self.ASSIGNED)
        cluster = MagicMock(name="cluster_candidates")
        monkeypatch.setattr(topic_mod, "cluster_candidates", cluster)
        return SimpleNamespace(mod=topic_mod, model=model, cluster=cluster, embs=_f32(self.EMBS),
                               report_of=lambda df, embs, **kw: _report_of(topic_mod, monkeypatch, df, embs, **kw))

    def test_assign_existing_topics_is_cosine_argmax(self, topic_mod):
        model = FakeOldTopicModel([])
        topics, sim, auto = topic_mod.assign_existing_topics(model, np.array(self.EMBS, dtype="float32"))
        assert topics.tolist() == self.ASSIGNED
        assert np.allclose(sim, [1, 1, 1 / np.sqrt(2), 1])
        assert not auto.any()
        topics, sim, _ = topic_mod.assign_existing_topics(model, np.array([[0, 0, 0, 2]], dtype="float32"))
        assert topics.tolist() == [-1] and np.allclose(sim, [1])

    @staticmethod
    def _model_with_reviewed(row):
        """Modello finto con un topic 3 creato da una revisione."""
        model = FakeOldTopicModel([])
        model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [row]]).astype("float32")
        return model

    def test_reviewed_topic_never_wins_above_threshold(self, topic_mod):
        model = self._model_with_reviewed([1, 0.05, 0, 0])
        doc = np.array([[1, 0.05, 0, 0]], dtype="float32")   # identico al topic 3, ma 0.999 col topic 0
        topics, sim, auto = topic_mod.assign_existing_topics(model, doc, {3})
        assert topics.tolist() == [0] and not auto.any()
        assert sim[0] > 0.99, "la similarità restituita è quella col miglior topic originale"

    def test_reviewed_topic_wins_below_threshold(self, topic_mod):
        model = self._model_with_reviewed([1, 1, 0, 0])
        doc = np.array([[1, 1, 0, 0]], dtype="float32")      # 0.707 col topic 0: sotto soglia
        topics, sim, auto = topic_mod.assign_existing_topics(model, doc, {3})
        assert topics.tolist() == [3] and auto.tolist() == [True]
        assert sim[0] == pytest.approx(1 / np.sqrt(2), abs=1e-4)

    def test_reviewed_topic_must_be_close_enough(self, topic_mod):
        model = self._model_with_reviewed([0, 0, 1, 1])
        doc = np.array([[1, 1, 0, 0]], dtype="float32")
        topics, _, auto = topic_mod.assign_existing_topics(model, doc, {3})
        assert topics.tolist() == [0] and not auto.any()

    def test_reviewed_bonus(self, topic_mod):
        model = self._model_with_reviewed([1, 0, 0.8, 0])
        doc = np.array([[1, 1, 0, 0]], dtype="float32")
        gap = 1 / np.sqrt(2) - 1 / (np.sqrt(2) * np.sqrt(1.64))   # sim(topic 0) - sim(topic 3)
        for bonus, expected in ((gap - 0.01, 0), (gap + 0.01, 3)):
            topics, _, _ = topic_mod.assign_existing_topics(model, doc, {3}, reviewed_bonus=bonus)
            assert topics.tolist() == [expected], bonus

    def test_without_reviewed_topics_new_rows_are_ordinary(self, topic_mod):
        """Senza reviewed_topics.json il topic 3 è un topic come gli altri."""
        model = self._model_with_reviewed([1, 0.05, 0, 0])
        topics, _, _ = topic_mod.assign_existing_topics(model, np.array([[1, 0.05, 0, 0]], dtype="float32"))
        assert topics.tolist() == [3]

    def test_assign_topics_uses_reviewed_file(self, topic_mod, monkeypatch, tmp_path, capsys):
        hier = tmp_path / "h.json"
        hier.write_text(json.dumps({**SMALL_HIER_T2H, "3": ["Unlabelled", "Ocean Acidification", "Climatology",
                                                            "Earth & Life Science"]}))
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(hier))
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "reviewed_topics.json").write_text("[3]")
        model = _install_old_model(topic_mod, monkeypatch, model_dir=model_dir)
        model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [[1, 1, 0, 0]]]).astype("float32")
        seen = {}
        real_review = topic_mod.review_and_apply
        monkeypatch.setattr(topic_mod, "review_and_apply",
                            lambda ctx, *a: seen.update(report=ctx.report.copy()) or real_review(ctx, *a))
        out = topic_mod.assign_topics(self._new_df(), _f32(self.EMBS))
        assert out.topics["topic_name"].tolist() == ["Climate Modelling", "Wireless Networks",
                                              "Ocean Acidification", "Unlabelled"]
        rep = seen["report"]
        assert rep["projectID"].tolist() == [13], "resta tra i candidati anche se assegnato in automatico"
        assert rep["auto_assigned"].tolist() == [True]
        assert rep["nearest_topic"].tolist() == ["Ocean Acidification"]
        assert "assigned to topics created in previous reviews" in capsys.readouterr().out

    def test_assigns_every_project_to_existing_topics(self, setup):
        out = setup.mod.assign_topics(self._new_df(), setup.embs)
        assert setup.model.loaded == [setup.mod.OLD_TOPIC_MODEL_DIR]
        assert out.topics["projectID"].tolist() == [11, 12, 13, 14]
        assert out.topics["topic_name"].tolist() == ["Climate Modelling", "Wireless Networks",
                                              "Climate Modelling", "Unlabelled"]
        assert list(out.topics["topic_name_hierarchy"].iloc[0]) == [
            "Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"]
        assert list(out.topics.columns) == ["projectID", "topic_name", "topic_name_hierarchy"]

    def test_outlier_topic_maps_to_unlabelled(self, topic_mod, monkeypatch, tmp_path, topic2hier_file):
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        _install_old_model(topic_mod, monkeypatch, [-1])
        df = pd.DataFrame({"projectID": [1], "title": ["T"], "objective": ["O"]})
        out = topic_mod.assign_topics(df, _f32([[0, 0, 0, 1]]))
        assert out.topics["topic_name"].tolist() == ["Unlabelled"]

    def test_uses_precomputed_embeddings(self, setup):
        setup.mod.assign_topics(self._new_df(), setup.embs)
        setup.mod.extract_specter2.assert_not_called()

    def test_computes_embeddings_when_missing(self, setup, monkeypatch):
        fake = MagicMock(return_value=np.array(self.EMBS, dtype="float32"))
        monkeypatch.setattr(setup.mod, "extract_specter2", fake)
        out = setup.mod.assign_topics(self._new_df(), None)
        fake.assert_called_once()
        assert len(out.topics) == 4

    def test_report_contains_only_projects_below_threshold(self, setup):
        report = setup.report_of(self._new_df(), setup.embs, similarity_threshold=0.92)
        assert report["projectID"].tolist() == [13]
        row = report.iloc[0]
        assert row["title"] == "T3"
        assert row["nearest_topic"] == "Climate Modelling"
        assert row["similarity"] == pytest.approx(1 / np.sqrt(2), abs=1e-4)
        assert row["cluster"] == -1 and row["cluster_size"] == 0

    def test_report_columns(self, setup):
        assert list(setup.report_of(self._new_df(), setup.embs).columns) == [
            "cluster", "cluster_size", "cluster_keywords", "projectID", "title", "similarity", "nearest_topic",
            "auto_assigned"]

    def test_threshold_is_configurable(self, setup):
        assert setup.report_of(self._new_df(), setup.embs, similarity_threshold=0.5).empty
        assert len(setup.report_of(self._new_df(), setup.embs, similarity_threshold=1.01)) == 4

    def test_review_runs_after_report(self, setup, monkeypatch):
        seen = {}

        def fake_review(ctx, mode, sheet_path, model_dir, hier_path, backup_dir):
            seen.update(mode=mode, path=sheet_path, report=ctx.report.copy(), ids=ctx.project_ids,
                        model_dir=model_dir, hier_path=hier_path, backup_dir=backup_dir,
                        titles=ctx.titles, objectives=ctx.objectives, reviewed=ctx.reviewed_topics,
                        existing=ctx.existing, threshold=ctx.similarity_threshold)
            return np.array([1, 1, 1, 1]), pd.DataFrame()

        monkeypatch.setattr(setup.mod, "review_and_apply", fake_review)
        out = setup.mod.assign_topics(self._new_df(), setup.embs, review="provisional", sheet_path="d.xlsx",
                                      similarity_threshold=0.9)
        assert seen["existing"] is None and seen["threshold"] == 0.9, "i progetti già nel db non c'entrano"
        assert not hasattr(out, "moves")
        assert out.embeddings.shape == (4, 4) and np.allclose(out.embeddings, self.EMBS)
        assert seen["mode"] == "provisional" and seen["path"] == "d.xlsx"
        assert seen["ids"] == [11, 12, 13, 14]
        assert seen["report"]["projectID"].tolist() == [13]
        assert seen["titles"] == ["T1", "", "T3", "T4"] and seen["objectives"] == ["O1", "O2", "", "O4"]
        assert seen["model_dir"] == setup.mod.OLD_TOPIC_MODEL_DIR
        assert seen["hier_path"] == setup.mod.TOPIC_HIER_DICT_DIR
        assert seen["backup_dir"] == setup.mod.BACKUP_DIR
        assert seen["reviewed"] == set()
        assert (out.topics["topic_name"] == "Wireless Networks").all(), "i topic finali sono quelli restituiti"

    def test_invalid_review_mode(self, setup):
        with pytest.raises(ValueError):
            setup.mod.assign_topics(self._new_df(), setup.embs, review="sheet")

    def test_isolated_candidate_is_unlabelled_until_reviewed(self, setup, tmp_path):
        out = setup.mod.assign_topics(self._new_df(), setup.embs, review="provisional",
                                      sheet_path=str(tmp_path / "s.xlsx"))
        assert (tmp_path / "s.xlsx").exists()
        assert out.topics["topic_name"].tolist() == ["Climate Modelling", "Wireless Networks",
                                                     "Unlabelled", "Unlabelled"], "13 è isolato, 14 è il topic -1"

    def test_no_candidates_changes_nothing(self, setup):
        out = setup.mod.assign_topics(self._new_df(), setup.embs, review="provisional", sheet_path=None,
                                      similarity_threshold=0.5)
        assert out.topics["topic_name"].tolist() == ["Climate Modelling", "Wireless Networks",
                                                     "Climate Modelling", "Unlabelled"]

    def test_cluster_gets_the_topic_of_its_centroid(self, topic_mod, monkeypatch, topic2hier_file, tmp_path):
        """Tutti i candidati di un cluster vanno al topic più vicino al centroide, anche chi da solo
        sarebbe più vicino a un altro; gli isolati sono Unlabelled."""
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        n = 14
        _install_old_model(topic_mod, monkeypatch)
        labels = [0] * 7 + [-1] * 7
        monkeypatch.setattr(topic_mod, "cluster_candidates",
                            lambda docs, embs, mcs: (FakeClusterModel({0: ["ai"]}), labels))
        a, b, c = [1, .5, .5, .5], [.6, 1, .5, .5], [.5, .5, 1, .5]
        embs = _f32([a] * 5 + [b] * 2 + [c] * 7)
        df = pd.DataFrame({"projectID": range(100, 100 + n), "title": ["t"] * n, "objective": ["o"] * n})
        seen = {}
        real = topic_mod.review_and_apply
        monkeypatch.setattr(topic_mod, "review_and_apply",
                            lambda ctx, *args: seen.update(report=ctx.report.copy()) or real(ctx, *args))
        out = topic_mod.assign_topics(df, embs, review="provisional", sheet_path=str(tmp_path / "s.xlsx"))
        assert out.topics["topic_name"].tolist() == ["Climate Modelling"] * 7 + ["Unlabelled"] * 7
        # le due righe b da sole andrebbero al topic 1 (Wireless Networks): il foglio mostra il topic provvisorio
        assert seen["report"].loc[seen["report"]["cluster"] == 0, "nearest_topic"].eq("Climate Modelling").all()
        assert seen["report"].loc[seen["report"]["cluster"] == -1, "nearest_topic"].eq("Unlabelled").all()

    def test_provisional_topics_leave_auto_assigned_projects(self, topic_mod):
        model = FakeOldTopicModel([])
        report = pd.DataFrame({"cluster": [0, 0, -1], "projectID": [1, 2, 3]})
        embs = _f32([[1, .5, .5, .5]] * 3)
        topics = np.array([2, 2, 2])
        auto = np.array([True, False, True])
        out = topic_mod.provisional_topics(topics, report, [1, 2, 3], embs, model, set(), 0.92, 0.02, auto)
        assert out.tolist() == [2, 0, 2], "il primo e il terzo restano al topic assegnato in automatico"
        assert topics.tolist() == [2, 2, 2], "l'input non viene modificato"

    def test_default_review_keeps_nearest(self, setup):
        out = setup.mod.assign_topics(self._new_df(), setup.embs)
        assert out.topics["topic_name"].tolist()[0] == "Climate Modelling"

    def test_topic_missing_from_hierarchy_has_no_name(self, topic_mod, monkeypatch, tmp_path, topic2hier_file):
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        model = _install_old_model(topic_mod, monkeypatch)
        # topic 3, assente da topic2hier (come il 177 reale), è il più vicino al progetto
        model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [[1, 0.1, 0, 0]]]).astype("float32")
        df = pd.DataFrame({"projectID": [1], "title": ["T"], "objective": ["O"]})
        out = topic_mod.assign_topics(df, _f32([[1, 0.1, 0, 0]]))
        assert out.topics["topic_name"].tolist() == [None]
        assert out.topics["topic_name_hierarchy"].tolist() == [None]

    def test_few_candidates_are_not_clustered(self, setup):
        setup.report_of(self._new_df(), setup.embs, similarity_threshold=1.01)
        setup.cluster.assert_not_called()

    def test_candidates_are_clustered_and_sorted(self, topic_mod, monkeypatch, tmp_path, topic2hier_file, capsys):
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        n = 14
        _install_old_model(topic_mod, monkeypatch, [0] * n)
        labels = [1] * 5 + [0] * 7 + [-1] * 2
        seen = {}

        def fake_cluster(docs, embs, min_cluster_size):
            seen.update(n_docs=len(docs), embs_shape=embs.shape, mcs=min_cluster_size)
            return FakeClusterModel({0: ["ai", "models"], 1: ["ocean", "climate"]}), labels

        monkeypatch.setattr(topic_mod, "cluster_candidates", fake_cluster)
        rng = np.random.default_rng(0)
        embs = 0.5 + rng.normal(scale=0.02, size=(n, 4))  # lontani da tutti i topic: tutti candidati
        df = pd.DataFrame({"projectID": range(100, 100 + n), "title": [f"P{i}" for i in range(n)],
                           "objective": ["obj"] * n})
        report = _report_of(topic_mod, monkeypatch, df, _f32(embs), similarity_threshold=0.92,
                            min_cluster_size=5)

        assert seen == {"n_docs": n, "embs_shape": (n, 4), "mcs": 5}
        assert report["cluster"].tolist() == [0] * 7 + [1] * 5 + [-1] * 2
        assert report["cluster_size"].tolist() == [7] * 7 + [5] * 5 + [0] * 2
        assert set(report.loc[report.cluster == 0, "cluster_keywords"]) == {"ai, models"}
        assert set(report.loc[report.cluster == 1, "cluster_keywords"]) == {"ocean, climate"}
        assert (report.loc[report.cluster == -1, "cluster_keywords"] == "").all()
        for c in (0, 1, -1):
            sims = report.loc[report.cluster == c, "similarity"].tolist()
            assert sims == sorted(sims), "dentro un cluster i meno simili vengono prima"
        out = capsys.readouterr().out
        assert "2 candidate new topics" in out and "2 isolated projects" in out

    def test_minimum_candidates_for_clustering(self, topic_mod, monkeypatch, tmp_path, topic2hier_file):
        """Il clustering parte solo con almeno max(2 * min_cluster_size, N_NEIGHBORS + 2) candidati."""
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(topic2hier_file))
        n = topic_mod.N_NEIGHBORS + 1
        _install_old_model(topic_mod, monkeypatch, [0] * n)
        cluster = MagicMock(name="cluster_candidates")
        monkeypatch.setattr(topic_mod, "cluster_candidates", cluster)
        df = pd.DataFrame({"projectID": range(n), "title": ["t"] * n, "objective": ["o"] * n})
        topic_mod.assign_topics(df, _f32(np.tile([0.5, 0.5, 0.5, 0.5], (n, 1))),
                                min_cluster_size=2)
        cluster.assert_not_called()


@pytest.fixture
def topic_mod_real(monkeypatch):
    """extract_topic con BERTopic, UMAP e HDBSCAN reali (senza modelli di embedding)."""
    for dep in ("bertopic", "umap", "hdbscan", "nltk"):
        pytest.importorskip(dep)
    fake_emb = types.ModuleType("extract_embedding")
    fake_emb.extract_specter2 = MagicMock(name="extract_specter2")
    monkeypatch.setitem(sys.modules, "extract_embedding", fake_emb)
    return load_module(monkeypatch, "extract_topic", HERE / "extract_topic.py")


@pytest.mark.filterwarnings("ignore:n_jobs value:UserWarning")  # avviso di umap, non della pipeline
@pytest.mark.filterwarnings("ignore:n_jobs value:UserWarning")  # avviso di umap, non della pipeline
class TestClusterCandidates:
    def test_separates_distinct_themes(self, topic_mod_real):
        rng = np.random.default_rng(0)
        themes = {
            "ocean": "ocean water marine coastal sea currents salinity",
            "speech": "speech language phonetic lexical infants vocabulary",
            "robot": "robot manipulation gripper actuator autonomous navigation",
        }
        docs, embs, truth = [], [], []
        for k, (name, words) in enumerate(themes.items()):
            centre = np.zeros(32)
            centre[k * 10] = 10
            for _ in range(15):
                docs.append(f"{name} {words} {rng.choice(words.split())}")
                embs.append(centre + rng.normal(scale=0.3, size=32))
                truth.append(k)
        model, labels = topic_mod_real.cluster_candidates(docs, np.array(embs), min_cluster_size=5)
        labels = np.asarray(labels)
        truth = np.asarray(truth)
        assert len(set(labels) - {-1}) == 3
        for k in range(3):
            found = labels[truth == k]
            found = found[found >= 0]
            assert len(set(found)) == 1, f"il tema {k} è stato diviso in più cluster"
        info = model.get_topic_info()
        words = {w for rep in info[info.Topic >= 0].Representation for w in rep}
        assert {"ocean", "speech", "robot"} <= words


# ==============================================================================
# 2.8 UNIT TEST: topic_review.py e topic_review_sheet.py (revisione dei topic nuovi)
# ==============================================================================
# gerarchia di prova, nello stesso formato allineato a destra di topic2hier.json
SMALL_HIER = {
    "-1": ["Unlabelled", "Unlabelled", "Unlabelled", "Unlabelled"],
    "0": ["Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"],
    "1": ["Wireless Networks", "Telecommunications", "Computer Engineering", "Engineering & Technology"],
    "2": ["Unlabelled", "Unlabelled", "Robotics", "Engineering & Technology"],
}
P_CLIMATE = ("Earth & Life Science", "Climatology", "Climate Modelling")
P_WIRELESS = ("Engineering & Technology", "Computer Engineering", "Telecommunications", "Wireless Networks")
P_ROBOTICS = ("Engineering & Technology", "Robotics")


@pytest.fixture
def review_mod(monkeypatch):
    pytest.importorskip("pyarrow")
    load_module(monkeypatch, "specter_store", HERE / "specter_store.py")
    load_module(monkeypatch, "create_projgraph", HERE / "create_projgraph.py")
    mod = load_module(monkeypatch, "topic_review", HERE / "topic_review.py")
    try:
        load_module(monkeypatch, "topic_review_sheet", HERE / "topic_review_sheet.py")
    except ImportError:    # senza openpyxl i test del foglio vengono saltati (sheet_mod)
        monkeypatch.delitem(sys.modules, "topic_review_sheet", raising=False)
    return mod


@pytest.fixture
def hier(review_mod):
    return review_mod.Hierarchy(SMALL_HIER)


def make_updatable_model(corpus, n_topics=3, dim=5):
    """Modello finto con gli attributi che add_topic_to_model aggiorna. Righe degli
    embedding: -1, 0, 1, 2 sui primi assi ortogonali."""
    from sklearn.feature_extraction.text import CountVectorizer
    import scipy.sparse as sp
    vec = CountVectorizer().fit(corpus)
    rows = [dim - 1] + list(range(n_topics))
    saved = []
    model = SimpleNamespace(
        _outliers=1,
        topic_embeddings_=np.eye(dim, dtype="float32")[rows],
        vectorizer_model=vec,
        ctfidf_model=SimpleNamespace(transform=lambda X: sp.csr_matrix(X, dtype=float)),
        c_tf_idf_=sp.csr_matrix((n_topics + 1, len(vec.vocabulary_))),
        topic_representations_={t: [] for t in range(-1, n_topics)},
        topic_sizes_={t: 10 for t in range(-1, n_topics)},
        topic_labels_={t: str(t) for t in range(-1, n_topics)},
        custom_labels_=None,
        top_n_words=10,
        saved=saved,
    )

    def save(path, serialization="pickle", save_ctfidf=False):
        os.makedirs(path)
        Path(path, "marker.txt").write_text(f"topics={len(model.topic_embeddings_) - 1}")
        saved.append((path, serialization, save_ctfidf))

    model.save = save
    return model


class TestHierarchy:
    def test_paths_from_right_aligned_lists(self, hier):
        assert hier.path(0) == P_CLIMATE
        assert hier.path(1) == P_WIRELESS
        assert hier.path(2) == P_ROBOTICS
        assert hier.path(-1) == ()

    def test_roundtrip(self, hier):
        assert hier.to_json() == SMALL_HIER

    def test_real_topic2hier_roundtrip(self, review_mod):
        path = REAL_DATA / "topic2hier.json"
        if not path.exists():
            pytest.skip("topic2hier.json non trovato")
        with open(path, encoding="utf-8") as f:
            original = json.load(f)
        assert review_mod.Hierarchy(original).to_json() == original

    def test_save_and_load(self, review_mod, hier, tmp_path):
        hier.save(tmp_path / "h.json")
        assert review_mod.Hierarchy.load(tmp_path / "h.json").to_json() == SMALL_HIER
        assert not (tmp_path / "h.json.tmp").exists()

    def test_names(self, hier):
        assert hier.name(0) == "Climate Modelling"
        assert hier.name(2) == "Robotics"
        assert hier.name(-1) == "Unlabelled"
        assert hier.name(99) == "Unlabelled"

    def test_children_are_categories_only(self, hier):
        assert hier.children() == ["Earth & Life Science", "Engineering & Technology"]
        assert hier.children(("Engineering & Technology",)) == ["Computer Engineering"]
        assert hier.children(("Engineering & Technology", "Computer Engineering")) == ["Telecommunications"]
        assert hier.children(P_WIRELESS[:3]) == []

    def test_topic_for_path(self, hier):
        assert hier.topic_for_path(P_ROBOTICS) == 2
        assert hier.topic_for_path(("Engineering & Technology", "Nope")) is None

    def test_copy_is_independent(self, hier):
        other = hier.copy()
        other.add(10, ("Engineering & Technology", "Computer Engineering", "Generative AI"))
        assert 10 not in hier.paths

    @pytest.mark.parametrize("path", [
        ("Engineering & Technology", "Computer Engineering", "Generative AI"),            # come sotto-area
        ("Engineering & Technology", "Computer Engineering", "Telecommunications", "5G"),  # come foglia
        ("Engineering & Technology", "Artificial Intelligence", "Generative AI"),        # area nuova
        ("Engineering & Technology", "Generative AI"),                                   # sotto una macro-area
        ("Digital Humanities", "Text Mining"),                                           # macro-area nuova
    ])
    def test_valid_new_paths(self, hier, path):
        hier.validate_new_path(path)
        hier.add(10, path)
        assert hier.path(10) == path
        assert hier.to_json()["10"][-len(path):] == list(reversed(path))
        assert len(hier.to_json()["10"]) == 4

    @pytest.mark.parametrize("path,error", [
        (("Generative AI",), "da 2 a 4"),
        (("A", "B", "C", "D", "E"), "da 2 a 4"),
        (("Engineering & Technology", "Unlabelled"), "non valido"),
        (("Engineering & Technology", " Padded "), "non valido"),
        (("Engineering & Technology", "X", "X"), "due volte"),
        (P_ROBOTICS, "esiste già"),
        (("Engineering & Technology", "Computer Engineering"), "categoria"),
        (("Engineering & Technology", "Robotics", "Soft Robotics"), "non può avere figli"),
        (("Earth & Life Science", "Computer Engineering", "X"), "un solo padre"),
        (("Earth & Life Science", "Robotics"), "un solo padre"),
    ])
    def test_invalid_new_paths(self, review_mod, hier, path, error):
        with pytest.raises(review_mod.HierarchyError, match=error):
            hier.validate_new_path(path)
        with pytest.raises(review_mod.HierarchyError):
            hier.add(10, path)
        assert 10 not in hier.paths

    def test_add_existing_id(self, review_mod, hier):
        with pytest.raises(review_mod.HierarchyError, match="esiste già"):
            hier.add(2, ("Engineering & Technology", "Generative AI"))

    def test_unlabelled_alias(self, hier):
        hier.add(10, ())
        assert hier.to_json()["10"] == ["Unlabelled"] * 4
        assert hier.name(10) == "Unlabelled"


class TestCheckName:
    @pytest.mark.parametrize("name,exact,similar", [
        ("climate modelling", ["Climate Modelling"], []),
        ("Climate Modeling", [], ["Climate Modelling"]),
        ("Robotics Systems", [], ["Robotics"]),
        ("Ocean Acidification", [], []),
        ("AI", [], []),
    ])
    def test_check_name(self, review_mod, hier, name, exact, similar):
        got_exact, got_similar = review_mod.check_name(name, hier)
        assert got_exact == exact
        assert set(similar) <= set(got_similar)
        if not similar:
            assert got_similar == []

    def test_categories_are_checked_too(self, review_mod, hier):
        assert review_mod.check_name("computer engineering", hier)[0] == ["Computer Engineering"]


CORPUS = ["ocean acidification coral reef carbonate", "ocean acidification shellfish carbonate",
          "speech language phonetics", "robot gripper arm", "wireless antenna network",
          "climate model simulation"]


@pytest.fixture
def batch(review_mod, hier):
    """6 progetti nuovi: topic più vicino 0, 0, 1, 1, 2, 2."""
    embs = np.array([
        [0.9, 0.1, 0, 0, 0.2],
        [0.8, 0.2, 0, 0, 0.3],
        [0, 1, 0.1, 0, 0],
        [0, 0.9, 0, 0.2, 0],
        [0, 0, 1, 0.1, 0],
        [0.1, 0, 0.9, 0, 0],
    ], dtype="float32")
    return SimpleNamespace(
        ids=[101, 102, 103, 104, 105, 106],
        embs=embs,
        docs=CORPUS,
        topics=np.array([0, 0, 1, 1, 2, 2]),
        model=make_updatable_model(CORPUS),
        hier=hier,
    )


OCEAN_PATH = ("Earth & Life Science", "Climatology", "Ocean Acidification")


class TestApplyGroups:
    PATH = OCEAN_PATH

    def _apply(self, review_mod, b, groups, reviewed=None):
        return review_mod.apply_groups(groups, b.ids, b.topics, b.embs, b.docs, b.model, b.hier, reviewed)

    def test_new_path_creates_topic(self, review_mod, batch):
        topics, created, changed = self._apply(review_mod, batch, {self.PATH: [101, 102]})
        assert changed and created == [(3, self.PATH)]
        assert topics.tolist() == [3, 3, 1, 1, 2, 2]
        assert batch.hier.path(3) == self.PATH
        m = batch.model
        assert m.topic_embeddings_.shape == (5, 5)
        assert np.allclose(m.topic_embeddings_[4], batch.embs[:2].mean(axis=0))
        assert m.c_tf_idf_.shape[0] == 5
        words = [w for w, _ in m.topic_representations_[3]]
        assert set(words[:3]) == {"acidification", "carbonate", "ocean"}
        assert m.topic_sizes_[3] == 2
        assert m.topic_labels_[3].startswith("3_")

    def test_existing_path_changes_nothing_else(self, review_mod, batch):
        rows = batch.model.topic_embeddings_.shape
        topics, created, changed = self._apply(review_mod, batch, {P_ROBOTICS: [103, 104]})
        assert not changed and created == []
        assert topics.tolist() == [0, 0, 2, 2, 2, 2]
        assert batch.model.topic_embeddings_.shape == rows
        assert batch.hier.to_json() == SMALL_HIER

    def test_unlabelled_alias(self, review_mod, batch):
        topics, created, changed = self._apply(review_mod, batch, {(): [105, 106]})
        assert changed and created == [], "un alias non prende progetti già nel db"
        assert topics.tolist() == [0, 0, 1, 1, 3, 3]
        assert batch.hier.path(3) == ()
        assert batch.hier.to_json()["3"] == ["Unlabelled"] * 4
        assert np.allclose(batch.model.topic_embeddings_[4], batch.embs[4:].mean(axis=0))

    def test_isolated_unlabelled_is_not_an_alias(self, review_mod, batch):
        rows = batch.model.topic_embeddings_.shape
        topics, created, changed = self._apply(review_mod, batch, {review_mod.PLAIN_UNLABELLED: [105, 106]})
        assert not changed and created == []
        assert topics.tolist() == [0, 0, 1, 1, -1, -1]
        assert batch.model.topic_embeddings_.shape == rows and batch.hier.to_json() == SMALL_HIER

    def test_created_topics_become_reviewed(self, review_mod, batch):
        reviewed = {99}
        self._apply(review_mod, batch, {self.PATH: [101], P_ROBOTICS: [103], (): [105]}, reviewed)
        assert reviewed == {99, 3, 4}

    def test_ids_follow_group_order(self, review_mod, batch):
        topics, created, _ = self._apply(review_mod, batch, {(): [105], self.PATH: [101]})
        assert topics[4] == 3 and topics[0] == 4
        assert created == [(4, self.PATH)]

    def test_input_topics_are_not_modified(self, review_mod, batch):
        before = batch.topics.copy()
        self._apply(review_mod, batch, {self.PATH: [101]})
        assert batch.topics.tolist() == before.tolist()

    def test_invalid_path_leaves_model_untouched(self, review_mod, batch):
        with pytest.raises(review_mod.HierarchyError):
            self._apply(review_mod, batch, {("Engineering & Technology", "Robotics", "Arms"): [101]})
        assert batch.model.topic_embeddings_.shape == (4, 5)

    def test_add_topic_requires_next_id(self, review_mod, batch):
        with pytest.raises(ValueError, match="id 3"):
            review_mod.add_topic_to_model(batch.model, batch.embs[:1], batch.docs[:1], 7)

    def test_custom_labels_extended(self, review_mod, batch):
        batch.model.custom_labels_ = ["a", "b", "c", "d"]
        review_mod.add_topic_to_model(batch.model, batch.embs[:1], batch.docs[:1], 3)
        assert len(batch.model.custom_labels_) == 5


class TestSaveWithBackup:
    def test_backup_and_replace(self, review_mod, batch, tmp_path):
        model_dir = tmp_path / "old_topic_model"
        model_dir.mkdir()
        (model_dir / "marker.txt").write_text("originale")
        hier_path = tmp_path / "topic2hier.json"
        hier_path.write_text(json.dumps(SMALL_HIER))
        batch.hier.add(3, ("Engineering & Technology", "Generative AI"))

        (model_dir / "reviewed_topics.json").write_text("[]")
        stamp = review_mod.save_with_backup(batch.model, str(model_dir), batch.hier, str(hier_path),
                                            str(tmp_path / "backups"), {3})

        assert batch.model.saved[0][1:] == ("safetensors", True)
        assert (model_dir / "marker.txt").read_text() == "topics=3"
        assert (tmp_path / "backups" / f"old_topic_model_{stamp}" / "marker.txt").read_text() == "originale"
        assert json.loads((tmp_path / "backups" / f"topic2hier_{stamp}.json").read_text()) == SMALL_HIER
        assert "3" in json.loads(hier_path.read_text())
        assert not Path(f"{model_dir}.tmp").exists()
        assert review_mod.load_reviewed_topics(str(model_dir)) == {3}
        backup = tmp_path / "backups" / f"old_topic_model_{stamp}"
        assert review_mod.load_reviewed_topics(str(backup)) == set()

    def test_load_reviewed_topics(self, review_mod, tmp_path):
        assert review_mod.load_reviewed_topics(str(tmp_path)) == set()
        (tmp_path / "reviewed_topics.json").write_text("[203, 204]")
        assert review_mod.load_reviewed_topics(str(tmp_path)) == {203, 204}


def make_ctx(review_mod, batch, report_rows):
    report = pd.DataFrame(report_rows, columns=["cluster", "cluster_size", "cluster_keywords", "projectID",
                                                "title", "similarity", "nearest_topic"])
    report["auto_assigned"] = False
    titles = ["Coral reef acidification", "Shellfish and ocean acidification", "Speech corpora",
              "Robot arms", "Antenna design", "Climate simulation"]
    return review_mod.ReviewContext(
        project_ids=batch.ids, titles=titles, objectives=[f"Objective of {t}" for t in titles],
        documents=batch.docs, embeddings=batch.embs, topics=batch.topics,
        similarity=np.array([0.80, 0.82, 0.85, 0.86, 0.9, 0.7]),
        report=report, model=batch.model, hierarchy=batch.hier)


# cluster 0 = progetti 101-102 (vicini a Climate Modelling), cluster 1 = 103-104, isolato 106
REPORT_ROWS = [
    (0, 2, "ocean, acidification", 101, "Coral reef acidification", 0.80, "Climate Modelling"),
    (0, 2, "ocean, acidification", 102, "Shellfish and ocean acidification", 0.82, "Climate Modelling"),
    (1, 2, "speech, wireless", 103, "Speech corpora", 0.85, "Wireless Networks"),
    (1, 2, "speech, wireless", 104, "Robot arms", 0.86, "Wireless Networks"),
    (-1, 0, None, 106, "Climate simulation", 0.70, "Robotics"),
]


@pytest.fixture
def ctx(review_mod, batch):
    return make_ctx(review_mod, batch, REPORT_ROWS)


class TestSimilarTopics:
    def test_similar_topics(self, review_mod, ctx):
        centroid = ctx.embeddings[:2].mean(axis=0)
        sims = review_mod.similar_topics(ctx.model, ctx.hierarchy, centroid, 3)
        assert sims[0][:2] == (0, P_CLIMATE)
        ids = [t for t, _, _ in sims]
        assert -1 not in ids and len(ids) == 3

    def test_similar_topics_skip_aliases_and_unknown(self, review_mod, batch):
        model = batch.model
        # topic 3 = alias Unlabelled, topic 4 = stesso percorso di 0, topic 5 = assente dalla gerarchia
        extra = np.array([[1, 0, 0, 0, 0], [0.9, 0.1, 0, 0, 0], [1, 0, 0, 0, 0]], dtype="float32")
        model.topic_embeddings_ = np.vstack([model.topic_embeddings_, extra])
        batch.hier.add(3, ())
        batch.hier.paths[4] = P_CLIMATE
        sims = review_mod.similar_topics(model, batch.hier, np.array([1, 0, 0, 0, 0], dtype="float32"))
        assert sims[0][0] == 0
        assert sorted(t for t, _, _ in sims) == [0, 1, 2], "alias, duplicati e topic sconosciuti esclusi"


# ------------------------------------------------------------------------------
# il foglio Excel: scrittura e lettura
# ------------------------------------------------------------------------------
@pytest.fixture
def sheet_mod(review_mod):
    pytest.importorskip("openpyxl")
    return sys.modules["topic_review_sheet"]


@pytest.fixture
def sheet(sheet_mod, ctx, tmp_path):
    path = tmp_path / "review.xlsx"
    sheet_mod.write_review_sheet(ctx, str(path))
    return path


def edit_sheet(path, *edits):
    """edits: (foglio, cella, valore)."""
    from openpyxl import load_workbook
    wb = load_workbook(path)
    for name, cell, value in edits:
        wb[name][cell] = value
    wb.save(path)


def set_path(sheet_name, levels, row=4, first_col="B"):
    return [(sheet_name, f"{chr(ord(first_col) + i)}{row}", v) for i, v in enumerate(levels)]


def row_of(ws, project_id):
    return next(r for r in range(9, ws.max_row + 1) if ws.cell(r, 1).value == project_id)


def read_groups(sheet_mod, ctx, path):
    groups, warnings = sheet_mod.read_review_sheet(str(path), ctx)
    return {k: sorted(v) for k, v in groups.items()}, warnings


class TestReviewSheetWrite:
    def test_sheets(self, sheet):
        from openpyxl import load_workbook
        assert load_workbook(sheet).sheetnames == ["Istruzioni", "Indice", "Gerarchia", "C01", "C02", "Isolati"]

    def test_cluster_sheet_header(self, sheet):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["C01"]
        assert "2 progetti" in ws["A1"].value
        assert ws["B2"].value == "ocean, acidification"
        assert "Climate Modelling" in ws["B3"].value
        assert [ws.cell(4, c).value for c in range(2, 6)] == [None] * 4, "il percorso va compilato a mano"
        assert [ws.cell(8, c).value for c in range(1, 7)] == [
            "projectID", "Titolo", "Objective", "Topic provvisorio", "Altro topic", None], "niente similarità"

    def test_projects_listed_by_relevance(self, review_mod, batch, sheet_mod, tmp_path):
        """Il progetto più lontano dal centroide del cluster va per ultimo."""
        rows = [(0, 3, "k", p, "t", 0.8, "x") for p in (101, 102, 106)]
        path = tmp_path / "r.xlsx"
        sheet_mod.write_review_sheet(make_ctx(review_mod, batch, rows), str(path))
        from openpyxl import load_workbook
        ws = load_workbook(path)["C01"]
        assert [ws.cell(r, 1).value for r in range(9, 12)][-1] == 106
        assert ws.cell(12, 1).value is None

    def test_project_row_content(self, sheet):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["C01"]
        r = row_of(ws, 101)
        assert ws.cell(r, 2).value == "Coral reef acidification"
        assert ws.cell(r, 3).value == "Objective of Coral reef acidification"
        assert ws.cell(r, 4).value == "Climate Modelling"
        assert ws.cell(r, 5).value is None

    def test_isolated_sheet(self, sheet):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["Isolati"]
        text = " ".join(str(ws.cell(r, 1).value) for r in range(1, 5))
        assert "Unlabelled" in text and "isolati" in text.lower()
        assert ws.cell(9, 1).value == 106 and ws.cell(10, 1).value is None
        assert [ws.cell(8, c).value for c in range(5, 9)] == ["Livello 1", "Livello 2", "Livello 3", "Livello 4"]

    def test_hierarchy_sheet(self, sheet, hier):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["Gerarchia"]
        rows = {tuple(ws.cell(r, c).value for c in range(1, 5) if ws.cell(r, c).value) for r in range(2, ws.max_row + 1)}
        rows.discard(())
        assert hier.leaves() <= rows
        areas = {ws.cell(r, 6).value for r in range(2, ws.max_row + 1)} - {None}
        assert areas == {"Earth & Life Science", "Engineering & Technology"}

    def test_level_one_menu_allows_free_text(self, sheet):
        from openpyxl import load_workbook
        dv = load_workbook(sheet)["C01"].data_validations.dataValidation
        by_cell = {str(d.sqref): d for d in dv}
        assert set(by_cell) == {"B4", "E9:E10"}, "macro-aree sul livello 1, topic esistenti su Altro topic"
        assert all(not d.showErrorMessage for d in dv), "il testo libero resta ammesso"
        assert "$F$" in by_cell["B4"].formula1 and "$H$" in by_cell["E9:E10"].formula1

    def test_leaf_topics_listed_for_the_menu(self, sheet, hier):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["Gerarchia"]
        names = {ws.cell(r, 8).value for r in range(2, ws.max_row + 1)} - {None}
        assert names == {leaf[-1] for leaf in hier.leaves()}

    def test_index_links_clusters(self, sheet):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["Indice"]
        assert ws["A2"].value.startswith("=HYPERLINK") and "C01" in ws["A2"].value
        assert ws["B2"].value == 2 and ws["C3"].value == "speech, wireless"
        assert ws["E2"].value.startswith("=IF(") and "C01" in ws["E2"].value
        assert ws.max_row == 3

    def test_text_that_looks_like_a_formula_stays_text(self, sheet_mod, ctx, tmp_path):
        from openpyxl import load_workbook
        ctx.titles[0] = "=1+1"
        path = tmp_path / "f.xlsx"
        sheet_mod.write_review_sheet(ctx, str(path))
        cell = load_workbook(path)["C01"].cell(row_of(load_workbook(path)["C01"], 101), 2)
        assert cell.value == "=1+1" and cell.data_type == "s"

    def test_long_abstract_is_cut_and_control_chars_removed(self, sheet_mod, ctx, tmp_path):
        from openpyxl import load_workbook
        ctx.objectives[0] = "ab\x00c" + "x" * 5000
        path = tmp_path / "f.xlsx"
        sheet_mod.write_review_sheet(ctx, str(path))
        ws = load_workbook(path)["C01"]
        value = ws.cell(row_of(ws, 101), 3).value
        assert value.startswith("abcx") and len(value) <= sheet_mod.ABSTRACT_CHARS

    def test_without_clusters(self, review_mod, batch, sheet_mod, tmp_path):
        from openpyxl import load_workbook
        path = tmp_path / "r.xlsx"
        sheet_mod.write_review_sheet(make_ctx(review_mod, batch, REPORT_ROWS[-1:]), str(path))
        assert load_workbook(path).sheetnames == ["Istruzioni", "Indice", "Gerarchia", "Isolati"]


class TestReviewSheetRead:
    def test_untouched_sheet_changes_nothing(self, sheet_mod, ctx, sheet):
        assert read_groups(sheet_mod, ctx, sheet) == ({}, [])

    def test_new_path_for_a_cluster(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [101, 102]}

    def test_existing_path_for_a_cluster(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C02", P_ROBOTICS))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {P_ROBOTICS: [103, 104]}

    def test_unlabelled(self, sheet_mod, ctx, sheet):
        """Un cluster Unlabelled diventa un alias nel modello, gli isolati Unlabelled no."""
        edit_sheet(sheet, ("C02", "B4", "unlabelled"), ("Isolati", "E9", "Unlabelled"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {(): [103, 104], ("Unlabelled",): [106]}

    def _other(self, sheet, pid, value, sheet_name="C01"):
        from openpyxl import load_workbook
        return (sheet_name, f"E{row_of(load_workbook(sheet)[sheet_name], pid)}", value)

    def test_x_keeps_the_provisional_topic(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), self._other(sheet, 101, "x"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [102]}

    def test_x_is_case_insensitive_and_only_x_excludes(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), self._other(sheet, 101, " X "))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [102]}
        edit_sheet(sheet, self._other(sheet, 101, "no"))
        with pytest.raises(sheet_mod.SheetError, match="non è un topic esistente"):
            read_groups(sheet_mod, ctx, sheet)

    def test_other_topic_assigns_an_existing_leaf(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), self._other(sheet, 101, "Robotics"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [102], P_ROBOTICS: [101]}

    def test_other_topic_without_a_cluster_path(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, self._other(sheet, 103, "wireless networks", "C02"),
                   self._other(sheet, 104, " Robotics ", "C02"))
        groups, _ = read_groups(sheet_mod, ctx, sheet)
        assert groups == {P_WIRELESS: [103], P_ROBOTICS: [104]}, "senza percorso il cluster resta com'è"

    def test_other_topic_joins_the_group_of_that_path(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C02", P_ROBOTICS), self._other(sheet, 101, "Robotics"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {P_ROBOTICS: [101, 103, 104]}

    @pytest.mark.parametrize("value", ["Not a topic", "Climatology", "Earth & Life Science"])
    def test_other_topic_must_be_an_existing_leaf(self, sheet_mod, ctx, sheet, value):
        edit_sheet(sheet, self._other(sheet, 101, value))
        with pytest.raises(sheet_mod.SheetError, match="non è un topic esistente") as e:
            read_groups(sheet_mod, ctx, sheet)
        assert "C01!E" in str(e.value) and "1 error" in str(e.value)

    def test_other_topic_name_shared_by_two_leaves_is_ambiguous(self, sheet_mod, ctx, sheet):
        ctx.hierarchy.paths[9] = ("Engineering & Technology", "Computer Engineering", "Robotics")
        edit_sheet(sheet, self._other(sheet, 101, "Robotics"))
        with pytest.raises(sheet_mod.SheetError, match="più topic"):
            read_groups(sheet_mod, ctx, sheet)

    def test_deleted_rows_are_excluded(self, sheet_mod, ctx, sheet):
        from openpyxl import load_workbook
        wb = load_workbook(sheet)
        wb["C01"].delete_rows(row_of(wb["C01"], 102))
        wb.save(sheet)
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [101]}

    def test_same_new_path_in_several_sheets_is_one_topic(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), *set_path("C02", OCEAN_PATH),
                   *set_path("Isolati", OCEAN_PATH, row=9, first_col="E"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [101, 102, 103, 104, 106]}

    def test_isolated_project_has_its_own_path(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("Isolati", P_ROBOTICS, row=9, first_col="E"))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {P_ROBOTICS: [106]}

    def test_existing_names_are_matched_ignoring_case(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", ["earth & life science", "climatology", "CLIMATE MODELLING"]))
        groups, warnings = read_groups(sheet_mod, ctx, sheet)
        assert groups == {P_CLIMATE: [101, 102]}
        assert any("corretto" in w for w in warnings)

    def test_similar_new_name_is_a_warning(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", ["Earth & Life Science", "Climatology", "Climate Modeling"]))
        groups, warnings = read_groups(sheet_mod, ctx, sheet)
        assert list(groups) == [("Earth & Life Science", "Climatology", "Climate Modeling")]
        assert any("Climate Modeling" in w and "Climate Modelling" in w for w in warnings)

    def test_numbers_stored_as_floats_and_text_are_accepted(self, sheet_mod, ctx, sheet):
        from openpyxl import load_workbook
        ws = load_workbook(sheet)["C01"]
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), ("C01", f"A{row_of(ws, 101)}", 101.0),
                   ("C01", f"A{row_of(ws, 102)}", " 102 "))
        assert read_groups(sheet_mod, ctx, sheet)[0] == {OCEAN_PATH: [101, 102]}

    @pytest.mark.parametrize("levels,error", [
        (["Engineering & Technology"], "da 2 a 4"),
        (["Engineering & Technology", "", "Arms"], "buchi"),
        (["Unlabelled", "Arms"], "Unlabelled"),
        (["Engineering & Technology", "Climatology", "Arms"], "un solo padre"),
        (["Earth & Life Science", "Climatology"], "categoria"),
        (["Engineering & Technology", "Robotics", "Arms"], "non può avere figli"),
        (["Engineering & Technology", "Arms", "Arms"], "due volte"),
    ])
    def test_invalid_paths(self, sheet_mod, ctx, sheet, levels, error):
        edit_sheet(sheet, *set_path("C01", levels))
        with pytest.raises(sheet_mod.SheetError, match=error) as e:
            read_groups(sheet_mod, ctx, sheet)
        assert "1 error" in str(e.value)

    def test_new_paths_are_checked_against_each_other(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, *set_path("C01", ["Engineering & Technology", "Arms"]),
                   *set_path("C02", ["Earth & Life Science", "Arms"]))
        with pytest.raises(sheet_mod.SheetError, match="un solo padre"):
            read_groups(sheet_mod, ctx, sheet)

    def test_all_errors_are_reported_together(self, sheet_mod, ctx, sheet):
        edit_sheet(sheet, ("C01", "B4", "Engineering & Technology"), ("C01", "C4", ""), ("C01", "D4", "X"),
                   ("C02", "A20", 999), ("C02", "A21", 101), ("Isolati", "E9", "Unlabelled"), ("Isolati", "F9", "Y"))
        with pytest.raises(sheet_mod.SheetError) as e:
            read_groups(sheet_mod, ctx, sheet)
        message = str(e.value)
        assert "4 error" in message
        for fragment in ("C01!B4", "C02!A20", "999", "C02!A21", "compare anche in C01", "Isolati!E9"):
            assert fragment in message

    def test_project_not_in_the_db(self, sheet_mod, ctx, sheet):
        ctx.project_ids = ctx.project_ids[:-1] + [777]
        with pytest.raises(sheet_mod.SheetError, match="non presente nel db") as e:
            read_groups(sheet_mod, ctx, sheet)
        assert "106" in str(e.value)

    def test_projects_must_still_have_the_provisional_topic(self, sheet_mod, ctx, sheet):
        ctx.current_names = {101: "Climate Modelling", 102: "Robotics", 103: "Wireless Networks",
                             104: "Wireless Networks", 106: "Robotics"}
        with pytest.raises(sheet_mod.SheetError, match="già stato applicato") as e:
            read_groups(sheet_mod, ctx, sheet)
        assert "C01!A" in str(e.value) and "102" in str(e.value) and "1 error" in str(e.value)

    def test_deleting_the_row_of_a_moved_project_is_the_way_out(self, sheet_mod, ctx, sheet):
        from openpyxl import load_workbook
        wb = load_workbook(sheet)
        wb["C01"].delete_rows(row_of(wb["C01"], 102))
        wb.save(sheet)
        ctx.current_names = {101: "Climate Modelling", 102: "Robotics", 103: "Wireless Networks",
                             104: "Wireless Networks", 106: "Robotics"}
        assert read_groups(sheet_mod, ctx, sheet) == ({}, [])

    def test_sheet_project_ids(self, sheet_mod, sheet):
        assert sheet_mod.sheet_project_ids(str(sheet)) == [101, 102, 103, 104, 106]

    def test_sheet_project_ids_ignores_garbage(self, sheet_mod, sheet):
        edit_sheet(sheet, ("C01", "A30", "boh"), ("C01", "A31", 205.0))
        assert sheet_mod.sheet_project_ids(str(sheet)) == [101, 102, 103, 104, 106, 205]

    def test_not_a_spreadsheet(self, sheet_mod, ctx, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_text("non è un foglio")
        with pytest.raises(sheet_mod.SheetError, match="impossibile leggere"):
            read_groups(sheet_mod, ctx, bad)


class TestReviewAndApply:
    @pytest.fixture
    def saves(self, review_mod, monkeypatch):
        calls = []
        monkeypatch.setattr(review_mod, "save_with_backup", lambda *a: calls.append(a) or "stamp")
        return calls

    def _run(self, review_mod, ctx, tmp_path, mode, sheet=None):
        return review_mod.review_and_apply(ctx, mode, str(sheet or tmp_path / "review.xlsx"),
                                           str(tmp_path / "model"), str(tmp_path / "h.json"),
                                           str(tmp_path / "backups"))

    def test_none_keeps_nearest(self, review_mod, ctx, tmp_path, saves):
        topics, moves = self._run(review_mod, ctx, tmp_path, "none")
        assert topics.tolist() == ctx.topics.tolist() and moves.empty
        assert saves == [] and not (tmp_path / "review.xlsx").exists()

    def test_provisional_writes_the_sheet_and_changes_nothing(self, review_mod, ctx, tmp_path, saves):
        topics, moves = self._run(review_mod, ctx, tmp_path, "provisional")
        assert topics.tolist() == ctx.topics.tolist() and moves.empty
        assert (tmp_path / "review.xlsx").exists() and saves == []
        assert ctx.model.topic_embeddings_.shape == (4, 5) and ctx.reviewed_topics == set()

    def test_sheet_applies_and_saves(self, review_mod, ctx, tmp_path, saves, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH))
        topics, _ = self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert topics.tolist()[:2] == [3, 3]
        assert len(saves) == 1
        assert saves[0][-1] == {3} and ctx.reviewed_topics == {3}
        assert ctx.hierarchy.path(3) == OCEAN_PATH

    def test_sheet_with_existing_paths_only_does_not_save(self, review_mod, ctx, tmp_path, saves, sheet):
        edit_sheet(sheet, *set_path("C01", P_ROBOTICS))
        topics, _ = self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert topics.tolist()[:2] == [2, 2] and saves == []

    def test_empty_sheet_keeps_nearest(self, review_mod, ctx, tmp_path, saves, sheet):
        topics, moves = self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert topics.tolist() == ctx.topics.tolist() and moves.empty and saves == []

    def test_errors_apply_nothing(self, review_mod, ctx, tmp_path, saves, sheet):
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH), *set_path("C02", ["Only one"]))
        with pytest.raises(review_mod.SheetError):
            self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert saves == [] and ctx.model.topic_embeddings_.shape == (4, 5)
        assert ctx.hierarchy.to_json() == SMALL_HIER

    def test_sheet_warnings_are_printed(self, review_mod, ctx, tmp_path, saves, sheet, capsys):
        edit_sheet(sheet, *set_path("C01", ["earth & life science", "climatology", "climate modelling"]))
        self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert "WARNING" in capsys.readouterr().out

    def test_invalid_mode(self, review_mod, ctx, tmp_path):
        with pytest.raises(ValueError):
            self._run(review_mod, ctx, tmp_path, "boh")
        with pytest.raises(ValueError):
            self._run(review_mod, ctx, tmp_path, "interactive")

    def test_provisional_without_candidates(self, review_mod, batch, tmp_path, saves, capsys):
        empty = make_ctx(review_mod, batch, [])
        topics, moves = self._run(review_mod, empty, tmp_path, "provisional")
        assert topics.tolist() == batch.topics.tolist() and moves.empty
        assert not (tmp_path / "review.xlsx").exists()
        assert "No candidate new topics" in capsys.readouterr().out

    def test_unset_topics_stay_unset(self, review_mod, ctx, tmp_path, saves, sheet):
        """Applicato ai progetti già nel db: chi il foglio non tocca resta UNSET (nessuna riscrittura)."""
        ctx.topics = np.full(len(ctx.project_ids), review_mod.UNSET)
        edit_sheet(sheet, *set_path("C01", OCEAN_PATH))
        topics, _ = self._run(review_mod, ctx, tmp_path, "sheet", sheet)
        assert topics.tolist() == [3, 3] + [review_mod.UNSET] * 4


def _pad(path):
    return ["Unlabelled"] * (4 - len(path)) + list(reversed(path))


def _existing(review_mod, rows):
    """rows: (projectID, embedding, titolo, percorso attuale)."""
    return review_mod.ExistingProjects(
        project_ids=np.array([r[0] for r in rows]),
        embeddings=np.array([r[1] for r in rows], dtype="float32"),
        titles=[r[2] for r in rows],
        hierarchies=[_pad(r[3]) for r in rows],
    )


# modello con gli embedding di TOPIC_EMBS (-1, 0, 1, 2) e gerarchia SMALL_HIER
EXISTING_ROWS = [
    (1, [1, 1, 0, 0], "On the target", P_CLIMATE),        # sim 0.71 con Climate, 1.0 con il target
    (2, [1, 0, 0, 0], "Pure climate", P_CLIMATE),          # sopra soglia: non si tocca
    (3, [1, 0.8, 0, 0], "Close to target", P_WIRELESS),    # sim 0.78, 0.99 con il target
    (4, [0, 0, 1, 0.2], "Robotics", P_ROBOTICS),           # sopra soglia
]
OCEAN_CENTROID = np.array([1, 1, 0, 0], dtype=float)


@pytest.fixture
def plain_model():
    return SimpleNamespace(_outliers=1, topic_embeddings_=TOPIC_EMBS.copy())


class TestExistingMoves:
    def _moves(self, review_mod, model, rows=EXISTING_ROWS, bonus=-0.005, reviewed=(), **kw):
        target = review_mod.Target(key="ocean", centroid=OCEAN_CENTROID, path=tuple(OCEAN_PATH), bonus=bonus)
        return review_mod.existing_moves(model, set(reviewed), _existing(review_mod, rows), [target],
                                         0.92, -0.005, **kw)

    def test_only_projects_below_threshold_move(self, review_mod, plain_model):
        moves = self._moves(review_mod, plain_model)
        assert moves["projectID"].tolist() == [1, 3], "dal più sicuro al più incerto"
        assert list(moves.columns) == review_mod.MOVE_COLUMNS

    def test_move_content(self, review_mod, plain_model):
        m = self._moves(review_mod, plain_model).iloc[1]
        assert m["title"] == "Close to target"
        assert m["from_topic"] == "Wireless Networks" and m["from_hierarchy"] == _pad(P_WIRELESS)
        assert m["topic_name"] == "Ocean Acidification" and m["topic_name_hierarchy"] == _pad(OCEAN_PATH)
        assert m["key"] == "ocean" and m["topic_id"] is None
        assert m["similarity"] == pytest.approx(1.8 / np.sqrt(1.64) / np.sqrt(2))
        assert m["best_original"] == pytest.approx(1 / np.sqrt(1.64))

    def test_bonus_is_the_required_margin(self, review_mod, plain_model):
        margin = 1 - 1 / np.sqrt(2)          # progetto 1: sim 1.0 con il target, 0.707 con Climate
        rows = EXISTING_ROWS[:1]
        assert len(self._moves(review_mod, plain_model, rows, bonus=-margin + 1e-6)) == 1
        assert len(self._moves(review_mod, plain_model, rows, bonus=-margin - 1e-6)) == 0

    def test_lower_bonus_moves_fewer_projects(self, review_mod, plain_model):
        counts = [len(self._moves(review_mod, plain_model, bonus=b)) for b in (0.02, -0.005, -0.25, -0.5)]
        assert counts == sorted(counts, reverse=True) and counts[0] == 2 and counts[-1] == 0

    def test_projects_already_on_target_are_skipped(self, review_mod, plain_model):
        rows = [(1, [1, 1, 0, 0], "Already ocean", tuple(OCEAN_PATH))] + EXISTING_ROWS[1:]
        assert self._moves(review_mod, plain_model, rows)["projectID"].tolist() == [3]

    def test_previous_reviewed_topic_competes(self, review_mod, plain_model):
        """Un topic di una revisione precedente identico al target vince il pareggio: il progetto resta."""
        plain_model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [[1, 1, 0, 0]]]).astype("float32")
        assert self._moves(review_mod, plain_model, reviewed={3})["projectID"].tolist() == []
        assert self._moves(review_mod, plain_model, reviewed={3}, competitors=set())["projectID"].tolist() == [1, 3]

    def test_reviewed_topics_do_not_count_as_original(self, review_mod, plain_model):
        """La soglia si misura sui topic originali: un topic revisionato vicino non la alza."""
        plain_model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [[1, 1, 0, 0]]]).astype("float32")
        moves = self._moves(review_mod, plain_model, reviewed={3}, competitors=set())
        assert moves["best_original"].max() < 0.92

    def test_target_already_in_model_is_not_its_own_rival(self, review_mod, plain_model):
        plain_model.topic_embeddings_ = np.vstack([TOPIC_EMBS, [[1, 1, 0, 0]]]).astype("float32")
        target = review_mod.Target(key=3, centroid=OCEAN_CENTROID, path=tuple(OCEAN_PATH), bonus=-0.005, topic_id=3)
        moves = review_mod.existing_moves(plain_model, {3}, _existing(review_mod, EXISTING_ROWS), [target],
                                          0.92, -0.005)
        assert moves["projectID"].tolist() == [1, 3] and set(moves["topic_id"]) == {3}

    def test_each_project_goes_to_the_best_target(self, review_mod, plain_model):
        rows = EXISTING_ROWS + [(5, [0, 1, 0.9, 0], "Between wireless and robotics", P_WIRELESS)]
        targets = [review_mod.Target("ocean", OCEAN_CENTROID, tuple(OCEAN_PATH), -0.005),
                   review_mod.Target("other", np.array([0, 1, 1, 0.0]), ("Engineering & Technology", "Mixed"), -0.005)]
        moves = review_mod.existing_moves(plain_model, set(), _existing(review_mod, rows), targets, 0.92, -0.005)
        assert dict(zip(moves["projectID"], moves["key"])) == {1: "ocean", 3: "ocean", 5: "other"}
        assert moves["key"].tolist() == ["ocean", "ocean", "other"], "ordinati per target"

    def test_chunks_give_the_same_result(self, review_mod, plain_model):
        a = self._moves(review_mod, plain_model)
        b = self._moves(review_mod, plain_model, chunk=1)
        pd.testing.assert_frame_equal(a, b)

    def test_nothing_to_do(self, review_mod, plain_model):
        assert review_mod.existing_moves(plain_model, set(), None, [], 0.92, 0).empty
        empty = review_mod.existing_moves(plain_model, set(), _existing(review_mod, EXISTING_ROWS), [], 0.92, 0)
        assert empty.empty and list(empty.columns) == review_mod.MOVE_COLUMNS


# progetti già nel db per il batch di prova (embedding a 5 dimensioni, come il batch)
BATCH_EXISTING_ROWS = [
    (501, [0.6, 0.1, 0, 0, 0.5], "Old reef study", P_CLIMATE),   # sim 0.76 con Climate, 0.92 con il cluster 0
    (502, [0, 0, 1, 0, 0], "Old robot", P_ROBOTICS),              # sopra soglia
    (503, [0, 1, 0, 0, 0.05], "Old antenna", P_WIRELESS),         # sopra soglia
]


@pytest.fixture
def ctx_existing(review_mod, ctx):
    ctx.existing = _existing(review_mod, BATCH_EXISTING_ROWS)
    return ctx


class TestReviewAndApplyExisting:
    """I topic nuovi prendono sempre i progetti già nel db che gli somigliano, con il bonus fisso."""

    @pytest.fixture
    def saves(self, review_mod, monkeypatch):
        calls = []
        monkeypatch.setattr(review_mod, "save_with_backup", lambda *a: calls.append(a) or "stamp")
        return calls

    def _apply(self, review_mod, ctx, sheet, *edits):
        edit_sheet(sheet, *edits)
        return review_mod.review_and_apply(ctx, "sheet", str(sheet), "m", "h", "b")

    def test_new_topic_takes_existing_projects(self, review_mod, ctx_existing, sheet, saves):
        topics, moves = self._apply(review_mod, ctx_existing, sheet, *set_path("C01", OCEAN_PATH))
        assert topics.tolist()[:2] == [3, 3]
        assert moves["projectID"].tolist() == [501]
        m = moves.iloc[0]
        assert m["topic_id"] == 3 and m["topic_name"] == "Ocean Acidification"
        assert m["topic_name_hierarchy"] == _pad(OCEAN_PATH)

    def test_strict_bonus_moves_nothing(self, review_mod, ctx_existing, sheet, saves):
        ctx_existing.existing_bonus = -0.2
        _, moves = self._apply(review_mod, ctx_existing, sheet, *set_path("C01", OCEAN_PATH))
        assert moves.empty

    def test_existing_topic_and_unlabelled_take_nothing(self, review_mod, ctx_existing, sheet, saves):
        _, moves = self._apply(review_mod, ctx_existing, sheet, *set_path("C01", P_ROBOTICS),
                               ("C02", "B4", "Unlabelled"))
        assert moves.empty

    def test_isolated_projects_with_a_new_path_form_a_topic_too(self, review_mod, ctx_existing, sheet, saves):
        _, moves = self._apply(review_mod, ctx_existing, sheet,
                               *set_path("Isolati", ["Earth & Life Science", "Reefs"], row=9, first_col="E"))
        assert set(moves["topic_name"]) <= {"Reefs"}

    def test_none_mode_moves_nothing(self, review_mod, ctx_existing):
        topics, moves = review_mod.review_and_apply(ctx_existing, "none", "s.xlsx", "m", "h", "b")
        assert moves.empty and topics.tolist() == ctx_existing.topics.tolist()

    def test_warning_without_store(self, review_mod, ctx, sheet, saves, capsys):
        _, moves = self._apply(review_mod, ctx, sheet, *set_path("C01", OCEAN_PATH))
        assert moves.empty
        assert "no Specter2 embeddings" in capsys.readouterr().out


# ==============================================================================
# 2.9 UNIT TEST: lance_maintenance.py (tabelle lette dalla dashboard)
# ==============================================================================
@pytest.fixture
def maint_mod(monkeypatch):
    pytest.importorskip("lancedb")
    return load_module(monkeypatch, "lance_maintenance", HERE / "lance_maintenance.py")


def _vectors(rng, n, dim=16):
    import pyarrow as pa
    return pa.FixedSizeListArray.from_arrays(pa.array(rng.normal(size=n * dim).astype("float32")), dim)


def make_old_style_db(path, n=300, vector_index=True, dictionaries=True):
    """Db come quello originale aggiornato dalla vecchia pipeline: colonne dictionary,
    righe aggiunte in un secondo frammento, indice IVF_PQ sul vettore."""
    import pyarrow as pa
    from lancedb.index import IvfPq
    rng = np.random.default_rng(0)
    db = connect(path)
    enc = (lambda a: a.dictionary_encode()) if dictionaries else (lambda a: a)
    projects = pa.table({
        "projectID": pa.array(range(n), pa.int32()),
        "topic_name": enc(pa.array([f"T{i % 5}" for i in range(n)])),
        "topic_name_hierarchy": pa.array([[f"T{i % 5}", "Root"] for i in range(n)]),
        "vector": _vectors(rng, n),
    })
    t = db.create_table("projects_uncase", data=projects)
    t.add(pd.DataFrame({"projectID": np.arange(n, n + 20, dtype="int32"),
                        "topic_name": ["T9"] * 10 + ["T1"] * 10,
                        "topic_name_hierarchy": [["T9", "Root"]] * 20,
                        "vector": list(rng.normal(size=(20, 16)).astype("float32"))}))
    if vector_index:
        t.create_index("vector", config=IvfPq(distance_type="cosine", num_partitions=2, num_sub_vectors=4))
    m = n + 20
    participants = pa.table({
        "projectID": pa.array(range(m), pa.int32()),
        "organisationID": pa.array(range(m), pa.int32()),
        "countryCode": pa.array(["IT", "DE"] * (m // 2)),
        "activityType": pa.array(["REC", "HES"] * (m // 2)),
        "role": enc(pa.array(["coordinator", "participant"] * (m // 2))),
        "fp": pa.array([9] * m, pa.int8()),
        "topic_name": enc(pa.array([f"T{i % 5}" for i in range(m)])),
        "name": pa.array([f"Org {i}" for i in range(m)]),
    })
    p = db.create_table("participants", data=participants)
    p.add(pd.DataFrame({"projectID": [m, m + 1], "organisationID": [m, m + 1], "countryCode": ["FR", "ES"],
                        "activityType": ["PRC", "PUB"], "role": ["partner", "coordinator"],
                        "fp": np.array([9, 9], dtype="int8"), "topic_name": ["T9", "T0"], "name": ["X", "Y"]}))
    return db


def _mixed_search(db):
    """Ricerca come quella della dashboard, con risultati da entrambi i frammenti."""
    t = db.open_table("projects_uncase")
    query = np.random.default_rng(1).normal(size=16).astype("float32")
    return t.search(query).metric("cosine").limit(t.count_rows()).to_pandas()


class TestLanceMaintenance:
    def test_old_style_db_reproduces_dashboard_failure(self, tmp_path):
        """Precondizione: il db di prova riproduce l'errore visto nella dashboard."""
        db = make_old_style_db(tmp_path / "db", vector_index=False)
        try:
            _mixed_search(db)
        except ValueError as e:
            assert "Categorical categories must be unique" in str(e)
        else:
            pytest.skip("questa versione di LanceDB non riproduce più l'errore sulle colonne dictionary")

    def test_repair_fixes_both_problems(self, maint_mod, tmp_path):
        import pyarrow as pa
        db = make_old_style_db(tmp_path / "db")
        before = {n: maint_mod.decode_dictionaries(db.open_table(n).to_arrow()) for n in maint_mod.TABLES}

        changes = maint_mod.repair_tables(db, verbose=False)

        assert changes["projects_uncase"] and changes["participants"]
        for name in maint_mod.TABLES:
            t = db.open_table(name)
            assert not [f.name for f in t.schema if pa.types.is_dictionary(f.type)]
            assert maint_mod.vector_indexes(t) == []
            after = t.to_arrow()
            key = [("projectID", "ascending")]
            assert after.sort_by(key).equals(before[name].sort_by(key)), "i dati non devono cambiare"
            assert [f.name for f in after.schema] == [f.name for f in before[name].schema]
        assert indexed_columns(db.open_table("projects_uncase")) == {"projectID", "topic_name_hierarchy"}
        assert indexed_columns(db.open_table("participants")) == {"countryCode", "activityType", "fp", "projectID"}

        res = _mixed_search(db)
        V = np.stack(res["vector"].to_numpy())
        q = np.random.default_rng(1).normal(size=16).astype("float32")
        true = 1 - (V @ q) / (np.linalg.norm(V, axis=1) * np.linalg.norm(q))
        assert np.allclose(res["_distance"], true, atol=1e-4), "senza indice le distanze sono esatte"

    def test_repair_is_idempotent(self, maint_mod, tmp_path):
        db = make_old_style_db(tmp_path / "db")
        maint_mod.repair_tables(db, verbose=False)
        versions = {n: db.open_table(n).version for n in maint_mod.TABLES}
        assert maint_mod.repair_tables(db, verbose=False) == {n: [] for n in maint_mod.TABLES}
        assert {n: db.open_table(n).version for n in maint_mod.TABLES} == versions

    def test_previous_version_still_readable(self, maint_mod, tmp_path):
        db = make_old_style_db(tmp_path / "db")
        version = db.open_table("projects_uncase").version
        maint_mod.repair_tables(db, verbose=False)
        old = db.open_table("projects_uncase")
        old.checkout(version)
        assert old.count_rows() == 320

    def test_only_vector_index(self, maint_mod, tmp_path):
        db = make_old_style_db(tmp_path / "db", dictionaries=False)
        version = db.open_table("projects_uncase").version
        changes = maint_mod.repair_table(db, "projects_uncase", verbose=False)
        assert len(changes) == 1 and "vector index" in changes[0]
        t = db.open_table("projects_uncase")
        assert maint_mod.vector_indexes(t) == [] and t.count_rows() == 320
        assert t.version == version + 1, "basta togliere l'indice, senza riscrivere la tabella"

    def test_command_line(self, maint_mod, tmp_path, monkeypatch, capsys):
        make_old_style_db(tmp_path / "db")
        for expected in ("converted to string", "already OK"):
            monkeypatch.setattr(sys, "argv", ["lance_maintenance.py", "--data", str(tmp_path / "db")])
            runpy.run_path(str(HERE / "lance_maintenance.py"), run_name="__main__")
            assert expected in capsys.readouterr().out


class TestUpdateRepairsOldStyleDb:
    """update_db ripara un db aggiornato con la vecchia pipeline prima di scriverci."""

    def _make_old_style(self, sb):
        import pyarrow as pa
        from lancedb.index import IvfPq
        db = sb.db()
        for name, cols in (("projects_uncase", ["topic_name"]), ("participants", ["role", "topic_name"])):
            data = db.open_table(name).to_arrow()
            for c in cols:
                i = data.schema.get_field_index(c)
                data = data.set_column(i, c, data.column(i).dictionary_encode())
            db.create_table(name, data=data, mode="overwrite")
        db.open_table("projects_uncase").create_index(
            "vector", config=IvfPq(distance_type="cosine", num_partitions=2, num_sub_vectors=16))

    def test_update_repairs_tables(self, sandbox, run_update, capsys):
        import pyarrow as pa
        self._make_old_style(sandbox)
        assert run_update(sandbox, "--projects").code == 0
        assert run_update(sandbox, "--participants").code == 0
        assert "converted to string" in capsys.readouterr().out
        for name in ("projects_uncase", "participants"):
            t = sandbox.table(name)
            assert not [f.name for f in t.schema if pa.types.is_dictionary(f.type)], name
            assert "vector" not in indexed_columns(t)
            t.to_pandas()
        rows = sandbox.df("projects_uncase").set_index("projectID")
        query = np.asarray(rows.loc[sandbox.new_ids[0], "vector"], dtype="float32")
        res = sandbox.table("projects_uncase").search(query).metric("cosine").limit(5).to_pandas()
        assert res["projectID"].iloc[0] == sandbox.new_ids[0]
        assert res["_distance"].iloc[0] == pytest.approx(0, abs=1e-4)


# ==============================================================================
# 2.10 UNIT TEST: specter_store.py e spostamento dei progetti già nel db (topic_review.py)
# ==============================================================================
@pytest.fixture
def store_mod(monkeypatch):
    pytest.importorskip("pyarrow")
    return load_module(monkeypatch, "specter_store", HERE / "specter_store.py")


class TestSpecterStore:
    def test_missing_store(self, store_mod, tmp_path):
        assert store_mod.load_store(str(tmp_path / "nope.parquet")) is None
        assert store_mod.load_store("") is None

    def test_roundtrip(self, store_mod, tmp_path):
        import pyarrow.parquet as pq
        path = str(tmp_path / "s.parquet")
        embs = np.arange(6, dtype="float32").reshape(2, 3)
        assert store_mod.update_store(path, np.array([7, 8], dtype=np.int64), embs) == 2
        ids, got = store_mod.load_store(path)
        assert ids.tolist() == [7, 8] and np.array_equal(got, embs) and got.dtype == np.float32
        schema = pq.read_schema(path)
        assert str(schema.field("projectID").type) == "int32"
        assert schema.field("vector").type.list_size == 3
        assert not (tmp_path / "s.parquet.tmp").exists()

    def test_reads_pandas_written_store(self, store_mod, tmp_path):
        """Un parquet scritto da pandas (vector come lista variabile, indice in più) si legge lo stesso."""
        path = tmp_path / "s.parquet"
        embs = np.arange(6, dtype="float32").reshape(2, 3)
        pd.DataFrame({"projectID": np.array([7, 8], dtype="int32"), "vector": list(embs)},
                     index=[10, 11]).to_parquet(path)
        ids, got = store_mod.load_store(str(path))
        assert ids.tolist() == [7, 8] and np.array_equal(got, embs)

    def test_embeddings_for_follows_project_ids(self, store_mod, tmp_path):
        path = str(tmp_path / "s.parquet")
        store_mod.update_store(path, [1, 2, 3], np.arange(9, dtype="float32").reshape(3, 3))
        got = store_mod.embeddings_for(path, [3, 1])
        assert got[:, 0].tolist() == [6, 0]

    def test_embeddings_for_errors(self, store_mod, tmp_path):
        path = str(tmp_path / "s.parquet")
        with pytest.raises(ValueError, match="non trovato"):
            store_mod.embeddings_for(path, [1])
        store_mod.update_store(path, [1, 2], np.ones((2, 3)))
        with pytest.raises(ValueError, match="senza embedding"):
            store_mod.embeddings_for(path, [1, 5])
        with pytest.raises(ValueError, match="npy"):
            store_mod.embeddings_for(str(tmp_path / "x.npy"), [1])

    def test_update_appends_and_replaces(self, store_mod, tmp_path):
        path = str(tmp_path / "s.parquet")
        store_mod.update_store(path, [1, 2], np.ones((2, 3)))
        assert store_mod.update_store(path, [2, 3], np.full((2, 3), 5.0)) == 3
        ids, embs = store_mod.load_store(path)
        assert ids.tolist() == [1, 2, 3]
        assert embs[:, 0].tolist() == [1, 5, 5], "il progetto 2 prende l'embedding nuovo"

    @pytest.mark.parametrize("ids,embs,error", [
        ([1, 2], np.ones((3, 3)), "progetti"),
        ([9], np.ones((1, 4)), "dimensione"),
    ])
    def test_invalid_input_leaves_store_untouched(self, store_mod, tmp_path, ids, embs, error):
        path = str(tmp_path / "s.parquet")
        store_mod.update_store(path, [1], np.ones((1, 3)))
        with pytest.raises(ValueError, match=error):
            store_mod.update_store(path, ids, embs)
        assert store_mod.load_store(path)[0].tolist() == [1]

    def test_real_store_has_the_same_format(self, store_mod):
        import pyarrow as pa
        import pyarrow.parquet as pq
        path = REAL_DATA / "specter2.parquet"
        if not path.exists():
            pytest.skip("data/specter2.parquet non trovato")
        schema = pq.read_schema(path)
        assert schema.names == ["projectID", "vector"]
        assert schema.field("projectID").type == pa.int32()
        vec = schema.field("vector").type
        assert pa.types.is_fixed_size_list(vec) and vec.list_size == 768 and vec.value_type == pa.float32()


# db minimo: 501 e 503 sono vicini al topic revisionato 3, 502 è un progetto Climate tipico
SMALL_DB_ROWS = [
    (501, "Reef and wireless", P_CLIMATE, ["Org A", "Org B"], [1, 1, 0, 0]),
    (502, "Pure climate", P_CLIMATE, ["Org A"], [1, 0, 0, 0]),
    (503, "Close to reef", P_WIRELESS, ["Org B"], [1, 0.8, 0, 0]),
    (504, "No embedding", P_ROBOTICS, ["Org C"], None),
]


@pytest.fixture
def small_db(tmp_path, store_mod, review_mod):
    pytest.importorskip("lancedb")
    import pyarrow as pa
    db = connect(tmp_path / "db")
    hier_type = pa.list_(pa.string())
    rows = SMALL_DB_ROWS
    db.create_table("projects_uncase", data=pa.table({
        "projectID": pa.array([r[0] for r in rows], pa.int32()),
        "title": [r[1] for r in rows],
        "topic_name": [r[2][-1] for r in rows],
        "topic_name_hierarchy": pa.array([_pad(r[2]) for r in rows], hier_type),
        "participants": pa.array([r[3] for r in rows], hier_type),
    }))
    parts = [(r[0], name, r[2]) for r in rows for name in r[3]]
    db.create_table("participants", data=pa.table({
        "projectID": pa.array([p[0] for p in parts], pa.int32()),
        "name": [p[1] for p in parts],
        "topic_name": [p[2][-1] for p in parts],
        "topic_name_hierarchy": pa.array([_pad(p[2]) for p in parts], hier_type),
    }))
    with_emb = [r for r in rows if r[4] is not None]
    store = tmp_path / "specter2.parquet"
    store_mod.update_store(str(store), [r[0] for r in with_emb], np.array([r[4] for r in with_emb]))
    model = SimpleNamespace(_outliers=1, topic_embeddings_=np.vstack(
        [TOPIC_EMBS, [[1, 1, 0, 0], [0, 0, 0.5, 1]]]).astype("float32"))
    return SimpleNamespace(db=db, store=str(store), model=model, reviewed={3, 4},
                           graphs=tmp_path / "graphs", logs=tmp_path / "logs")


def _topics(db, table):
    df = db.open_table(table).to_pandas()
    return {int(p): (n, list(h)) for p, n, h in zip(df["projectID"], df["topic_name"], df["topic_name_hierarchy"])}


class TestMovesInTheDb:
    def _moves(self, review_mod, s, bonus=-0.005):
        existing = review_mod.load_existing(s.db.open_table("projects_uncase"), s.store)
        target = review_mod.Target(key=3, centroid=s.model.topic_embeddings_[4], path=OCEAN_PATH, bonus=bonus,
                                   topic_id=3)
        return review_mod.existing_moves(s.model, s.reviewed, existing, [target], 0.92, bonus)

    def test_load_existing(self, review_mod, small_db, capsys):
        ex = review_mod.load_existing(small_db.db.open_table("projects_uncase"), small_db.store, exclude_ids=[503])
        assert ex.project_ids.tolist() == [501, 502]
        assert np.allclose(ex.embeddings, [[1, 1, 0, 0], [1, 0, 0, 0]])
        assert ex.titles == ["Reef and wireless", "Pure climate"]
        assert ex.hierarchies[0] == _pad(P_CLIMATE)
        assert "1 projects in the db have no Specter2 embedding" in capsys.readouterr().out
        assert review_mod.load_existing(small_db.db.open_table("projects_uncase"), "/nope.parquet") is None

    def test_write_moves_updates_both_tables(self, review_mod, small_db):
        before = {t: _topics(small_db.db, t) for t in ("projects_uncase", "participants")}
        moves = self._moves(review_mod, small_db)
        assert moves["projectID"].tolist() == [501, 503]
        review_mod.write_moves(small_db.db, moves, str(small_db.logs))
        for table in ("projects_uncase", "participants"):
            after = _topics(small_db.db, table)
            for pid in (501, 503):
                assert after[pid] == ("Ocean Acidification", _pad(OCEAN_PATH)), (table, pid)
            for pid in (502, 504):
                assert after[pid] == before[table][pid], "gli altri progetti non cambiano"
        assert len(small_db.db.open_table("participants").to_pandas()) == 5, "nessuna riga aggiunta o tolta"

    def test_log_allows_rollback(self, review_mod, small_db):
        versions = {t: small_db.db.open_table(t).version for t in ("projects_uncase", "participants")}
        review_mod.write_moves(small_db.db, self._moves(review_mod, small_db), str(small_db.logs),
                               note={"topics": [3]})
        [log_path] = list(small_db.logs.iterdir())
        log = json.loads(log_path.read_text())
        assert log["versions_before"] == versions and log["note"] == {"topics": [3]}
        assert {m["projectID"]: m["from"] for m in log["moves"]} == {501: _pad(P_CLIMATE), 503: _pad(P_WIRELESS)}
        assert all(m["topic_id"] == 3 and m["to"] == _pad(OCEAN_PATH) for m in log["moves"])
        # le versioni nel log riportano la tabella com'era
        tbl = small_db.db.open_table("projects_uncase")
        tbl.checkout(log["versions_before"]["projects_uncase"])
        assert set(tbl.to_pandas()["topic_name"]) == {"Climate Modelling", "Wireless Networks", "Robotics"}

    def test_graphs_rebuilt(self, review_mod, small_db):
        review_mod.write_moves(small_db.db, self._moves(review_mod, small_db), str(small_db.logs))
        review_mod.rebuild_project_graphs(small_db.db.open_table("projects_uncase"), str(small_db.graphs))
        index = json.loads((small_db.graphs / "_index.json").read_text())
        graph = json.loads((small_db.graphs / index["Ocean Acidification"]).read_text())
        assert set(graph["nodes"]) == {"501", "503"}
        assert graph["edges"][0]["collaborators"] == ["Org B"]

    def test_no_moves_write_nothing(self, review_mod, small_db):
        before = _topics(small_db.db, "projects_uncase")
        assert review_mod.write_moves(small_db.db, self._moves(review_mod, small_db, bonus=-0.5), str(small_db.logs)) is None
        assert _topics(small_db.db, "projects_uncase") == before and not small_db.logs.exists()

    def test_rerun_is_noop(self, review_mod, small_db):
        review_mod.write_moves(small_db.db, self._moves(review_mod, small_db), str(small_db.logs))
        assert self._moves(review_mod, small_db).empty


class TestApplyReviewSheet:
    """extract_topic.apply_review_sheet: il foglio compilato applicato a progetti già nel db."""

    @pytest.fixture
    def env(self, topic_mod, review_mod, store_mod, batch, ctx, ctx_existing, sheet, tmp_path, monkeypatch):
        pytest.importorskip("lancedb")
        import pyarrow as pa
        # extract_topic usa la sua copia di topic_review: si lavora sui suoi globali
        topic_review = SimpleNamespace(**topic_mod.review_and_apply.__globals__)
        saves = []
        monkeypatch.setitem(topic_mod.review_and_apply.__globals__, "save_with_backup",
                            lambda *a: saves.append(a) or "stamp")
        hier_file = tmp_path / "topic2hier.json"
        hier_file.write_text(json.dumps(SMALL_HIER))
        monkeypatch.setattr(topic_mod, "TOPIC_HIER_DICT_DIR", str(hier_file))
        monkeypatch.setattr(topic_mod, "OLD_TOPIC_MODEL_DIR", str(tmp_path / "model"))
        monkeypatch.setattr(topic_mod, "BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setattr(topic_mod, "BERTopic",
                            SimpleNamespace(load=lambda path: make_updatable_model(CORPUS)))

        provisional = {101: P_CLIMATE, 102: P_CLIMATE, 103: P_WIRELESS, 104: P_WIRELESS, 105: P_ROBOTICS,
                       106: P_ROBOTICS}
        rows = [(p, ctx.titles[i], ctx.objectives[i], provisional[p]) for i, p in enumerate(batch.ids)]
        rows += [(r[0], r[2], "obj", r[3]) for r in BATCH_EXISTING_ROWS]
        db = connect(tmp_path / "db")
        db.create_table("projects_uncase", data=pa.table({
            "projectID": pa.array([r[0] for r in rows], pa.int32()),
            "title": [r[1] for r in rows], "objective": [r[2] for r in rows],
            "topic_name": [r[3][-1] for r in rows],
            "topic_name_hierarchy": pa.array([_pad(r[3]) for r in rows], pa.list_(pa.string())),
        }))
        db.create_table("participants", data=pa.table({
            "projectID": pa.array([r[0] for r in rows], pa.int32()),
            "topic_name": [r[3][-1] for r in rows],
            "topic_name_hierarchy": pa.array([_pad(r[3]) for r in rows], pa.list_(pa.string())),
        }))
        store = tmp_path / "specter2.parquet"
        ids = batch.ids + [r[0] for r in BATCH_EXISTING_ROWS]
        vectors = np.vstack([batch.embs, np.array([r[1] for r in BATCH_EXISTING_ROWS], dtype="float32")])
        store_mod.update_store(str(store), ids, vectors)
        return SimpleNamespace(mod=topic_mod, db=db, sheet=sheet, store=str(store), saves=saves,
                               topic_review=topic_review, logs=str(tmp_path / "logs"))

    def _apply(self, env, *edits, **kw):
        edit_sheet(env.sheet, *edits)
        return env.mod.apply_review_sheet(env.db, str(env.sheet), env.store, **kw)

    def test_new_topic_for_a_cluster_and_old_projects(self, env):
        changes = self._apply(env, *set_path("C01", OCEAN_PATH))
        assert list(changes.columns) == env.topic_review.MOVE_COLUMNS
        assert changes["projectID"].tolist() == [101, 102, 501], "prima i progetti del foglio, poi quelli vecchi"
        sheet_rows = changes.iloc[:2]
        assert (sheet_rows["topic_name"] == "Ocean Acidification").all() and (sheet_rows["topic_id"] == 3).all()
        assert sheet_rows["topic_name_hierarchy"].iloc[0] == _pad(OCEAN_PATH)
        assert sheet_rows["from_hierarchy"].iloc[0] == _pad(P_CLIMATE) and sheet_rows["from_topic"].iloc[0] == "Climate Modelling"
        assert len(env.saves) == 1, "il modello e la gerarchia vengono salvati con backup"

    def test_existing_path_moves_only_the_sheet_projects(self, env):
        changes = self._apply(env, *set_path("C02", P_ROBOTICS))
        assert changes["projectID"].tolist() == [103, 104]
        assert (changes["topic_name"] == "Robotics").all() and (changes["topic_id"] == 2).all()
        assert env.saves == [], "modello e gerarchia non cambiano"

    def test_isolated_unlabelled(self, env):
        changes = self._apply(env, ("Isolati", "E9", "Unlabelled"))
        assert changes["projectID"].tolist() == [106]
        row = changes.iloc[0]
        assert row["topic_name"] == "Unlabelled" and row["topic_id"] == -1 and row["from_topic"] == "Robotics"
        assert env.saves == []

    def test_nothing_to_change(self, env):
        assert self._apply(env).empty and env.saves == []

    def test_cannot_be_applied_twice(self, env):
        changes = self._apply(env, *set_path("C01", OCEAN_PATH))
        env.topic_review.write_moves(env.db, changes, env.logs)
        with pytest.raises(Exception, match="già stato applicato") as e:
            env.mod.apply_review_sheet(env.db, str(env.sheet), env.store)
        assert type(e.value).__name__ == "SheetError"

    def test_unknown_project(self, env):
        with pytest.raises(Exception, match="999") as e:
            self._apply(env, ("C01", "A40", 999))
        assert type(e.value).__name__ == "SheetError" and env.saves == []

    def test_missing_specter_embeddings(self, env, store_mod):
        ids, vectors = store_mod.load_store(env.store)
        keep = ids != 101
        Path(env.store).unlink()
        store_mod.update_store(env.store, ids[keep], vectors[keep])
        with pytest.raises(Exception, match="Specter2") as e:
            self._apply(env, *set_path("C01", OCEAN_PATH))
        assert type(e.value).__name__ == "ReviewAborted" and env.saves == []

    def test_missing_store(self, env):
        Path(env.store).unlink()
        with pytest.raises(Exception, match="Specter2") as e:
            self._apply(env, *set_path("C01", OCEAN_PATH))
        assert type(e.value).__name__ == "ReviewAborted"


# ==============================================================================
# 2.11 UNIT TEST: extract_deliverables.py (rete, pdf e LLM stubbati)
# ==============================================================================
class FakeLLMClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


@pytest.fixture
def xd(monkeypatch):
    pytest.importorskip("httpx")
    pytest.importorskip("dotenv")
    pytest.importorskip("tqdm")
    monkeypatch.syspath_prepend(str(HERE))
    monkeypatch.delitem(sys.modules, "cordis_loader", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    return load_module(monkeypatch, "extract_deliverables_under_test", HERE / "extract_deliverables.py")


def _export(*rows):
    return pd.DataFrame(rows, columns=["id", "projectID", "title", "physUrl"])


class TestExtractDeliverablesScript:
    @pytest.mark.parametrize("raw,expected", [
        ({"Ada": "FBK", "Bob": None}, {"Ada": "FBK", "Bob": "Unknown"}),
        ({}, None), (None, None), (["Ada"], None), ({"": "x"}, None),
    ])
    def test_normalize_authors(self, xd, raw, expected):
        out = xd.normalize_authors(raw)
        assert out == ("{}" if expected is None else json.dumps(expected))

    def test_extract_authors_ok_and_retry(self, xd):
        client = FakeLLMClient(["not json", '{"authors": {"Ada": "FBK"}}'])
        assert asyncio.run(xd.extract_authors(client, "md")) == ('{"Ada": "FBK"}', None)
        assert len(client.calls) == 2

    def test_extract_authors_errors(self, xd):
        authors, err = asyncio.run(xd.extract_authors(FakeLLMClient(["x", "y"]), "md"))
        assert authors == "{}" and "JSON malformato" in err
        authors, err = asyncio.run(xd.extract_authors(FakeLLMClient([RuntimeError("boom")]), "md"))
        assert authors == "{}" and "boom" in err

    def test_authors_null_is_not_an_error(self, xd):
        assert asyncio.run(xd.extract_authors(FakeLLMClient(['{"authors": null}']), "md")) == ("{}", None)

    def test_process_download_failure(self, xd, monkeypatch):
        async def nothing(url):
            return None
        monkeypatch.setattr(xd, "download_pdf", nothing)
        out = asyncio.run(xd.process_deliverable("u", FakeLLMClient([]), asyncio.Semaphore(1)))
        assert out == {"authors": "{}", "status": "error", "error_msg": xd.ERR_PDF}

    @pytest.mark.parametrize("pymupdf_text,expected", [("# md", ["pymupdf"]), (None, ["pymupdf", "docling"])])
    def test_process_falls_back_to_docling(self, xd, monkeypatch, pymupdf_text, expected):
        used = []

        async def pdf(url):
            return b"%PDF"
        monkeypatch.setattr(xd, "download_pdf", pdf)
        monkeypatch.setattr(xd, "pdf_to_markdown_pymupdf", lambda b: used.append("pymupdf") or pymupdf_text)
        monkeypatch.setattr(xd, "pdf_to_markdown_docling", lambda b: used.append("docling") or "# docling")
        client = FakeLLMClient(['{"authors": {"Ada": "FBK"}}'])
        out = asyncio.run(xd.process_deliverable("u", client, asyncio.Semaphore(1)))
        assert used == expected
        assert out == {"authors": '{"Ada": "FBK"}', "status": "ok"}

    def test_process_unreadable_pdf(self, xd, monkeypatch):
        async def pdf(url):
            return b"%PDF"
        monkeypatch.setattr(xd, "download_pdf", pdf)
        monkeypatch.setattr(xd, "pdf_to_markdown_pymupdf", lambda b: None)
        monkeypatch.setattr(xd, "pdf_to_markdown_docling", lambda b: None)
        out = asyncio.run(xd.process_deliverable("u", FakeLLMClient([]), asyncio.Semaphore(1)))
        assert out["status"] == "error" and out["error_msg"] == xd.ERR_PDF

    def test_build_table_known_authors(self, xd):
        export = _export(("a", 1, "A", "u/a"), ("b", 1, "B", "u/b"), ("c", 2, "C", None),
                         ("d", 2, "D", "u/d"), ("e", 3, "E", "u/e"))
        by_id = pd.Series({"a": '{"X": "Y"}'})
        by_url = pd.Series({"u/b": '{"Z": "W"}'})
        t = xd.build_table(export, None, by_id, by_url).set_index("id")
        assert t["status"].to_dict() == {"a": "carried", "b": "carried", "c": "no_url",
                                         "d": "pending", "e": "pending"}
        assert t.loc["a", "authors"] == '{"X": "Y"}' and t.loc["b", "authors"] == '{"Z": "W"}'
        assert t.loc[["c", "d"], "authors"].eq("{}").all()

    def test_build_table_resumes_previous_output(self, xd):
        export = _export(("a", 1, "A", "u/a"), ("b", 1, "B", "u/b"), ("c", 1, "C", "u/c"), ("d", 1, "D", "u/d2"))
        previous = pd.DataFrame({
            "id": ["a", "b", "c", "d"], "physUrl": ["u/a", "u/b", "u/c", "u/d"],
            "authors": ['{"A": "x"}', "{}", "{}", '{"D": "x"}'],
            "status": ["ok", "error", "pending", "ok"]})
        t = xd.build_table(export, previous, pd.Series(dtype=object), pd.Series(dtype=object)).set_index("id")
        assert t.loc["a", "status"] == "ok" and t.loc["a", "authors"] == '{"A": "x"}'
        assert t.loc["b", "status"] == "pending", "gli errori si riprovano"
        assert t.loc["c", "status"] == "pending"
        assert t.loc["d", "status"] == "pending" and t.loc["d", "authors"] == "{}", "physUrl cambiato"

    def test_extract_all_checkpoints_each_batch(self, xd, monkeypatch, tmp_path):
        export = _export(*[(f"i{n}", n, f"T{n}", f"u/{n}") for n in range(1, 6)])
        table = xd.build_table(export, None, pd.Series(dtype=object), pd.Series(dtype=object))
        out = tmp_path / "d.parquet"
        saved = []

        async def fake_process(url, client, semaphore):
            return {"authors": json.dumps({url: "FBK"}), "status": "ok"}

        async def gather(*tasks, **kw):
            return await asyncio.gather(*tasks)

        real_write = xd.write_table
        monkeypatch.setattr(xd, "write_table", lambda t, p: (real_write(t, p), saved.append(pd.read_parquet(p)))[0])
        monkeypatch.setattr(xd, "process_deliverable", fake_process)
        monkeypatch.setattr(xd, "tqdm", SimpleNamespace(gather=gather))
        monkeypatch.setattr(xd, "BATCH_SIZE", 2)
        asyncio.run(xd.extract_all(table, str(out), None, limit=4))
        assert [int((s["status"] == "ok").sum()) for s in saved] == [2, 4]
        assert table["status"].tolist() == ["ok"] * 4 + ["pending"]

    def test_main_end_to_end_and_rerun(self, xd, monkeypatch, tmp_path):
        folder = tmp_path / "export"
        folder.mkdir()
        write_record(folder, _project(101), deliverables=[DELIV_A, DELIV_NO_LINK])
        write_record(folder, _project(102), deliverables=[
            {"id": "102_1_DELIVHORIZON", "title": "Plan", "physUrl": "https://example.org/b.pdf"}])
        cfg = ConfigParser()
        cfg["paths"] = {"new_data_folder_name": str(folder), "deliverables_file": "", "deliverables_env_path": ""}
        (tmp_path / "settings.config").write_text("")
        with open(tmp_path / "settings.config", "w") as f:
            cfg.write(f)
        for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            monkeypatch.setenv(k, "x")
        stub_modules(monkeypatch, "openai")
        monkeypatch.setattr(xd, "known_authors_from_db",
                            lambda d: (pd.Series({"102_1_DELIVHORIZON": '{"Old": "FBK"}'}), pd.Series(dtype=object)))
        calls = []

        async def fake_process(url, client, semaphore):
            calls.append(url)
            return {"authors": '{"New": "Unknown"}', "status": "ok"}

        async def gather(*tasks, **kw):
            return await asyncio.gather(*tasks)

        monkeypatch.setattr(xd, "process_deliverable", fake_process)
        monkeypatch.setattr(xd, "tqdm", SimpleNamespace(gather=gather))
        out = tmp_path / "out.parquet"
        argv = ["--config", str(tmp_path / "settings.config"), "--out", str(out)]
        assert xd.main(argv) == 0
        df = pd.read_parquet(out).set_index("id")
        assert calls == [DELIV_A["physUrl"]]
        assert df["status"].to_dict() == {DELIV_A["id"]: "ok", DELIV_NO_LINK["id"]: "no_url",
                                          "102_1_DELIVHORIZON": "carried"}
        assert df.loc[DELIV_A["id"], "authors"] == '{"New": "Unknown"}'
        assert df.loc["102_1_DELIVHORIZON", "authors"] == '{"Old": "FBK"}'
        assert df.loc[DELIV_A["id"], "title"] == DELIV_A["title"], "titolo ufficiale dell'export"
        assert pd.read_parquet(out)["projectID"].dtype == "int32"
        # secondo lancio: niente da fare
        assert xd.main(argv) == 0
        assert calls == [DELIV_A["physUrl"]]

    def test_main_requires_llm_settings(self, xd, monkeypatch, tmp_path):
        folder = tmp_path / "export"
        folder.mkdir()
        write_record(folder, _project(101), deliverables=[DELIV_A])
        (tmp_path / "s.config").write_text(f"[paths]\nnew_data_folder_name = {folder}\n")
        monkeypatch.setattr(xd, "known_authors_from_db", lambda d: (pd.Series(dtype=object),) * 2)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        assert xd.main(["--config", str(tmp_path / "s.config"), "--out", str(tmp_path / "o.parquet")]) == 1

    def test_main_refuses_legacy_export(self, xd, tmp_path):
        folder = tmp_path / "old"
        folder.mkdir()
        for name in ("project.json", "organization.json", "webLink.json"):
            (folder / name).write_text("[]")
        (tmp_path / "s.config").write_text(f"[paths]\nnew_data_folder_name = {folder}\n")
        assert xd.main(["--config", str(tmp_path / "s.config"), "--out", str(tmp_path / "o.parquet")]) == 1
        assert not (tmp_path / "o.parquet").exists()


# ==============================================================================
# 3. INTEGRAZIONE: update_db.py e compute_embeddings.py eseguiti nella sandbox
#
# 3.1 update_db.py --projects
# ==============================================================================
class TestProjectsStep:
    def test_adds_only_new_projects(self, sandbox, run_update):
        before = sandbox.df("projects_uncase")
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        after = sandbox.df("projects_uncase")
        assert len(after) == len(before) + len(sandbox.new_ids)
        assert set(after["projectID"]) == set(before["projectID"]) | set(sandbox.new_ids)
        assert not after["projectID"].duplicated().any()

    def test_new_rows_content(self, sandbox, run_update):
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        fp_dict = read_fp_dict()
        rows = sandbox.df("projects_uncase").set_index("projectID").loc[sandbox.new_ids]
        expected_vectors = sandbox.bge_vectors()
        assert np.allclose(np.stack(rows["vector"].to_numpy()), expected_vectors, atol=1e-6)
        for i, (rec, (pid, row)) in enumerate(zip(sandbox.new_projects.to_dict("records"), rows.iterrows())):
            assert pid == rec["projectID"]
            assert same(row["title"], rec["title"])
            assert same(row["objective"], rec["objective"])
            assert same(row["acronym"], rec["acronym"])
            assert same(row["fp"], fp_dict.get(rec["fp"]))
            assert list(row["participants"]) == []
            assert row["n_deliverables"] == 0 and row["n_publications"] == 0
            hier = res.fakes.expected_hierarchy(i)
            assert list(row["topic_name_hierarchy"]) == list(hier)
            assert row["topic_name"] == first_labelled(hier)

    def test_existing_rows_untouched(self, sandbox, run_update):
        before = sandbox.df("projects_uncase").set_index("projectID")
        assert run_update(sandbox, "--projects").code == 0
        after = sandbox.df("projects_uncase").set_index("projectID").loc[before.index]
        for col in ("title", "objective", "acronym", "fp", "topic_name"):
            assert all(same(a, b) for a, b in zip(before[col], after[col])), col
        assert [list(p) for p in before["participants"]] == [list(p) for p in after["participants"]]
        assert np.allclose(np.stack(before["vector"].to_numpy()), np.stack(after["vector"].to_numpy()))

    def test_treemap_written(self, sandbox, run_update):
        """La treemap della pagina Concept finisce nella sandbox (mai in assets/ reale) e conta tutti i progetti etichettati."""
        out = sandbox.root / "assets" / "treemap.json"
        assert not out.exists()
        assert run_update(sandbox, "--projects").code == 0
        trace = json.loads(out.read_text())["data"][0]
        hier_paths = {tuple(p) for p in json.loads((sandbox.data / "topic2hier.json").read_text()).values()}
        projects = sandbox.df("projects_uncase")
        labelled = [p for p in projects["topic_name_hierarchy"]
                    if any(n != "Unlabelled" for n in p) and tuple(p) in hier_paths]
        roots = [v for v, parent in zip(trace["values"], trace["parents"]) if parent == ""]
        assert sum(roots) == len(labelled)

    def test_concept_map_backed_up(self, sandbox, run_update):
        """Prima di rigenerare la mappa di Concept ne resta una copia in data/backups/."""
        dmp = sandbox.root / "assets" / "dmp_for_dash.html"
        dmp.parent.mkdir(parents=True, exist_ok=True)
        dmp.write_text("<html>vecchia</html>")
        assert run_update(sandbox, "--projects").code == 0
        backups = list((sandbox.data / "backups").glob("dmp_for_dash_*.html"))
        assert [b.read_text() for b in backups] == ["<html>vecchia</html>"]

    def test_duplicates_in_new_data_are_skipped(self, sandbox, run_update):
        assert sandbox.dup_ids, "la sandbox dovrebbe contenere progetti duplicati"
        before = sandbox.df("projects_uncase")
        assert run_update(sandbox, "--projects").code == 0
        after = sandbox.df("projects_uncase")
        for pid in sandbox.dup_ids:
            assert (after["projectID"] == pid).sum() == 1
            assert (before["projectID"] == pid).sum() == 1

    def test_uses_precomputed_embeddings(self, sandbox, run_update):
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert res.fakes.bge_calls == [], "con bge_embedding_file impostato non si deve ricalcolare"
        assert len(res.fakes.topic_calls) == 1
        call = res.fakes.topic_calls[0]
        assert call["df"]["projectID"].tolist() == sandbox.new_ids
        assert call["embs_shape"][0] == len(sandbox.new_ids)

    def test_computes_embeddings_when_not_configured(self, sandbox, run_update):
        write_config(sandbox, bge="")
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert len(res.fakes.bge_calls) == 1
        assert res.fakes.bge_calls[0]["projectID"].tolist() == sandbox.new_ids
        rows = sandbox.df("projects_uncase").set_index("projectID").loc[sandbox.new_ids]
        assert np.stack(rows["vector"].to_numpy()).shape == (len(sandbox.new_ids), sandbox.vector_dim)

    def test_uses_precomputed_specter_by_project_id(self, sandbox, run_update):
        """Il parquet della sandbox è in ordine inverso: gli embedding vanno abbinati per projectID."""
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert np.allclose(res.fakes.topic_calls[0]["embs"], sandbox.specter_vectors())

    def test_empty_specter_path_means_compute(self, sandbox, run_update):
        write_config(sandbox, specter="")
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert res.fakes.topic_calls[0]["embs"] is None

    def test_topic_settings_passed_from_config(self, sandbox, run_update):
        write_config(sandbox, threshold="0.9", min_cluster_size="7", review="new_data/rev.xlsx",
                     bonus="0.05", bonus_existing="-0.01")
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert res.fakes.topic_calls[0]["kwargs"] == {
            "similarity_threshold": 0.9, "min_cluster_size": 7,
            "review": "provisional", "sheet_path": f"new_data/rev_{TODAY}.xlsx", "reviewed_bonus": 0.05}

    def test_topic_settings_defaults(self, sandbox, run_update):
        """Senza la sezione [topics] nel config si usano i valori predefiniti."""
        path = write_config(sandbox)
        cfg = ConfigParser()
        cfg.read(path)
        cfg.remove_section("topics")
        with open(path, "w", encoding="utf-8") as f:
            cfg.write(f)
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        assert res.fakes.topic_calls[0]["kwargs"] == {
            "similarity_threshold": 0.92, "min_cluster_size": 5,
            "review": "provisional", "sheet_path": f"new_data/topic_review_{TODAY}.xlsx", "reviewed_bonus": 0.02}

    @pytest.mark.parametrize("flags,review", [
        ((), "provisional"),         # tutti i progetti entrano, con topic provvisori e foglio da compilare
        (("--no-review",), "none"),
    ])
    def test_review_mode(self, sandbox, run_update, flags, review):
        res = run_update(sandbox, "--projects", *flags)
        assert res.code == 0
        kwargs = res.fakes.topic_calls[0]["kwargs"]
        assert kwargs["review"] == review
        assert kwargs["sheet_path"] == f"new_data/topic_review_{TODAY}.xlsx", "la data è nel nome del foglio"
        assert "existing" not in kwargs and "report_path" not in kwargs and "decisions_path" not in kwargs

    def test_projects_are_written_without_waiting_for_the_review(self, sandbox, run_update):
        """Nessuna pausa: i progetti sono nel db subito, con il topic provvisorio scelto dalla revisione."""
        assert run_update(sandbox).code == 0
        assert set(sandbox.new_ids) <= set(sandbox.df("projects_uncase")["projectID"])
        assert sandbox.table("participants").count_rows() > 0

    def test_no_terminal_is_needed(self, sandbox, run_update, monkeypatch):
        """Nessuna parte della pipeline legge da stdin: la revisione è nel foglio."""
        monkeypatch.setattr(sys, "stdin", None)
        assert run_update(sandbox, "--projects").code == 0

    def test_aborted_topic_assignment_writes_nothing(self, sandbox, run_update, capsys):
        n = sandbox.table("projects_uncase").count_rows()
        res = run_update(sandbox, "--projects", topic_error="ReviewAborted")
        assert res.code == 1
        assert sandbox.table("projects_uncase").count_rows() == n
        assert "No database was modified" in capsys.readouterr().out

    def test_bge_computed_after_the_topics(self, sandbox, run_update):
        write_config(sandbox, bge="")
        res = run_update(sandbox, "--projects", "--no-review")
        assert res.code == 0 and len(res.fakes.bge_calls) == 1

    def test_rerun_aborts_and_keeps_table(self, sandbox, run_update):
        assert run_update(sandbox, "--projects").code == 0
        n = sandbox.table("projects_uncase").count_rows()
        res = run_update(sandbox, "--projects")
        assert res.code != 0
        assert res.fakes.topic_calls == []
        assert sandbox.table("projects_uncase").count_rows() == n

    @pytest.mark.parametrize("which", ["bge", "specter"])
    def test_missing_embedding_aborts(self, sandbox, run_update, capsys, which):
        path = sandbox.bge if which == "bge" else sandbox.specter
        emb = read_embeddings(path)
        write_embeddings(path, emb.ids[1:], emb.vectors[1:])
        n = sandbox.table("projects_uncase").count_rows()
        res = run_update(sandbox, "--projects")
        assert res.code != 0
        assert res.fakes.topic_calls == []
        assert sandbox.table("projects_uncase").count_rows() == n
        assert "senza embedding" in capsys.readouterr().out

    def test_extra_embeddings_are_ignored(self, sandbox, run_update):
        """Embedding di progetti che non sono da aggiungere (es. già nel db) non danno fastidio."""
        emb = read_embeddings(sandbox.bge)
        write_embeddings(sandbox.bge, emb.ids + [sandbox.old_ids[0]], np.vstack([emb.vectors, emb.vectors[:1]]))
        assert run_update(sandbox, "--projects").code == 0
        rows = sandbox.df("projects_uncase").set_index("projectID").loc[sandbox.new_ids]
        assert np.allclose(np.stack(rows["vector"].to_numpy()), sandbox.bge_vectors(), atol=1e-6)

    def test_duplicate_embedding_ids_abort(self, sandbox, run_update):
        emb = read_embeddings(sandbox.specter)
        write_embeddings(sandbox.specter, emb.ids + emb.ids[:1], np.vstack([emb.vectors, emb.vectors[:1]]))
        assert run_update(sandbox, "--projects").code != 0
        assert sandbox.table("projects_uncase").count_rows() == len(sandbox.old_ids)

    def test_positional_npy_rejected(self, sandbox, run_update):
        npy = sandbox.du / "new_data" / "bge.npy"
        np.save(npy, sandbox.bge_vectors())
        write_config(sandbox, bge="new_data/bge.npy")
        res = run_update(sandbox, "--projects")
        assert res.code != 0
        assert res.fakes.topic_calls == []

    def test_bge_dim_mismatch_aborts(self, sandbox, run_update):
        emb = read_embeddings(sandbox.bge)
        write_embeddings(sandbox.bge, emb.ids, emb.vectors[:, :8])
        res = run_update(sandbox, "--projects")
        assert res.code != 0
        assert sandbox.table("projects_uncase").count_rows() == len(sandbox.old_ids)

    def test_non_integer_project_id_aborts(self, sandbox, run_update):
        bad_id = None if sandbox.fmt == "legacy" else "not-a-number"
        sandbox.append_project(**{**sandbox.new_projects.iloc[0].to_dict(), "projectID": bad_id})
        n = sandbox.table("projects_uncase").count_rows()
        res = run_update(sandbox, "--projects")
        assert res.code != 0
        assert sandbox.table("projects_uncase").count_rows() == n

    def test_missing_config_aborts(self, sandbox, run_update):
        res = run_update(sandbox, "--projects", config=sandbox.du / "does_not_exist.config")
        assert res.code != 0

    def test_empty_data_folder_aborts(self, sandbox, run_update):
        write_config(sandbox, folder="")
        assert run_update(sandbox, "--projects").code != 0

    def test_custom_config_path(self, sandbox, run_update):
        alt = write_config(sandbox, path=sandbox.root / "alt.config")
        (sandbox.du / "settings.config").unlink()
        assert run_update(sandbox, "--projects", config=alt).code == 0
        assert set(sandbox.new_ids) <= set(sandbox.df("projects_uncase")["projectID"])

    def test_indexes_created(self, sandbox, run_update):
        assert run_update(sandbox, "--projects").code == 0
        idx = indexed_columns(sandbox.table("projects_uncase"))
        assert {"projectID", "topic_name_hierarchy"} <= idx
        assert "vector" not in idx, "un indice vettoriale falsa le distanze filtrate dalla dashboard"

    def test_search_distances_are_exact(self, sandbox, run_update):
        """La dashboard scarta i risultati con distanza > 0.45 (scripts/_rag.py): le distanze
        restituite dalla ricerca devono essere quelle vere, anche con righe vecchie e nuove."""
        assert run_update(sandbox, "--projects").code == 0
        rows = sandbox.df("projects_uncase").set_index("projectID")
        query = (np.asarray(rows.loc[sandbox.old_ids[0], "vector"], dtype="float32")
                 + sandbox.bge_vectors()[0].astype("float32"))
        res = sandbox.table("projects_uncase").search(query).metric("cosine").limit(50).to_pandas()
        V = np.stack(res["vector"].to_numpy())
        true = 1 - (V @ query) / (np.linalg.norm(V, axis=1) * np.linalg.norm(query))
        assert np.allclose(res["_distance"], true, atol=1e-4)
        ids = set(res["projectID"])
        assert ids & set(sandbox.new_ids) and ids & set(sandbox.old_ids), "il test vuole risultati misti"

    def test_schema_preserved(self, sandbox, run_update):
        schema_before = sandbox.table("projects_uncase").schema
        assert run_update(sandbox, "--projects").code == 0
        assert sandbox.table("projects_uncase").schema == schema_before

    def test_vector_search_finds_new_project(self, sandbox, run_update):
        assert run_update(sandbox, "--projects").code == 0
        vec = sandbox.bge_vectors()[0]
        hit = (sandbox.table("projects_uncase").search(vec).metric("cosine").limit(1)
               .select(["projectID"]).to_pandas())
        assert hit["projectID"].iloc[0] == sandbox.new_ids[0]

    def test_only_projects_step_runs(self, sandbox, run_update):
        n_part = sandbox.table("participants").count_rows()
        n_deliv = sandbox.table("deliverables").count_rows()
        orgs_before = sandbox.org_json.read_text(encoding="utf-8")
        assert run_update(sandbox, "--projects").code == 0
        assert sandbox.table("participants").count_rows() == n_part
        assert sandbox.table("deliverables").count_rows() == n_deliv
        assert sandbox.org_json.read_text(encoding="utf-8") == orgs_before
        assert not (sandbox.graph_dir / "_index.json").exists()


# ==============================================================================
# 3.2 INTEGRAZIONE: compute_embeddings.py (modelli stubbati)
# ==============================================================================
def fake_vectors(ids, dim):
    """Embedding deterministici ricavabili dal projectID."""
    ids = np.asarray(ids, dtype="float32")
    return np.stack([np.full(dim, i % 997, dtype="float32") + np.arange(dim, dtype="float32") / dim
                     for i in ids]) if len(ids) else np.zeros((0, dim), dtype="float32")


@pytest.fixture
def run_compute(monkeypatch):
    def _run(sb, *args):
        emb = types.ModuleType("extract_embedding")
        emb.get_device = lambda: "cpu"
        emb.extract_specter2 = lambda df, batch_size=32, device=None, progress=False: \
            fake_vectors(df["projectID"], 768)
        emb.extract_bgem3 = lambda df, device=None: fake_vectors(df["projectID"], 1024)
        with monkeypatch.context() as m:
            m.chdir(sb.du)
            m.syspath_prepend(str(sb.du))
            for name in PIPELINE_MODULES:
                m.delitem(sys.modules, name, raising=False)
            m.setitem(sys.modules, "extract_embedding", emb)
            m.setattr(sys, "argv", ["compute_embeddings.py", *args])
            try:
                runpy.run_path(str(sb.du / "compute_embeddings.py"), run_name="__main__")
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            finally:
                for name in PIPELINE_MODULES:
                    sys.modules.pop(name, None)
        return code
    return _run


class TestComputeEmbeddings:
    @pytest.mark.parametrize("model,dim", [("specter2", 768), ("bge", 1024)])
    def test_new_projects_only(self, sandbox, run_compute, model, dim):
        out = sandbox.root / f"{model}.parquet"
        assert run_compute(sandbox, "--model", model, "--source", "new", "--out", str(out)) == 0
        emb = read_embeddings(out)
        assert sorted(emb.ids) == sorted(sandbox.new_ids), "solo i progetti non ancora nel db"
        assert np.allclose(emb.for_ids(emb.ids), fake_vectors(emb.ids, dim))
        import pyarrow.parquet as pq
        schema = pq.read_schema(out)
        assert str(schema.field("projectID").type) == "int32"
        assert schema.field("vector").type.list_size == dim

    def test_default_output_name(self, sandbox, run_compute):
        assert run_compute(sandbox, "--model", "specter2", "--source", "new") == 0
        assert (sandbox.du / "new_data" / "specter2_batch.parquet").exists()

    def test_db_source_with_limit(self, sandbox, run_compute):
        out = sandbox.root / "db.parquet"
        assert run_compute(sandbox, "--model", "specter2", "--source", "db", "--limit", "5", "--out", str(out)) == 0
        ids = read_embeddings(out).ids
        assert len(ids) == 5 and set(ids) <= set(sandbox.old_ids)

    def test_output_feeds_update_db(self, sandbox, run_compute, run_update):
        if sandbox.vector_dim != 1024:
            pytest.skip("il db della sandbox non ha vettori a 1024 dimensioni")
        assert run_compute(sandbox, "--model", "bge", "--source", "new", "--out", str(sandbox.bge)) == 0
        assert run_compute(sandbox, "--model", "specter2", "--source", "new", "--out", str(sandbox.specter)) == 0
        res = run_update(sandbox, "--projects")
        assert res.code == 0
        rows = sandbox.df("projects_uncase").set_index("projectID").loc[sandbox.new_ids]
        assert np.allclose(np.stack(rows["vector"].to_numpy()), fake_vectors(sandbox.new_ids, 1024))
        assert np.allclose(res.fakes.topic_calls[0]["embs"], fake_vectors(sandbox.new_ids, 768))

    def test_no_new_projects(self, sandbox, run_compute, run_update):
        assert run_update(sandbox, "--projects").code == 0
        assert run_compute(sandbox, "--model", "bge", "--source", "new") != 0


# ==============================================================================
# 3.3 INTEGRAZIONE: progetti già nel db (archivio Specter2) e update_db.py --review
# ==============================================================================
def _store_ids(sb):
    import pyarrow.parquet as pq
    return pq.read_table(sb.store).column("projectID").to_pylist()


def _fake_moves(ids, path, topic_id=999):
    n = len(ids)
    return pd.DataFrame({
        "projectID": ids, "title": ["t"] * n, "from_topic": ["x"] * n, "from_hierarchy": [["x"] * 4] * n,
        "key": [0] * n, "topic_id": [topic_id] * n, "topic_name": [path[-1]] * n,
        "topic_name_hierarchy": [_pad(path)] * n, "similarity": [0.9] * n, "best_original": [0.85] * n,
    })


NEW_TOPIC_PATH = ("Engineering & Technology", "Computer Engineering", "Test Moved Topic")


class TestExistingProjectsInUpdate:
    def test_store_gets_new_projects(self, sandbox, run_update, store_mod):
        before = _store_ids(sandbox)
        assert run_update(sandbox, "--projects").code == 0
        ids, embs = store_mod.load_store(str(sandbox.store))
        assert ids.tolist() == before + sandbox.new_ids, "i progetti vecchi restano, i nuovi si aggiungono"
        assert np.allclose(embs[len(before):], sandbox.specter_vectors()), "stesso embedding usato per i topic"

    def test_store_created_when_missing(self, sandbox, run_update):
        sandbox.store.unlink()
        assert run_update(sandbox, "--projects").code == 0
        assert _store_ids(sandbox) == sandbox.new_ids

    def test_aborted_topic_assignment_leaves_store_untouched(self, sandbox, run_update):
        before = sandbox.store.read_bytes()
        assert run_update(sandbox, "--projects", topic_error="ReviewAborted").code == 1
        assert sandbox.store.read_bytes() == before


class TestReviewFlag:
    """update_db.py --review FILE: applica il foglio compilato ai progetti già nel db e termina."""

    def test_applies_the_sheet_and_nothing_else(self, sandbox, run_update, capsys):
        write_config(sandbox, threshold="0.9", bonus_existing="-0.01")
        n = sandbox.table("projects_uncase").count_rows()
        res = run_update(sandbox, "--review", "new_data/compiled.xlsx")
        assert res.code == 0
        [call] = res.fakes.review_calls
        assert call["sheet_path"] == "new_data/compiled.xlsx"
        assert call["store_path"].endswith("specter2.parquet")
        assert call["kwargs"] == {"similarity_threshold": 0.9, "existing_bonus": -0.01}
        assert res.fakes.topic_calls == [] and res.fakes.bge_calls == [], "non legge l'export né ricalcola nulla"
        assert sandbox.table("projects_uncase").count_rows() == n
        assert "Nothing to change" in capsys.readouterr().out

    def test_works_without_new_projects(self, sandbox, run_update):
        assert run_update(sandbox, "--projects").code == 0
        assert run_update(sandbox, "--review", "new_data/compiled.xlsx").code == 0

    @pytest.mark.parametrize("flags", [("--projects",), ("--participants",), ("--deliverables",), ("--no-review",)])
    def test_does_not_combine(self, sandbox, run_update, flags):
        res = run_update(sandbox, "--review", "new_data/compiled.xlsx", *flags)
        assert res.code != 0 and res.fakes.review_calls == []

    def test_needs_a_file(self, sandbox, run_update):
        assert run_update(sandbox, "--review").code != 0

    @pytest.mark.parametrize("error", ["ReviewAborted", "KeyboardInterrupt"])
    def test_aborted_writes_nothing(self, sandbox, run_update, error, capsys):
        before = sandbox.df("projects_uncase")
        res = run_update(sandbox, "--review", "new_data/compiled.xlsx", topic_error=error)
        assert res.code == 1
        pd.testing.assert_frame_equal(sandbox.df("projects_uncase"), before)
        assert "No database was modified" in capsys.readouterr().out

    def test_moves_written_to_both_tables(self, sandbox, run_update, capsys):
        moved = sandbox.dup_ids[:2]
        parts_before = sandbox.df("participants")
        res = run_update(sandbox, "--review", "new_data/compiled.xlsx", moves=_fake_moves(moved, NEW_TOPIC_PATH))
        assert res.code == 0
        assert "2 projects moved to new topics" in capsys.readouterr().out

        rows = sandbox.df("projects_uncase").set_index("projectID")
        assert (rows.loc[moved, "topic_name"] == "Test Moved Topic").all()
        assert list(rows.loc[moved[0], "topic_name_hierarchy"]) == _pad(NEW_TOPIC_PATH)
        others = [p for p in sandbox.old_ids if p not in moved]
        assert (rows.loc[others, "topic_name"] != "Test Moved Topic").all()

        parts = sandbox.df("participants")
        assert len(parts) == len(parts_before)
        mine = parts[parts["projectID"].isin(moved)]
        assert len(mine) > 0 and (mine["topic_name"] == "Test Moved Topic").all()
        assert all(list(h) == _pad(NEW_TOPIC_PATH) for h in mine["topic_name_hierarchy"])
        rest = parts[~parts["projectID"].isin(moved)]
        assert (rest["topic_name"] != "Test Moved Topic").all()

        logs = list((sandbox.data / "backups").glob("reassign_*.json"))
        assert len(logs) == 1 and {m["projectID"] for m in json.loads(logs[0].read_text())["moves"]} == set(moved)

    def test_graphs_include_moved_projects(self, sandbox, run_update):
        moved = sandbox.dup_ids[:2]
        assert run_update(sandbox, "--review", "new_data/compiled.xlsx",
                          moves=_fake_moves(moved, NEW_TOPIC_PATH)).code == 0
        index = json.loads((sandbox.graph_dir / "_index.json").read_text())
        graph = json.loads((sandbox.graph_dir / index["Test Moved Topic"]).read_text())
        assert set(graph["nodes"]) == {str(p) for p in moved}

    def test_no_moves_no_log_no_rebuild(self, sandbox, run_update):
        assert run_update(sandbox, "--review", "new_data/compiled.xlsx").code == 0
        assert not list(sandbox.data.glob("backups/reassign_*.json"))
        assert not list(sandbox.data.glob("backups/project_graphs_*"))

    def test_graphs_backed_up_before_rebuild(self, sandbox, run_update):
        (sandbox.graph_dir / "marker.json").write_text("{}")
        moved = sandbox.dup_ids[:2]
        assert run_update(sandbox, "--review", "new_data/compiled.xlsx",
                          moves=_fake_moves(moved, NEW_TOPIC_PATH)).code == 0
        backups = list((sandbox.data / "backups").glob("project_graphs_*"))
        assert len(backups) == 1 and (backups[0] / "marker.json").exists()

    def test_dashboard_reads_tables_after_moves(self, sandbox, run_update):
        """to_pandas semplice, come la dashboard, dopo update su righe vecchie e add di righe nuove."""
        assert run_update(sandbox).code == 0
        assert run_update(sandbox, "--review", "new_data/compiled.xlsx",
                          moves=_fake_moves(sandbox.dup_ids[:2], NEW_TOPIC_PATH)).code == 0
        for name in ("projects_uncase", "participants"):
            assert len(sandbox.df(name)) > 0


# ==============================================================================
# 3.4 INTEGRAZIONE: update_db.py --participants
# ==============================================================================
def _expected_new_participant_projects(sb, projects_before):
    todo = {pid for pid, p in zip(projects_before["projectID"], projects_before["participants"]) if len(p) == 0}
    return todo & set(sb.new_orgs()["projectID"])


def _new_orgs_exploded(sb):
    """Organizzazioni del batch della sandbox con una riga per paese, come in update_db."""
    orgs = sb.new_orgs()
    orgs["countryCode"] = orgs["countryCode"].str.split(";")
    orgs = orgs.explode("countryCode", ignore_index=True)
    orgs["countryCode"] = orgs["countryCode"].str.strip()
    return orgs


class TestParticipantsStep:
    def test_runs(self, sb_with_projects, run_update):
        assert run_update(sb_with_projects, "--participants").code == 0

    def test_rows_added_only_for_todo_projects(self, sb_with_projects, run_update):
        sb = sb_with_projects
        projects_before = sb.df("projects_uncase")
        parts_before = sb.df("participants")
        expected = _expected_new_participant_projects(sb, projects_before)
        assert run_update(sb, "--participants").code == 0
        parts_after = sb.df("participants")

        diff = (parts_after["projectID"].value_counts()
                .sub(parts_before["projectID"].value_counts(), fill_value=0))
        changed = set(diff[diff != 0].index)
        assert changed == expected
        n_expected_rows = int(_new_orgs_exploded(sb)["projectID"].isin(expected).sum())
        assert len(parts_after) - len(parts_before) == n_expected_rows

    def test_projects_with_participants_not_reprocessed(self, sb_with_projects, run_update):
        sb = sb_with_projects
        before = sb.df("participants")
        assert run_update(sb, "--participants").code == 0
        after = sb.df("participants")
        for pid in sb.dup_ids:
            assert (after["projectID"] == pid).sum() == (before["projectID"] == pid).sum()

    def test_added_rows_enriched_with_project_fields(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        projects = sb.df("projects_uncase").set_index("projectID")
        parts = sb.df("participants")
        new_parts = parts[parts["projectID"].isin(sb.new_ids)]
        assert not new_parts.empty
        for _, row in new_parts.iterrows():
            proj = projects.loc[row["projectID"]]
            assert same(row["topic_name"], proj["topic_name"])
            assert same(row["fp"], proj["fp"])
            assert list(row["topic_name_hierarchy"]) == list(proj["topic_name_hierarchy"])

    def test_added_rows_have_raw_fields(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        parts = sb.df("participants")
        new_parts = parts[parts["projectID"].isin(sb.new_ids)]
        raw = _new_orgs_exploded(sb)
        raw = raw[raw["projectID"].isin(sb.new_ids)]
        key = lambda df: sorted(zip(df["organisationID"].astype(int), df["projectID"].astype(int),
                                    df["role"].astype(str)))
        assert key(new_parts) == key(raw)
        assert sorted(new_parts["countryCode"].astype(str)) == sorted(raw["countryCode"].astype(str))
        assert sorted(new_parts["activityType"].astype(str)) == sorted(raw["activityType"].astype(str))

    def test_ec_contribution_rounded_to_int(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        parts = sb.df("participants")
        new_parts = parts[parts["projectID"].isin(sb.new_ids)]
        values = new_parts["netEcContribution"].dropna()
        assert (values == values.round()).all()
        raw = _new_orgs_exploded(sb)
        raw = raw[raw["projectID"].isin(sb.new_ids)]
        expected = (pd.to_numeric(raw["netEcContribution"], errors="coerce").round()
                    .groupby(raw["projectID"]).sum())
        got = new_parts.groupby("projectID")["netEcContribution"].sum()
        assert np.allclose(got.reindex(expected.index).astype(float), expected.astype(float))

    def test_multi_country_rows_are_split(self, sb_with_projects, run_update):
        """Un'organizzazione con countryCode "DE;HU" diventa una riga per paese."""
        sb = sb_with_projects
        orgs = sb.new_orgs()
        pid = int(orgs.loc[orgs["projectID"].isin(sb.new_ids), "projectID"].iloc[-1])
        template = orgs[orgs["projectID"] == pid].iloc[0].to_dict()
        sb.append_org(**{**template, "organisationID": 999999991, "countryCode": "DE;HU",
                         "name": "MULTI COUNTRY ORGANISATION"})

        assert run_update(sb, "--participants").code == 0
        parts = sb.df("participants")
        rows = parts[(parts["organisationID"] == 999999991) & (parts["projectID"] == pid)]
        assert sorted(rows["countryCode"]) == ["DE", "HU"]
        assert rows["name"].nunique() == 1 and rows["role"].nunique() == 1
        assert not parts["countryCode"].astype(str).str.contains(";").any()
        projects = sb.df("projects_uncase").set_index("projectID")
        names = list(projects.loc[pid, "participants"])
        assert names.count(rows["name"].iloc[0]) == 1, "il nome non deve essere duplicato nei participants"

    def test_names_use_dictionary_or_formatting(self, sb_with_projects, run_update, format_name_mod):
        sb = sb_with_projects
        with open(sb.org_json, encoding="utf-8") as f:
            org_dict = {int(k): v for k, v in json.load(f).items()}
        stopwords = pytest.importorskip("stopwordsiso").stopwords(STOPWORD_LANGS)
        assert run_update(sb, "--participants").code == 0
        parts = sb.df("participants")
        names = {(int(o), int(p)): n for o, p, n in zip(parts["organisationID"], parts["projectID"], parts["name"])}
        n_known = n_new = 0
        for r in sb.new_orgs().to_dict("records"):
            if r["projectID"] not in sb.new_ids:
                continue
            oid = int(r["organisationID"])
            got = names[(oid, int(r["projectID"]))]
            if oid in org_dict:
                n_known += 1
                assert got == org_dict[oid]
            else:
                n_new += 1
                assert got == call_format_name(format_name_mod.format_name, str(r["name"]), stopwords)
        assert n_known > 0, "nessuna organizzazione già nota nel campione"
        assert n_new > 0, "nessuna organizzazione nuova nel campione: format_name non viene esercitata"

    def test_organisations_json_updated(self, sb_with_projects, run_update):
        sb = sb_with_projects
        with open(sb.org_json, encoding="utf-8") as f:
            before = json.load(f)
        assert run_update(sb, "--participants").code == 0
        with open(sb.org_json, encoding="utf-8") as f:
            after = json.load(f)
        assert all(after[k] == v for k, v in before.items()), "nomi già presenti modificati"
        parts = sb.df("participants")
        new_org_ids = {str(int(o)) for o in parts[parts["projectID"].isin(sb.new_ids)]["organisationID"]}
        assert new_org_ids <= set(after)
        assert set(after) - set(before) == new_org_ids - set(before)
        assert all(isinstance(v, str) and v for v in after.values())

    def test_projects_participants_filled(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        parts = sb.df("participants")
        name_of = {int(o): n for o, n in zip(parts["organisationID"], parts["name"]) if n}
        expected = {}
        for r in sb.new_orgs().to_dict("records"):
            pid = r["projectID"]
            if pid in sb.new_ids:
                expected.setdefault(pid, []).append(name_of[int(r["organisationID"])])
        projects = sb.df("projects_uncase").set_index("projectID")
        for pid in sb.new_ids:
            got = list(projects.loc[pid, "participants"])
            assert got == list(dict.fromkeys(expected.get(pid, []))), pid

    def test_other_project_columns_preserved(self, sb_with_projects, run_update):
        """merge_insert su participants non deve alterare le altre colonne dei progetti."""
        sb = sb_with_projects
        before = sb.df("projects_uncase").set_index("projectID").sort_index()
        assert run_update(sb, "--participants").code == 0
        after = sb.df("projects_uncase").set_index("projectID").sort_index()
        assert list(before.index) == list(after.index)
        for col in ("title", "objective", "acronym", "fp", "topic_name", "n_deliverables", "n_publications"):
            assert all(same(a, b) for a, b in zip(before[col], after[col])), col
        assert [list(h) for h in before["topic_name_hierarchy"]] == [list(h) for h in after["topic_name_hierarchy"]]
        assert np.allclose(np.stack(before["vector"].to_numpy()), np.stack(after["vector"].to_numpy()))
        assert sb.table("projects_uncase").count_rows() == len(before)

    def test_old_projects_participants_unchanged(self, sb_with_projects, run_update):
        sb = sb_with_projects
        before = sb.df("projects_uncase").set_index("projectID")
        assert run_update(sb, "--participants").code == 0
        after = sb.df("projects_uncase").set_index("projectID")
        for pid in sb.old_ids:
            if len(before.loc[pid, "participants"]):
                assert list(before.loc[pid, "participants"]) == list(after.loc[pid, "participants"])

    def test_project_graphs_written(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        index, graphs = _read_graphs(sb.graph_dir)
        projects = sb.df("projects_uncase")
        topics = set(projects["topic_name"].dropna())
        assert topics == set(index)
        by_topic = projects.dropna(subset=["topic_name"]).groupby("topic_name", observed=True)
        for topic, group in by_topic:
            g = graphs[topic]
            assert set(g["nodes"]) == {str(p) for p in group["projectID"]}
            parts = dict(zip(group["projectID"], group["participants"]))
            for e in g["edges"]:
                shared = sorted(set(parts[e["source"]]) & set(parts[e["target"]]))
                assert e["collaborators"] == shared and e["weight"] == len(shared)

    def test_project_graphs_backed_up(self, sb_with_projects, run_update):
        """Prima di rigenerare i grafi ne resta una copia in data/backups/."""
        sb = sb_with_projects
        (sb.graph_dir / "marker.json").write_text("{}")
        assert run_update(sb, "--participants").code == 0
        backups = list((sb.data / "backups").glob("project_graphs_*"))
        assert any((b / "marker.json").exists() for b in backups)

    def test_rerun_is_noop(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        n = sb.table("participants").count_rows()
        with open(sb.org_json, encoding="utf-8") as f:
            orgs = json.load(f)
        assert run_update(sb, "--participants").code == 0
        assert sb.table("participants").count_rows() == n
        with open(sb.org_json, encoding="utf-8") as f:
            assert json.load(f) == orgs

    def test_indexes_created(self, sb_with_projects, run_update):
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        assert {"countryCode", "activityType", "fp", "projectID"} <= indexed_columns(sb.table("participants"))

    def test_mixed_rows_convert_to_pandas(self, sb_with_projects, run_update):
        """Come in scripts/_rag.py: righe di progetti vecchi e nuovi lette insieme con to_pandas."""
        sb = sb_with_projects
        assert run_update(sb, "--participants").code == 0
        ids = ", ".join(str(int(p)) for p in sb.old_ids[:20] + sb.new_ids[:20])
        df = sb.table("participants").search().where(f"projectID IN ({ids})").to_arrow().to_pandas()
        assert set(df["projectID"]) & set(sb.new_ids) and set(df["projectID"]) & set(sb.old_ids)

    def test_schema_preserved(self, sb_with_projects, run_update):
        sb = sb_with_projects
        schema = sb.table("participants").schema
        assert run_update(sb, "--participants").code == 0
        assert sb.table("participants").schema == schema


# ==============================================================================
# 3.5 INTEGRAZIONE: update_db.py --deliverables (dall'export o da deliverables_file)
# ==============================================================================
@pytest.fixture
def sb_deliv(sandbox):
    if sandbox.fmt != "records":
        pytest.skip("i deliverables si leggono solo dall'export con un file per progetto")
    return sandbox


DELIV_KEY = ["physUrl", "projectID", "title", "authors"]


def deliverable_counts(sb):
    """Deliverables per progetto (righe della tabella, compresi quelli senza link)."""
    return sb.df("deliverables").groupby("projectID").size()


def rows_of(sb, project_ids, columns=DELIV_KEY):
    d = sb.df("deliverables")
    return d[d["projectID"].isin(project_ids)][columns].sort_values("physUrl").reset_index(drop=True)


def old_project_with_authors(sb, min_rows=2):
    """Progetto già nel db, fuori dal batch, con almeno min_rows deliverables scritti dalla
    vecchia pipeline (id null), il primo con degli autori."""
    d = sb.df("deliverables")
    d = d[d["projectID"].isin(set(sb.old_ids) - set(sb.dup_ids))]
    for pid, g in d.groupby("projectID"):
        g = g.sort_values("authors", key=lambda a: a == "{}")
        if len(g) >= min_rows and g.iloc[0]["authors"] != "{}":
            return int(pid), g.reset_index(drop=True)
    pytest.skip("nessun progetto con deliverables e autori nella sandbox")


class TestDeliverablesStep:
    def test_export_deliverables_written(self, sb_deliv, run_update):
        sb = sb_deliv
        sb.append_deliverable(sb.new_ids[0], "T_1_DELIVHORIZON", "Synthetic plan", "https://test.invalid/t1")
        before_urls = set(sb.df("deliverables")["physUrl"])
        assert run_update(sb, "--deliverables").code == 0
        export = sb.export_deliverables().set_index("id")
        table = sb.df("deliverables").dropna(subset=["id"]).set_index("id")
        assert set(export.index) <= set(table.index)
        for did, row in export.iterrows():
            got = table.loc[did]
            assert got["title"] == row["title"], "titolo ufficiale dell'export"
            assert same(got["physUrl"], row["physUrl"])
            assert int(got["projectID"]) == int(row["projectID"])
            if row["physUrl"] not in before_urls:
                assert got["authors"] == "{}"

    def test_authors_carried_and_project_rebuilt(self, sb_deliv, run_update):
        """Un progetto già nel db che compare nell'export: i suoi deliverables diventano quelli
        dell'export, gli autori già estratti seguono il physUrl, quelli tolti spariscono."""
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        kept, dropped = old.iloc[0], old.iloc[1]
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "Official title", kept["physUrl"])
        sb.append_deliverable(pid, "K_2_DELIVHORIZON", "Not online yet", None)
        assert run_update(sb, "--deliverables").code == 0
        rows = sb.df("deliverables")
        rows = rows[rows["projectID"] == pid].set_index("id")
        assert sorted(rows.index) == ["K_1_DELIVHORIZON", "K_2_DELIVHORIZON"]
        assert rows.loc["K_1_DELIVHORIZON", "authors"] == kept["authors"]
        assert rows.loc["K_1_DELIVHORIZON", "title"] == "Official title"
        assert rows.loc["K_2_DELIVHORIZON", "authors"] == "{}"
        assert rows.loc["K_2_DELIVHORIZON", "physUrl"] is None
        assert dropped["physUrl"] not in set(sb.df("deliverables")["physUrl"])
        assert sb.df("projects_uncase").set_index("projectID").loc[pid, "n_deliverables"] == 2

    def test_projects_outside_export_untouched(self, sb_deliv, run_update):
        sb = sb_deliv
        outside = [p for p in sb.old_ids if p not in set(sb.dup_ids)]
        before = rows_of(sb, outside)
        assert run_update(sb, "--deliverables").code == 0
        after = rows_of(sb, outside, DELIV_KEY + ["id"])
        assert after["id"].isna().all()
        assert after[DELIV_KEY].equals(before)

    def test_export_project_without_deliverables_is_emptied(self, sb_deliv, run_update):
        """I progetti dell'export seguono l'export anche quando non hanno deliverables."""
        sb = sb_deliv
        d = sb.df("deliverables")
        with_rows = [p for p in sb.dup_ids if (d["projectID"] == p).any()]
        if not with_rows:
            pytest.skip("nessun progetto del batch con deliverables nel db della sandbox")
        assert run_update(sb, "--deliverables").code == 0
        assert not sb.df("deliverables")["projectID"].isin(with_rows).any()
        n = sb.df("projects_uncase").set_index("projectID").loc[with_rows, "n_deliverables"]
        assert (n == 0).all()

    def test_rerun_changes_nothing(self, sb_deliv, run_update):
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "Official title", old.iloc[0]["physUrl"])
        assert run_update(sb, "--deliverables").code == 0
        versions = {t: sb.table(t).version for t in ("deliverables", "projects_uncase")}
        assert run_update(sb, "--deliverables").code == 0
        assert {t: sb.table(t).version for t in versions} == versions, "nessuna scrittura al secondo run"

    def test_incremental_update(self, sb_deliv, run_update):
        """Run successivo su un export cambiato: deliverable ricaricato con un nuovo physUrl
        (tiene gli autori), uno tolto, uno nuovo; il resto della tabella non cambia."""
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        authors = old.iloc[0]["authors"]
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "Official title", old.iloc[0]["physUrl"])
        sb.append_deliverable(pid, "K_2_DELIVHORIZON", "To be withdrawn", "https://test.invalid/k2")
        assert run_update(sb, "--deliverables").code == 0
        others_before = sb.df("deliverables").query("projectID != @pid")[DELIV_KEY + ["id"]]

        sb.edit_deliverable(pid, "K_1_DELIVHORIZON", title="Official title v2",
                            physUrl="https://test.invalid/k1-reuploaded")
        sb.remove_deliverable(pid, "K_2_DELIVHORIZON")
        sb.append_deliverable(pid, "K_3_DELIVHORIZON", "Brand new", "https://test.invalid/k3")
        assert run_update(sb, "--deliverables").code == 0

        rows = sb.df("deliverables").query("projectID == @pid").set_index("id")
        assert sorted(rows.index) == ["K_1_DELIVHORIZON", "K_3_DELIVHORIZON"]
        assert rows.loc["K_1_DELIVHORIZON", "physUrl"] == "https://test.invalid/k1-reuploaded"
        assert rows.loc["K_1_DELIVHORIZON", "title"] == "Official title v2"
        assert rows.loc["K_1_DELIVHORIZON", "authors"] == authors, "gli autori seguono l'id"
        assert rows.loc["K_3_DELIVHORIZON", "authors"] == "{}"
        others_after = sb.df("deliverables").query("projectID != @pid")[DELIV_KEY + ["id"]]
        key = lambda df: df.sort_values(["projectID", "physUrl"]).reset_index(drop=True)
        assert key(others_after).equals(key(others_before))
        assert sb.df("projects_uncase").set_index("projectID").loc[pid, "n_deliverables"] == 2

    def test_n_deliverables_consistent(self, sb_deliv, run_update):
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "A", old.iloc[0]["physUrl"])
        sb.append_deliverable(pid, "K_2_DELIVHORIZON", "B", None)
        assert run_update(sb, "--deliverables").code == 0
        projects = sb.df("projects_uncase").set_index("projectID")
        counts = deliverable_counts(sb).reindex(projects.index, fill_value=0)
        wrong = projects.index[projects["n_deliverables"] != counts]
        assert wrong.empty, f"n_deliverables errato per {list(wrong[:5])}"

    def test_n_deliverables_update_preserves_other_columns(self, sb_deliv, run_update):
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "A", None)
        schema = sb.table("projects_uncase").schema
        before = sb.df("projects_uncase").set_index("projectID").sort_index()
        assert run_update(sb, "--deliverables").code == 0
        after = sb.df("projects_uncase").set_index("projectID").sort_index()
        assert list(before.index) == list(after.index)
        for col in ("title", "objective", "fp", "topic_name", "n_publications"):
            assert all(same(a, b) for a, b in zip(before[col], after[col])), col
        assert [list(p) for p in before["participants"]] == [list(p) for p in after["participants"]]
        assert np.allclose(np.stack(before["vector"].to_numpy()), np.stack(after["vector"].to_numpy()))
        assert sb.table("projects_uncase").schema == schema

    def test_deliverables_before_projects(self, sb_deliv, run_update):
        """Se i deliverables arrivano prima dei progetti, i progetti nuovi prendono subito il conteggio."""
        sb = sb_deliv
        for pid in sb.new_ids[:3]:
            for k in range(3):
                sb.append_deliverable(pid, f"N{pid}_{k}_DELIVHORIZON", f"D{k}", f"https://test.invalid/{pid}/{k}")
        assert run_update(sb, "--deliverables").code == 0
        assert run_update(sb, "--projects").code == 0
        rows = sb.df("projects_uncase").set_index("projectID")
        counts = deliverable_counts(sb)
        for pid in sb.new_ids[:3]:
            assert rows.loc[pid, "n_deliverables"] == counts[pid] >= 3

    def test_schema_indexes_and_dashboard_query(self, sb_deliv, run_update):
        """Al primo run lo step 3 aggiunge la colonna id. Il db reale la ha già (lo step è
        stato eseguito): la si toglie dalla sandbox per ricreare il db di prima."""
        sb = sb_deliv
        if "id" in sb.table("deliverables").schema.names:
            sb.table("deliverables").drop_columns(["id"])
        schema = sb.table("deliverables").schema
        assert run_update(sb, "--deliverables").code == 0
        tbl = sb.table("deliverables")
        assert tbl.schema.names == schema.names + ["id"]
        assert {"projectID", "id"} <= indexed_columns(tbl)
        pid = int(sb.export_deliverables()["projectID"].iloc[0]) if len(sb.export_deliverables()) else sb.old_ids[0]
        # stessa query di pages/rag.py
        rows = (tbl.search().select(["projectID", "title", "authors", "physUrl"])
                .where(f"projectID = {pid}").to_arrow().to_pylist())
        assert rows
        for r in rows:
            assert isinstance(json.loads(r["authors"]), dict)

    def test_only_deliverables_step_runs(self, sb_deliv, run_update):
        n_proj = sb_deliv.table("projects_uncase").count_rows()
        n_part = sb_deliv.table("participants").count_rows()
        assert run_update(sb_deliv, "--deliverables").code == 0
        assert sb_deliv.table("projects_uncase").count_rows() == n_proj
        assert sb_deliv.table("participants").count_rows() == n_part

    def test_legacy_export_refused(self, sandbox, run_update):
        if sandbox.fmt != "legacy":
            pytest.skip("solo per il vecchio formato")
        version = sandbox.table("deliverables").version
        assert run_update(sandbox, "--deliverables").code != 0
        assert sandbox.table("deliverables").version == version


def write_deliverables_file(sb, rel, authors_of=None, **drop):
    """Parquet nel formato di extract_deliverables.py con i deliverables dell'export della sandbox."""
    df = sb.export_deliverables()
    df["authors"] = [(authors_of or {}).get(i, "{}") for i in df["id"]]
    df["status"] = "ok"
    df["projectID"] = df["projectID"].astype("int32")
    path = sb.du / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


class TestDeliverablesFile:
    def test_file_authors_are_used(self, sb_deliv, run_update):
        sb = sb_deliv
        pid = sb.new_ids[0]
        sb.append_deliverable(pid, "F_1_DELIVHORIZON", "From file", "https://test.invalid/f1")
        write_deliverables_file(sb, "new_data/deliv.parquet", {"F_1_DELIVHORIZON": '{"Ada": "FBK"}'})
        write_config(sb, deliverables="new_data/deliv.parquet")
        assert run_update(sb, "--deliverables").code == 0
        rows = sb.df("deliverables").dropna(subset=["id"]).set_index("id")
        assert rows.loc["F_1_DELIVHORIZON", "authors"] == '{"Ada": "FBK"}'
        assert rows.loc["F_1_DELIVHORIZON", "title"] == "From file"

    def test_file_replaces_authors_carried_from_db(self, sb_deliv, run_update):
        """Con il file vale il file: gli autori del db non vengono riportati."""
        sb = sb_deliv
        pid, old = old_project_with_authors(sb)
        sb.append_deliverable(pid, "K_1_DELIVHORIZON", "T", old.iloc[0]["physUrl"])
        write_deliverables_file(sb, "new_data/deliv.parquet", {"K_1_DELIVHORIZON": '{"File": "Author"}'})
        write_config(sb, deliverables="new_data/deliv.parquet")
        assert run_update(sb, "--deliverables").code == 0
        rows = sb.df("deliverables").set_index("id")
        assert rows.loc["K_1_DELIVHORIZON", "authors"] == '{"File": "Author"}'

    def test_second_run_writes_nothing(self, sb_deliv, run_update):
        sb = sb_deliv
        sb.append_deliverable(sb.new_ids[0], "F_1_DELIVHORIZON", "T", "https://test.invalid/f1")
        write_deliverables_file(sb, "new_data/deliv.parquet", {"F_1_DELIVHORIZON": '{"Ada": "FBK"}'})
        write_config(sb, deliverables="new_data/deliv.parquet")
        assert run_update(sb, "--deliverables").code == 0
        version = sb.table("deliverables").version
        assert run_update(sb, "--deliverables").code == 0
        assert sb.table("deliverables").version == version

    def test_missing_file_stops_before_writing(self, sb_deliv, run_update):
        version = sb_deliv.table("deliverables").version
        write_config(sb_deliv, deliverables="new_data/nope.parquet")
        assert run_update(sb_deliv, "--deliverables").code == 1
        assert sb_deliv.table("deliverables").version == version

    @pytest.mark.parametrize("drop", ["authors", "id"])
    def test_file_without_required_column_stops(self, sb_deliv, run_update, drop):
        df = write_deliverables_file(sb_deliv, "new_data/deliv.parquet")
        df.drop(columns=[drop]).to_parquet(sb_deliv.du / "new_data/deliv.parquet")
        version = sb_deliv.table("deliverables").version
        write_config(sb_deliv, deliverables="new_data/deliv.parquet")
        assert run_update(sb_deliv, "--deliverables").code == 1
        assert sb_deliv.table("deliverables").version == version

    def test_duplicate_ids_stop(self, sb_deliv, run_update):
        df = write_deliverables_file(sb_deliv, "new_data/deliv.parquet")
        pd.concat([df, df.iloc[:1]]).to_parquet(sb_deliv.du / "new_data/deliv.parquet")
        write_config(sb_deliv, deliverables="new_data/deliv.parquet")
        assert run_update(sb_deliv, "--deliverables").code == 1

    def test_file_works_with_legacy_export(self, sandbox, run_update):
        """Il file è indipendente dal formato dell'export."""
        if sandbox.fmt != "legacy":
            pytest.skip("solo per il vecchio formato")
        pid = int(sandbox.old_ids[0])
        pd.DataFrame({"id": ["L_1_DELIVHORIZON"], "projectID": pd.Series([pid], dtype="int32"),
                      "title": ["T"], "physUrl": ["https://test.invalid/l1"], "authors": ['{"A": "B"}']}
                     ).to_parquet(sandbox.du / "new_data/deliv.parquet")
        write_config(sandbox, deliverables="new_data/deliv.parquet")
        assert run_update(sandbox, "--deliverables").code == 0
        rows = sandbox.df("deliverables").set_index("id")
        assert rows.loc["L_1_DELIVHORIZON", "authors"] == '{"A": "B"}'


# ==============================================================================
# 3.6 INTEGRAZIONE: update_db.py --publications
# ==============================================================================
@pytest.fixture
def sb_pubs(sandbox):
    if sandbox.fmt != "records":
        pytest.skip("le pubblicazioni si leggono solo dall'export con un file per progetto")
    return sandbox


def project_counts(sb, ids):
    return sb.df("projects_uncase").set_index("projectID").loc[ids, "n_publications"]


class TestPublicationsStep:
    def test_new_projects_get_export_publications(self, sb_pubs, run_update):
        sb = sb_pubs
        pid = sb.new_ids[0]
        sb.append_publication(pid, "T_1_PUBLIHORIZON", "Synthetic paper", "Ada Lovelace; Alan Turing", "10.1000/t1")
        sb.append_publication(pid, "T_2_PUBLIHORIZON", "No doi", "Grace Hopper")
        assert run_update(sb, "--projects").code == 0
        old_rows = sb.df("publications")
        assert run_update(sb, "--publications").code == 0

        table = sb.df("publications")
        added = table.dropna(subset=["id"]).set_index("id")
        export = sb.export_publications().set_index("id")
        assert set(added.index) == set(export.index[export["projectID"].isin(sb.new_ids)])
        got = added.loc["T_1_PUBLIHORIZON"]
        assert (got["title"], got["physUrl"]) == ("Synthetic paper", "https://doi.org/10.1000/t1")
        assert json.loads(got["authors"]) == {"Ada Lovelace": "Unknown", "Alan Turing": "Unknown"}
        assert added.loc["T_2_PUBLIHORIZON", "physUrl"] is None
        assert len(table) == len(old_rows) + len(added), "le righe vecchie restano"
        cols = ["projectID", "title", "authors", "physUrl"]
        assert table[table["id"].isna()][cols].reset_index(drop=True).equals(old_rows[cols].reset_index(drop=True))

        counts = export[export["projectID"].isin(sb.new_ids)].groupby("projectID").size()
        assert (project_counts(sb, list(counts.index)) == counts).all()
        assert counts[pid] >= 2

    def test_only_projects_without_publications(self, sb_pubs, run_update):
        """I progetti già nel db con n_publications > 0 restano come sono, anche se
        l'export ha pubblicazioni per loro; quelli con 0 le ricevono."""
        sb = sb_pubs
        n = sb.df("projects_uncase").set_index("projectID")["n_publications"]
        with_pubs = [p for p in sb.old_ids if n[p] > 0][:1]
        without = [p for p in sb.old_ids if n[p] == 0][:1]
        if not with_pubs or not without:
            pytest.skip("la sandbox non ha progetti con e senza pubblicazioni")
        for pid in with_pubs + without:
            sb.append_publication(pid, f"O{pid}_PUBLIHORIZON", "Paper", "Ada Lovelace")
        assert run_update(sb, "--publications").code == 0
        ids = set(sb.df("publications")["id"].dropna())
        assert f"O{without[0]}_PUBLIHORIZON" in ids
        assert f"O{with_pubs[0]}_PUBLIHORIZON" not in ids
        assert project_counts(sb, with_pubs).iloc[0] == n[with_pubs[0]]
        assert project_counts(sb, without).iloc[0] == 1

    def test_projects_not_in_db_are_skipped(self, sb_pubs, run_update):
        """Senza --projects i progetti nuovi non sono nel db: si saltano, restano vuoti."""
        sb = sb_pubs
        sb.append_publication(sb.new_ids[0], "S_1_PUBLIHORIZON", "Skipped", "Ada Lovelace")
        assert run_update(sb, "--publications").code == 0
        table = sb.df("publications")
        assert "id" not in table.columns or "S_1_PUBLIHORIZON" not in set(table["id"].dropna())

    def test_rerun_changes_nothing(self, sb_pubs, run_update):
        sb = sb_pubs
        assert run_update(sb, "--projects").code == 0
        assert run_update(sb, "--publications").code == 0
        version = sb.table("publications").version
        projects_version = sb.table("projects_uncase").version
        assert run_update(sb, "--publications").code == 0
        assert sb.table("publications").version == version
        assert sb.table("projects_uncase").version == projects_version

    def test_external_source_is_not_overwritten(self, sb_pubs, run_update):
        sb = sb_pubs
        assert run_update(sb, "--projects").code == 0
        version = sb.table("publications").version
        cfg = write_config(sb, path=sb.root / "ext.config", publications="new_data/pubs.parquet")
        assert run_update(sb, "--publications", config=cfg).code != 0
        assert sb.table("publications").version == version

    def test_old_format_is_refused(self, sandbox, run_update):
        if sandbox.fmt != "legacy":
            pytest.skip("solo con il vecchio export")
        version = sandbox.table("publications").version
        assert run_update(sandbox, "--publications").code != 0
        assert sandbox.table("publications").version == version


# ==============================================================================
# 3.7 INTEGRAZIONE: run completo di update_db.py (tutti gli step)
# ==============================================================================
class TestFullRun:
    def test_all_steps_without_flags(self, sandbox, run_update):
        sb = sandbox
        n_proj = sb.table("projects_uncase").count_rows()
        n_part = sb.table("participants").count_rows()
        deliv_version = sb.table("deliverables").version
        res = run_update(sb)
        assert res.code == 0
        assert sb.table("projects_uncase").count_rows() == n_proj + len(sb.new_ids)
        assert sb.table("participants").count_rows() > n_part
        if sb.fmt == "records":
            assert set(sb.export_deliverables()["id"]) <= set(sb.df("deliverables")["id"].dropna())
        else:
            # il vecchio export non ha i deliverables: lo step viene saltato
            assert sb.table("deliverables").version == deliv_version
        assert (sb.graph_dir / "_index.json").exists()
        projects = sb.df("projects_uncase").set_index("projectID")
        filled = sum(1 for pid in sb.new_ids if len(projects.loc[pid, "participants"]))
        assert filled > 0

    def test_n_deliverables_consistent_after_full_run(self, sandbox, run_update):
        """Dopo un aggiornamento completo ogni progetto ha n_deliverables = deliverables presenti."""
        sb = sandbox
        if sb.fmt == "records":
            outside = [p for p in sb.old_ids if p not in set(sb.dup_ids)]
            for pid in sb.new_ids[:2] + outside[:2]:
                sb.append_deliverable(pid, f"F{pid}_DELIVHORIZON", "F", f"https://test.invalid/f/{pid}")
        assert run_update(sb).code == 0
        projects = sb.df("projects_uncase").set_index("projectID")
        counts = deliverable_counts(sb).reindex(projects.index, fill_value=0)
        wrong = projects.index[projects["n_deliverables"] != counts]
        assert wrong.empty, f"n_deliverables errato per {list(wrong[:5])}"

    def test_steps_in_separate_runs_equal_full_run(self, pristine_sandbox, tmp_path, run_update):
        a = _copy_sandbox(pristine_sandbox, tmp_path / "a")
        b = _copy_sandbox(pristine_sandbox, tmp_path / "b")
        assert run_update(a).code == 0
        flags = ["--projects", "--participants", "--deliverables", "--publications"]
        if pristine_sandbox.fmt == "legacy":
            flags.remove("--deliverables")   # rifiutati con il vecchio export
            flags.remove("--publications")
        for flag in flags:
            assert run_update(b, flag).code == 0
        for name in ("projects_uncase", "participants", "deliverables", "publications"):
            assert a.table(name).count_rows() == b.table(name).count_rows(), name
        pa_ = a.df("projects_uncase").set_index("projectID").sort_index()
        pb_ = b.df("projects_uncase").set_index("projectID").sort_index()
        assert [list(x) for x in pa_["participants"]] == [list(x) for x in pb_["participants"]]
        assert (pa_["n_deliverables"] == pb_["n_deliverables"]).all()


# ==============================================================================
# 4. TEST LENTI CON MODELLI REALI (RUN_SLOW=1)
# ==============================================================================
@slow
@pytest.mark.filterwarnings("ignore:n_jobs value:UserWarning")  # avviso di umap, non della pipeline
class TestRealModels:
    @pytest.fixture
    def sb_slow(self, pristine_sandbox_slow, tmp_path):
        for dep in ("FlagEmbedding", "bertopic", "adapters", "umap", "hdbscan", "nltk"):
            pytest.importorskip(dep)
        if not (REAL_DATA / "old_topic_model").exists():
            pytest.skip("old_topic_model non trovato")
        return _copy_sandbox(pristine_sandbox_slow, tmp_path / "slow")

    def test_projects_step_with_real_models(self, sb_slow, run_update):
        write_config(sb_slow, bge="", specter="")
        res = run_update(sb_slow, "--projects", "--no-review", fake_models=False)
        assert res.code == 0
        rows = sb_slow.df("projects_uncase").set_index("projectID").loc[sb_slow.new_ids]
        vectors = np.stack(rows["vector"].to_numpy())
        assert vectors.shape == (len(sb_slow.new_ids), sb_slow.vector_dim)
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-2)
        labelled = rows["topic_name"].notna() & (rows["topic_name"] != "Unlabelled")
        assert labelled.mean() > 0.9, f"solo {labelled.mean():.0%} dei progetti ha un topic"

    def test_topic_assignment_with_precomputed_embeddings(self, sb_slow, run_update):
        """BERTopic e old_topic_model reali, embedding Specter2 precalcolati: veloce.
        Il lancio scrive i progetti con i topic provvisori e il foglio datato da compilare."""
        if not sb_slow.real_embeddings:
            pytest.skip("embedding precalcolati non disponibili (la sandbox userebbe vettori casuali)")
        pytest.importorskip("openpyxl")
        res = run_update(sb_slow, "--projects", fake_models=False)
        assert res.code == 0
        self._check_sheet(sb_slow)
        rows = sb_slow.df("projects_uncase").set_index("projectID").loc[sb_slow.new_ids]
        labelled = rows["topic_name"].notna() & (rows["topic_name"] != "Unlabelled")
        assert labelled.mean() > 0.9, f"solo {labelled.mean():.0%} dei progetti ha un topic"
        assert rows["topic_name"].nunique() > 10, "i progetti nuovi dovrebbero distribuirsi su molti topic"
        with open(sb_slow.data / "topic2hier.json", encoding="utf-8") as f:
            hierarchies = {tuple(v) for v in json.load(f).values()}
        assert all(tuple(h) in hierarchies for h in rows["topic_name_hierarchy"])

    def _check_sheet(self, sb):
        from openpyxl import load_workbook
        wb = load_workbook(sb.du / "new_data" / f"topic_review_{TODAY}.xlsx")
        listed = []
        for ws in wb:
            if not (re.match(r"^C\d+$", ws.title) or ws.title == "Isolati"):
                continue
            rows = [ws.cell(r, 1).value for r in range(9, ws.max_row + 1) if ws.cell(r, 1).value]
            listed += rows
            if ws.title != "Isolati":
                assert len(rows) >= 5, "un cluster ha almeno min_cluster_size progetti"
                assert ws["B2"].value, "ogni cluster ha parole chiave"
        assert set(listed) <= set(sb.new_ids) and len(set(listed)) == len(listed)
        assert len(listed) < len(sb.new_ids) / 2, "troppi candidati: soglia o embedding sospetti"

    @pytest.fixture
    def et_real(self, monkeypatch):
        """extract_topic con le dipendenze reali (solo per le sue funzioni, sola lettura)."""
        monkeypatch.syspath_prepend(str(HERE))
        return load_module(monkeypatch, "extract_topic", HERE / "extract_topic.py")

    def test_review_sheet_with_real_model(self, sb_slow, run_update, et_real):
        """Foglio compilato con il vero old_topic_model: un gruppo di candidati in un topic nuovo,
        un altro Unlabelled (isolati: nessun alias), alcuni progetti in un topic esistente. Poi simula il batch successivo."""
        pytest.importorskip("openpyxl")
        from openpyxl import load_workbook
        from bertopic import BERTopic
        import pyarrow.parquet as pq
        sb = sb_slow
        write_config(sb, bonus_existing="0.02")   # più largo del predefinito: sui 300 progetti vecchi
                                                  # della sandbox serve qualche spostamento
        specter = sb.specter_vectors()
        unit = specter / np.linalg.norm(specter, axis=1, keepdims=True)
        old_model = BERTopic.load(str(sb.data / "old_topic_model"))
        n_orig = len(old_model.topic_embeddings_)
        new_id = n_orig - old_model._outliers
        reviewed_file = sb.data / "old_topic_model" / "reviewed_topics.json"
        reviewed_before = json.loads(reviewed_file.read_text()) if reviewed_file.exists() else []

        # gruppi coerenti presi tra i candidati (sotto soglia), come farebbe il revisore
        before, best, _ = et_real.assign_existing_topics(old_model, specter, set(reviewed_before))
        cand = np.flatnonzero(best < 0.92)
        assert len(cand) >= 15, f"troppi pochi candidati nella sandbox: {len(cand)}"

        def nearest_candidates(seed, n, exclude=()):
            order = [int(i) for i in cand[np.argsort(-(unit[cand] @ unit[seed]))] if int(i) not in exclude]
            return order[:n]

        accepted = nearest_candidates(int(cand[0]), 8)
        far = int(cand[np.argmin(unit[cand] @ unit[cand[0]])])
        unlabelled = nearest_candidates(far, 5, exclude=set(accepted))
        taken = set(accepted) | set(unlabelled)
        remapped = [i for i in range(len(sb.new_ids)) if i not in taken][:5]
        others = [i for i in range(len(sb.new_ids)) if i not in taken | set(remapped)]
        ids = lambda idx: [int(sb.new_ids[i]) for i in idx]

        with open(sb.data / "topic2hier.json", encoding="utf-8") as f:
            hier_before = json.load(f)
        wireless = list(reversed([x for x in hier_before["40"] if x != "Unlabelled"]))
        new_path = ["Engineering & Technology", "Computer Engineering", "Test Topic Slow"]

        # primo lancio: progetti con topic provvisori e foglio; poi si riscrive il foglio con i gruppi
        # scelti, uno per progetto nel foglio Isolati (i cluster del foglio vengono tolti)
        assert run_update(sb, "--projects", fake_models=False).code == 0
        sheet_rel = f"new_data/topic_review_{TODAY}.xlsx"
        sheet_path = sb.du / sheet_rel
        provisional = sb.df("projects_uncase").set_index("projectID")["topic_name"]
        wb = load_workbook(sheet_path)
        for name in [n for n in wb.sheetnames if re.match(r"^C\d+$", n)]:
            del wb[name]
        ws = wb["Isolati"]
        ws.delete_rows(9, ws.max_row)
        groups = [(accepted, new_path), (remapped, wireless), (unlabelled, ["Unlabelled"])]
        for r, (pid, path) in enumerate(((p, path) for idx, path in groups for p in ids(idx)), 9):
            ws.cell(r, 1, pid)
            ws.cell(r, 4, provisional[pid])
            for k, level in enumerate(path):
                ws.cell(r, 5 + k, level)
        wb.save(sheet_path)

        old_before = sb.df("projects_uncase").set_index("projectID").loc[sb.old_ids]
        res = run_update(sb, "--review", sheet_rel, fake_models=False)
        assert res.code == 0

        # gerarchia: solo il topic nuovo (gli isolati Unlabelled non creano alias), il resto invariato
        with open(sb.data / "topic2hier.json", encoding="utf-8") as f:
            hier_after = json.load(f)
        assert hier_after[str(new_id)] == ["Unlabelled"] + list(reversed(new_path))
        assert str(new_id + 1) not in hier_after
        assert {k: v for k, v in hier_after.items() if int(k) < new_id} == hier_before

        # modello, elenco dei topic revisionati e backup
        model = BERTopic.load(str(sb.data / "old_topic_model"))
        assert len(model.topic_embeddings_) == n_orig + 1
        reviewed = json.loads(reviewed_file.read_text())
        assert reviewed == sorted(reviewed_before + [new_id])
        backups = list((sb.data / "backups").iterdir())
        assert any(p.name.startswith("old_topic_model_") for p in backups)
        assert any(p.name.startswith("topic2hier_") for p in backups)

        # db
        rows = sb.df("projects_uncase").set_index("projectID")
        assert (rows.loc[ids(accepted), "topic_name"] == "Test Topic Slow").all()
        assert list(rows.loc[ids(accepted)[0], "topic_name_hierarchy"]) == hier_after[str(new_id)]
        assert (rows.loc[ids(remapped), "topic_name"] == "Wireless Networks").all()
        assert (rows.loc[ids(unlabelled), "topic_name"] == "Unlabelled").all()

        # progetti già nel db: passano al topic nuovo solo quelli sotto soglia
        changed = [p for p in sb.old_ids if rows.loc[p, "topic_name"] != old_before.loc[p, "topic_name"]]
        assert all(rows.loc[p, "topic_name"] == "Test Topic Slow" for p in changed)
        store = pq.read_table(sb.store).to_pandas().set_index("projectID")
        if changed:
            _, best_old, _ = et_real.assign_existing_topics(
                old_model, np.stack(store.loc[changed, "vector"].to_numpy()), set(reviewed_before))
            assert (best_old < 0.92).all(), "un progetto sopra soglia non cambia mai topic"
        assert len(changed) <= 0.06 * len(sb.old_ids), f"{len(changed)} progetti già nel db spostati"
        print(f"{len(changed)} of {len(sb.old_ids)} projects already in the db moved to the new topic")

        # archivio: i progetti nuovi ci sono, con gli embedding usati per i topic
        assert np.allclose(np.stack(store.loc[sb.new_ids, "vector"].to_numpy()), specter)

        # batch successivo, con la stessa regola della pipeline
        after, _, auto = et_real.assign_existing_topics(model, specter, set(reviewed))
        assert np.mean(after[accepted] == new_id) >= 0.75
        assert not (after == new_id + 1).any(), "gli isolati Unlabelled non hanno un alias nel modello"
        above = [i for i in others if best[i] >= 0.92]
        assert (after[above] == before[above]).all(), "sopra soglia nessun progetto cambia topic"
        assert set(np.flatnonzero(auto)) <= set(cand), "solo i candidati possono andare ai topic revisionati"

    def test_reviewed_topic_rule_on_real_batch(self, real_db, aligned_new_projects, real_specter, et_real):
        """Regressione delle misure del banco di prova sul batch reale: ogni cluster di candidati
        viene diviso a metà, una metà crea il topic e l'altra simula i progetti futuri (M2);
        400 progetti già classificati misurano i "furti" ai topic originali (M3)."""
        from bertopic import BERTopic
        from extract_embedding import extract_specter2
        if real_specter is None or aligned_new_projects.empty:
            pytest.skip("embedding Specter2 precalcolati non disponibili")
        model = BERTopic.load(str(REAL_DATA / "old_topic_model"))
        # solo i topic originali: quelli creati dalle review (in coda al modello) possono venire
        # proprio da questo batch, e come "topic originali" alzerebbero la misura senza bonus
        reviewed_file = REAL_DATA / "old_topic_model" / "reviewed_topics.json"
        already = set(json.loads(reviewed_file.read_text())) if reviewed_file.exists() else set()
        n0 = len(model.topic_embeddings_) - len(already)
        if already != set(range(n0 - model._outliers, len(model.topic_embeddings_) - model._outliers)):
            pytest.skip("i topic revisionati non sono in coda al modello: misura non confrontabile")
        T0 = model.topic_embeddings_[:n0]
        original = SimpleNamespace(topic_embeddings_=T0, _outliers=model._outliers)
        spec = real_specter.for_ids(aligned_new_projects["projectID"].tolist())
        docs = [f"{t or ''} {o or ''}" for t, o in zip(aligned_new_projects["title"], aligned_new_projects["objective"])]
        _, best, _ = et_real.assign_existing_topics(original, spec)
        cand = np.flatnonzero(best < 0.92)
        _, labels = et_real.cluster_candidates([docs[i] for i in cand], spec[cand], 5)
        labels = np.asarray(labels)
        clusters = [cand[labels == c] for c in sorted(set(labels) - {-1})]
        assert clusters

        old = (real_db.open_table("projects_uncase").search().select(["title", "objective", "topic_name"])
               .limit(10 ** 7).to_pandas())
        old = old[old["topic_name"].astype(str) != "Unlabelled"].sample(400, random_state=0)
        E_old = extract_specter2(old)

        rng = np.random.default_rng(0)
        sizes = np.array([len(c) for c in clusters])
        results = {}
        for bonus in (0.0, 0.02):
            pull, theft = [], []
            for _ in range(5):
                halves = [rng.permutation(c) for c in clusters]
                centroids = [spec[h[: len(h) // 2]].mean(0) for h in halves]
                fake = SimpleNamespace(topic_embeddings_=np.vstack([T0] + centroids), _outliers=model._outliers)
                reviewed = set(range(n0 - model._outliers, n0 - model._outliers + len(halves)))
                for c, h in enumerate(halves):
                    held = h[len(h) // 2:]
                    t, _, _ = et_real.assign_existing_topics(fake, spec[held], reviewed, reviewed_bonus=bonus)
                    pull.append(np.mean(t == n0 - model._outliers + c))
                t_old, _, _ = et_real.assign_existing_topics(fake, E_old, reviewed, reviewed_bonus=bonus)
                theft.append(np.mean(np.isin(t_old, list(reviewed))))
            pull = np.array(pull).reshape(5, -1).mean(0)
            results[bonus] = (np.average(pull, weights=sizes), np.mean(theft))
            print(f"bonus {bonus}: M2 {results[bonus][0]:.0%} (per cluster {np.round(pull, 2).tolist()}), "
                  f"M3 {results[bonus][1]:.1%}")

        m2, m3 = results[0.02]
        assert m2 >= 0.70, f"i progetti futuri simili attirati dai topic revisionati sono solo {m2:.0%}"
        # il guadagno dipende dal batch: 2026-06 da 42% a 74%, 2026-10-15 da 68% a 83% (M3 3,1%)
        assert m2 >= results[0.0][0] + 0.1, "il bonus deve migliorare nettamente l'attrazione"
        assert m3 <= 0.05, f"troppi progetti già classificati rubati dai topic revisionati: {m3:.1%}"

    def test_existing_rule_on_real_store(self, real_db, et_real, monkeypatch):
        """Sui progetti reali e i topic revisionati reali: la penalità riduce gli spostamenti,
        e solo i progetti sotto soglia possono spostarsi. Sola lettura."""
        from bertopic import BERTopic
        review_mod = load_module(monkeypatch, "topic_review", HERE / "topic_review.py")
        store_mod = load_module(monkeypatch, "specter_store", HERE / "specter_store.py")
        model_dir = REAL_DATA / "old_topic_model"
        reviewed = review_mod.load_reviewed_topics(str(model_dir))
        hier = review_mod.Hierarchy.load(str(REAL_DATA / "topic2hier.json"))
        accepted = [t for t in sorted(reviewed) if hier.path(t)]
        if not accepted or not (REAL_DATA / "specter2.parquet").exists():
            pytest.skip("nessun topic revisionato o archivio Specter2 assente")
        model = BERTopic.load(str(model_dir))
        existing = review_mod.load_existing(real_db.open_table("projects_uncase"),
                                              str(REAL_DATA / "specter2.parquet"))
        counts = {}
        for bonus in (0.02, 0.0, -0.005):
            targets = [review_mod.Target(t, model.topic_embeddings_[t + model._outliers], hier.path(t), bonus, t)
                       for t in accepted]
            moves = review_mod.existing_moves(model, reviewed, existing, targets, 0.92, bonus)
            assert (moves["best_original"] < 0.92).all()
            counts[bonus] = len(moves)
        print(f"projects already in the db that would move to {accepted}: {counts}")
        assert counts[0.02] >= counts[0.0] >= counts[-0.005]
        assert counts[-0.005] <= 0.01 * len(existing.project_ids), "con la penalità restano spostamenti contenuti"

    def test_recomputed_bge_matches_precomputed(self, sb_slow, run_update):
        if not sb_slow.real_embeddings:
            pytest.skip("embedding precalcolati non disponibili")
        precomputed = sb_slow.bge_vectors()
        write_config(sb_slow, bge="")
        assert run_update(sb_slow, "--projects", "--no-review", fake_models=False).code == 0
        rows = sb_slow.df("projects_uncase").set_index("projectID").loc[sb_slow.new_ids]
        got = np.stack(rows["vector"].to_numpy())
        cos = (got * precomputed).sum(1) / (np.linalg.norm(got, axis=1) * np.linalg.norm(precomputed, axis=1))
        assert cos.min() > 0.98, f"similarità minima {cos.min():.3f}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
