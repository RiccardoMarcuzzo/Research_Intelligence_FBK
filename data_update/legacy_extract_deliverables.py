import os
import re
import io
import json
import asyncio
import httpx
import logging
from configparser import ConfigParser
from dotenv import load_dotenv, set_key
from pathlib import Path

import pandas as pd
import pymupdf4llm, pymupdf
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import DocumentStream

logging.getLogger("docling").setLevel(logging.WARNING)

load_dotenv()
FEATHERLESS_API_KEY = os.environ.get('FEATHERLESS_API_KEY')
INDEX = int(os.environ.get('INDEX'))

CONFIG_PATH = Path(__file__).with_name("settings.config")
config = ConfigParser()
config.read(CONFIG_PATH)
NEW_DATA_FOLDER_NAME = config["paths"]["new_data_folder_name"]


BATCH_SIZE = 100
N_WORKERS = 4
MODEL = "Qwen/Qwen2.5-14B-Instruct"
OUTPUT_PATH = config['paths']['deliverables_file']
ENV_PATH = config['paths']['deliverables_env_path']

deliverables_df = pd.read_json(os.path.join(NEW_DATA_FOLDER_NAME, 'webLink.json'))
deliverables_df = deliverables_df[deliverables_df['type'] == 'projectDeliverable']

CONVERTER = DocumentConverter()

client = AsyncOpenAI(
    api_key=FEATHERLESS_API_KEY,
    base_url="https://api.featherless.ai/v1",
)

system_prompt = """You are an information extraction system. 
Given the first pages of an EU project deliverable, extract the following fields 
and return them as a JSON object:\n

- "title": the title of THIS deliverable document 
(usually found in the header or cover page of the document itself, 
NOT in cited publications or related works lists)\n
- "authors": a dictionary where keys are author names and values are their affiliations. 
Include ONLY the authors of THIS document, listed on the cover page or header. \n

IMPORTANT RULES:\n
- Do NOT include reviewers, contributors, project coordinators, or partners 
unless they are explicitly listed as authors \n
- Do NOT include authors of cited publications, related works, or bibliography entries \n
- Do NOT include names found in sections titled "Reviewers", "Review History", 
"Contributors", "Related Publications", "Acknowledgements" \n
- If an affiliation is not present for an author, use "Unknown" as the value \n
- If you cannot find the title or authors, leave the field as null \n

Return strictly valid JSON with no preamble, no markdown, no backticks. \n

DOCUMENT:\n\n
"""


def pagine(da, a):
    return list(range(da - 1, a))


async def convert_with_pymupdf(download_page_url: str) -> str | None:
    """Scarica il PDF dall'url della pagina di download, lo converte in markdown (prime 3 pagine)."""
    if not isinstance(download_page_url, str):
        return None
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=30
        ) as session:
            r = await session.get(download_page_url)
            match = re.search(r"window\.location='([^']+)'", r.text)
            if not match:
                return None
            pdf_url = match.group(1)
            r2 = await session.get(pdf_url, headers={"Accept-Encoding": "identity"})
            buf = io.BytesIO(r2.content)
            doc = pymupdf.open(stream=buf, filetype="pdf")
            # FIX: se il PDF ha meno di 3 pagine, pages=[0,1,2] sollevava un errore
            # (pagina inesistente) e il documento veniva scartato come "non parsabile".
            return pymupdf4llm.to_markdown(doc, pages=pagine(1, min(3, doc.page_count)))
    except Exception as e:
        print(f"Errore su {download_page_url}: {e}")
        return None


async def convert_with_docling(download_page_url: str) -> str | None:
    """Scarica il PDF dall'url della pagina di download, lo converte in markdown con docling."""
    if not isinstance(download_page_url, str):
        return None
    
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=30
        ) as session:
            r = await session.get(download_page_url)
            match = re.search(r"window\.location='([^']+)'", r.text)
            if not match:
                print(f"[HTTP] Redirect URL non trovato per {download_page_url}")
                return None
            pdf_url = match.group(1)
            r2 = await session.get(pdf_url, headers={"Accept-Encoding": "identity"})
            buf = io.BytesIO(r2.content)
    except Exception as e:
        print(f"[HTTP] Errore download su {download_page_url}: {e}")
        return None

    try:
        def parse():
            stream = DocumentStream(name="document.pdf", stream=buf)
            result = CONVERTER.convert(stream)
            return result.document.export_to_markdown()[:5000]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, parse)
    except Exception as e:
        print(f"[DOCLING] Errore parsing su {download_page_url}: {e}")
        return None


async def extract_deliverables_info(markdown_text: str) -> dict:
    """
    Chiama il modello LLM con il testo markdown del deliverable.
    Tenta fino a 2 volte in caso di JSON malformato.
    Restituisce un dict con 'title', 'authors', 'status', e opzionalmente 'error_msg'.
    """
    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": markdown_text}
                ],
                max_tokens=1000,
                temperature=0.0
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            parsed["status"] = "ok"
            return parsed
        except json.JSONDecodeError as e:
            if attempt == 0:
                continue  # retry
            return {
                "title": None,
                "authors": None,
                "status": "error",
                "error_msg": f"JSON malformato dopo 2 tentativi: {e} | raw: {raw[:200]}"
            }
        except Exception as e:
            return {
                "title": None,
                "authors": None,
                "status": "error",
                "error_msg": f"Errore chiamata LLM: {e}"
            }


async def process_deliverable(row: pd.Series, semaphore: asyncio.Semaphore, 
                              docling: bool = False) -> dict:
    """
    Pipeline completa per un singolo deliverable:
    download PDF -> markdown -> LLM -> dict finale con physUrl, projectID, status.
    Il semaforo limita la concurrency sull'intera pipeline.
    """
    async with semaphore:
        phys_url = row.get("physUrl")
        project_id = row.get("projectID")

        if docling:
            markdown = await convert_with_docling(phys_url)
        else:
            markdown = await convert_with_pymupdf(phys_url)

        if markdown is None:
            return {
                "physUrl": phys_url,
                "projectID": project_id,
                "title": None,
                "authors": None,
                "status": "error",
                "error_msg": "PDF non scaricabile o non parsabile"
            }

        info = await extract_deliverables_info(markdown)

        return {
            "physUrl": phys_url,
            "projectID": project_id,
            **info  # contiene title, authors, status, e opzionalmente error_msg
        }


async def main():
    """
    Gestisce la concurrency sul batch corrente.
    Al termine, salva i risultati in JSONL e aggiorna INDEX nel file .env.
    """
    global INDEX
    original_df = deliverables_df.copy()
    while INDEX < 200_000:
        batch = original_df.iloc[INDEX:INDEX + BATCH_SIZE]
        if batch.empty:
            print("Tutti i deliverable processati")
            break

        semaphore = asyncio.Semaphore(N_WORKERS)

        tasks = [
            process_deliverable(row, semaphore)
            for _, row in batch.iterrows()
        ]

        results = await tqdm.gather(*tasks, desc="Processing deliverables")

        # Scrittura unica su disco al termine del batch
        with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
            for record in results:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Aggiorna INDEX nel .env senza toccare FEATHERLESS_API_KEY
        INDEX += len(batch)
        set_key(ENV_PATH, "INDEX", str(INDEX))
        print(f"Batch completato. Nuovo INDEX: {INDEX}. Risultati salvati in {OUTPUT_PATH}.")

async def main_deep_pdf_parsing():
    """
    Utilizza docling per parsare i documenti che non è riuscito a scaricare
    precedentemente. Salva i progressi ogni 1000 righe processate.
    """
    done_df = pd.read_json(OUTPUT_PATH, lines=True)
    mask = (
        (done_df['status'] == 'error')
        & (done_df['error_msg'] == "PDF non scaricabile o non parsabile")
    )
    to_parse = done_df[mask]

    index = 0
    checkpoint = 0

    while index < len(to_parse):
        parsed_records = []

        next_checkpoint = min(checkpoint + 500, len(to_parse))

        while index < next_checkpoint:
            batch = to_parse.iloc[index: min(index + BATCH_SIZE, next_checkpoint)]
            if batch.empty:
                break

            semaphore = asyncio.Semaphore(N_WORKERS)

            tasks = [
                process_deliverable(row, semaphore, docling=True)
                for _, row in batch.iterrows()
            ]

            results = await tqdm.gather(
                *tasks,
                desc=f"Parsing batch {index}-{index + len(batch)}"
            )
            parsed_records.extend(results)
            index += len(batch)

        if parsed_records:
            parsed_df = pd.DataFrame(parsed_records)
            block_index = to_parse.index[checkpoint:index]
            parsed_df.index = block_index
            done_df.loc[block_index, 'error_msg'] = None
            done_df.update(parsed_df)

            tmp_path = f"{OUTPUT_PATH}.tmp"
            done_df.to_json(tmp_path, orient='records', lines=True, force_ascii=False)
            os.replace(tmp_path, OUTPUT_PATH)
            print(f"Checkpoint salvato: {index}/{len(to_parse)} righe processate.")

        checkpoint = index

    print(f"Completato. Risultati salvati in {OUTPUT_PATH}.")

if __name__ == "__main__":
    asyncio.run(main_deep_pdf_parsing())