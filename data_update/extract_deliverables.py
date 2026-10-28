# ------------------------------------------------------------------------------
# Estrae gli autori dei deliverables dai pdf e scrive un parquet che update_db.py (step 3)
# legge al posto del fallback automatico (deliverables dell'export + autori già nel db).
# Sostituisce legacy_extract_deliverables.py: un solo lancio, nessun file intermedio
# (niente jsonl, niente INDEX nel .env).
#
# Per ogni deliverable dell'export (cordis_loader.load_deliverables, solo formato records):
#   - id, projectID, title, physUrl vengono dall'export (il titolo è quello ufficiale, non
#     quello letto dall'LLM);
#   - gli autori già noti si riusano senza chiamare l'LLM: dal parquet di un lancio
#     precedente (stesso id e stesso physUrl) e dalla tabella deliverables del db
#     (per id, poi per physUrl);
#   - gli altri: download del pdf -> markdown delle prime 3 pagine (pymupdf, se non basta
#     docling) -> LLM -> autori.
#
# Il servizio LLM (API compatibile con OpenAI) si configura nel .env di deliverables_env_path:
# LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.
#
# Colonne del parquet: id, projectID (int32), title, physUrl, authors (JSON
# {nome: affiliazione}, "{}" se ignoti, come nella tabella) e status:
#   ok       autori estratti ora ("{}" se l'LLM non ne ha trovati)
#   carried  autori già noti (db o lancio precedente)
#   no_url   il deliverable non ha un link
#   error    pdf non scaricabile / non leggibile / LLM fallito: riprovato al lancio dopo
#   pending  non ancora provato (lancio interrotto o --limit): riprovato al lancio dopo
# Il parquet è anche il checkpoint: viene riscritto dopo ogni batch, e rilanciando lo script
# si riprende da dove si era arrivati.
#
# Uso (da data_update/):
#   python extract_deliverables.py [--out FILE] [--limit N] [--config PATH]
# poi in settings.config: deliverables_file = <FILE>, e python update_db.py --deliverables
# ------------------------------------------------------------------------------
import os
import re
import io
import sys
import json
import asyncio
import argparse
import logging
from configparser import ConfigParser
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv
from tqdm.asyncio import tqdm

from cordis_loader import load_deliverables, CordisFormatError

logging.getLogger("docling").setLevel(logging.WARNING)

BATCH_SIZE = 100
N_WORKERS = 4
# servizio LLM (qualsiasi API compatibile con OpenAI), configurato nel .env
LLM_ENV = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
PDF_PAGES = 3                 # pagine lette da pymupdf
DOCLING_MAX_CHARS = 5000      # testo passato all'LLM dopo docling

COLUMNS = ['id', 'projectID', 'title', 'physUrl', 'authors', 'status']
DONE_STATUS = {'ok', 'carried', 'no_url'}
NO_AUTHORS = '{}'
ERR_PDF = "PDF non scaricabile o non parsabile"

SYSTEM_PROMPT = """You are an information extraction system.
Given the first pages of an EU project deliverable, extract the authors of THIS document
and return them as a JSON object:\n

- "authors": a dictionary where keys are author names and values are their affiliations.
Include ONLY the authors of THIS document, listed on the cover page or header. \n

IMPORTANT RULES:\n
- Do NOT include reviewers, contributors, project coordinators, or partners
unless they are explicitly listed as authors \n
- Do NOT include authors of cited publications, related works, or bibliography entries \n
- Do NOT include names found in sections titled "Reviewers", "Review History",
"Contributors", "Related Publications", "Acknowledgements" \n
- If an affiliation is not present for an author, use "Unknown" as the value \n
- If you cannot find the authors, leave the field as null \n

Return strictly valid JSON with no preamble, no markdown, no backticks. \n

DOCUMENT:\n\n
"""

_docling_converter = None


# ------------------------------------------------------------------------------
# pdf -> markdown
# ------------------------------------------------------------------------------
async def download_pdf(download_page_url):
    """Scarica il pdf dall'url della pagina di download (che rimanda al file con un
    window.location). None se non è una stringa o il download fallisce."""
    if not isinstance(download_page_url, str):
        return None
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"},
                                     follow_redirects=True, timeout=30) as session:
            r = await session.get(download_page_url)
            match = re.search(r"window\.location='([^']+)'", r.text)
            if not match:
                return None
            r2 = await session.get(match.group(1), headers={"Accept-Encoding": "identity"})
            return r2.content
    except Exception as e:
        print(f"[HTTP] Errore download su {download_page_url}: {e}")
        return None


def pdf_to_markdown_pymupdf(pdf):
    """Prime PDF_PAGES pagine in markdown; None se il pdf non si apre o non ha testo."""
    import pymupdf, pymupdf4llm
    try:
        doc = pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf")
        text = pymupdf4llm.to_markdown(doc, pages=list(range(min(PDF_PAGES, doc.page_count))))
        return text if text and text.strip() else None
    except Exception:
        return None


def pdf_to_markdown_docling(pdf):
    """Più lento di pymupdf ma legge anche i pdf che quello non riesce ad aprire."""
    global _docling_converter
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import DocumentStream
        if _docling_converter is None:
            _docling_converter = DocumentConverter()
        result = _docling_converter.convert(DocumentStream(name="document.pdf", stream=io.BytesIO(pdf)))
        text = result.document.export_to_markdown()[:DOCLING_MAX_CHARS]
        return text if text.strip() else None
    except Exception as e:
        print(f"[DOCLING] Errore parsing: {e}")
        return None


# ------------------------------------------------------------------------------
# LLM
# ------------------------------------------------------------------------------
def normalize_authors(raw):
    """JSON {nome: affiliazione} per la colonna authors. '{}' se l'LLM non ha trovato
    autori o ha risposto in un altro formato."""
    if not isinstance(raw, dict):
        return NO_AUTHORS
    authors = {str(k).strip(): (str(v).strip() if v else "Unknown") or "Unknown"
               for k, v in raw.items() if k and str(k).strip()}
    return json.dumps(authors) if authors else NO_AUTHORS


async def extract_authors(client, markdown):
    """(authors JSON, errore). Due tentativi se la risposta non è un JSON valido."""
    raw = ""
    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=os.environ["LLM_MODEL"],
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": markdown}],
                max_tokens=1000,
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            return normalize_authors(parsed.get("authors") if isinstance(parsed, dict) else None), None
        except json.JSONDecodeError as e:
            if attempt == 1:
                return NO_AUTHORS, f"JSON malformato dopo 2 tentativi: {e} | raw: {raw[:200]}"
        except Exception as e:
            return NO_AUTHORS, f"Errore chiamata LLM: {e}"


async def process_deliverable(url, client, semaphore):
    """Download -> markdown (pymupdf, poi docling) -> LLM. {'authors', 'status'[, 'error_msg']}"""
    async with semaphore:
        pdf = await download_pdf(url)
        if pdf is None:
            return {"authors": NO_AUTHORS, "status": "error", "error_msg": ERR_PDF}
        loop = asyncio.get_running_loop()
        markdown = await loop.run_in_executor(None, pdf_to_markdown_pymupdf, pdf)
        if markdown is None:
            markdown = await loop.run_in_executor(None, pdf_to_markdown_docling, pdf)
        if markdown is None:
            return {"authors": NO_AUTHORS, "status": "error", "error_msg": ERR_PDF}
        authors, error = await extract_authors(client, markdown)
        if error:
            return {"authors": NO_AUTHORS, "status": "error", "error_msg": error}
        return {"authors": authors, "status": "ok"}


# ------------------------------------------------------------------------------
# tabella di lavoro
# ------------------------------------------------------------------------------
def known_authors_from_db(data_dir):
    """Autori già estratti (diversi da '{}') nella tabella deliverables del db, per id e per
    physUrl. Due Series vuote se il db o la tabella non ci sono."""
    empty = pd.Series(dtype=object)
    try:
        import lancedb
        current = lancedb.connect(data_dir).open_table("deliverables").to_pandas()
    except Exception as e:
        print(f"deliverables del db non lette ({e}): nessun autore riusato dal db.")
        return empty, empty
    current = current[current['authors'].notna() & (current['authors'] != NO_AUTHORS)]
    by_id = current.dropna(subset=['id']).drop_duplicates('id').set_index('id')['authors'] \
        if 'id' in current else empty
    by_url = current.dropna(subset=['physUrl']).drop_duplicates('physUrl').set_index('physUrl')['authors']
    return by_id, by_url


def build_table(export, previous, db_by_id, db_by_url):
    """Una riga per deliverable dell'export, con gli autori già noti e lo status di partenza.
    previous: parquet di un lancio precedente (o None): conta solo se il physUrl non è cambiato."""
    table = export[['id', 'projectID', 'title', 'physUrl']].copy()
    table['authors'] = NO_AUTHORS
    table['status'] = 'pending'

    table.loc[table['physUrl'].isna(), 'status'] = 'no_url'

    if previous is not None and len(previous):
        prev = previous.drop_duplicates('id').set_index('id')
        same_url = table['id'].map(prev['physUrl']).eq(table['physUrl']) | \
            (table['id'].map(prev['physUrl']).isna() & table['physUrl'].isna())
        prev_status = table['id'].map(prev['status'])
        reuse = same_url & prev_status.isin(DONE_STATUS) & table['id'].isin(prev.index)
        table.loc[reuse, 'authors'] = table.loc[reuse, 'id'].map(prev['authors'])
        table.loc[reuse, 'status'] = prev_status[reuse]

    todo = table['status'] == 'pending'
    from_db = table.loc[todo, 'id'].map(db_by_id)
    from_db = from_db.where(from_db.notna(), table.loc[todo, 'physUrl'].map(db_by_url))
    found = from_db.notna()
    table.loc[found[found].index, 'authors'] = from_db[found]
    table.loc[found[found].index, 'status'] = 'carried'
    return table


def write_table(table, path):
    """Scrittura atomica: un lancio interrotto non lascia mai un file a metà."""
    out = table[COLUMNS].copy()
    out['projectID'] = out['projectID'].astype('int32')
    schema = pa.schema([('id', pa.string()), ('projectID', pa.int32()), ('title', pa.string()),
                        ('physUrl', pa.string()), ('authors', pa.string()), ('status', pa.string())])
    tmp = f"{path}.tmp"
    pq.write_table(pa.Table.from_pandas(out, schema=schema, preserve_index=False), tmp)
    os.replace(tmp, path)


async def extract_all(table, path, client, limit=None):
    """Elabora i deliverables 'pending' / 'error' di table, a batch, riscrivendo path dopo
    ognuno. Modifica table sul posto."""
    todo = table.index[table['status'].isin(['pending', 'error'])].tolist()
    if limit is not None:
        todo = todo[:limit]
    print(f"{len(todo)} deliverables to read from the pdf.")
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        semaphore = asyncio.Semaphore(N_WORKERS)
        results = await tqdm.gather(
            *[process_deliverable(table.at[i, 'physUrl'], client, semaphore) for i in batch],
            desc="Processing deliverables")
        for i, res in zip(batch, results):
            table.at[i, 'authors'] = res['authors']
            table.at[i, 'status'] = res['status']
        write_table(table, path)
        print(f"{start + len(batch)}/{len(todo)} done, saved in {path}.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estrae gli autori dei deliverables dai pdf "
                                                 "(vedi il commento in cima al file)")
    parser.add_argument("--out", help="parquet di output (default: deliverables_file di "
                                      "settings.config, altrimenti new_data/deliverables_<export>.parquet)")
    parser.add_argument("--limit", type=int, help="al massimo N pdf in questo lancio (prove)")
    parser.add_argument("--config", default=str(Path(__file__).with_name("settings.config")))
    parser.add_argument("--data", default="../data", help="cartella del db (autori già noti)")
    args = parser.parse_args(argv)

    config = ConfigParser()
    if not config.read(args.config):
        print(f"File di configurazione non trovato: {args.config}")
        return 1
    folder = config["paths"]["new_data_folder_name"]
    env_path = config.get("paths", "deliverables_env_path", fallback="").strip()
    load_dotenv(env_path or None)
    out = args.out or config.get("paths", "deliverables_file", fallback="").strip() \
        or os.path.join("new_data", f"deliverables_{os.path.basename(os.path.normpath(folder))}.parquet")

    try:
        export = load_deliverables(folder)
    except CordisFormatError as e:
        print(e)
        return 1

    previous = pd.read_parquet(out) if os.path.exists(out) else None
    if previous is not None and not {'id', 'physUrl', 'authors', 'status'} <= set(previous.columns):
        print(f"{out} exists but is not an output of this script (columns: {list(previous.columns)}). "
              "Choose another --out.")
        return 1

    by_id, by_url = known_authors_from_db(args.data)
    table = build_table(export, previous, by_id, by_url)
    print(table['status'].value_counts().to_string())
    write_table(table, out)

    if table['status'].isin(['pending', 'error']).any() and args.limit != 0:
        missing = [k for k in LLM_ENV if not os.environ.get(k)]
        if missing:
            print(f"Not set: {', '.join(missing)} (put them in the .env file).")
            return 1
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"])
        asyncio.run(extract_all(table, out, client, args.limit))

    left = int(table['status'].isin(['pending', 'error']).sum())
    print(f"Done: {out} ({len(table)} deliverables, {left} without authors still to read; "
          "run again to retry them)." if left else f"Done: {out} ({len(table)} deliverables).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
