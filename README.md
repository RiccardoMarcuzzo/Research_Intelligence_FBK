# Research Intelligence Tool (FBK)

A [Dash](https://dash.plotly.com/) web application for exploring EU-funded research data from [CORDIS](https://cordis.europa.eu/) (Horizon 2020 and Horizon Europe). The tool combines an LLM-derived topic taxonomy, semantic (RAG-style) project search, and interactive visual analytics to let users explore projects, organisations, and research topics, and how they connect.

This project builds on the topic modeling / taxonomy work from [Ex-CORDIS](https://github.com/RiccardoMarcuzzo/Ex-CORDIS) and layers a multi-page analytics dashboard on top of it.

## Features

- **Projects** (`/projects`): natural-language / filter-based semantic search over the CORDIS project corpus, with a paginated project list, an aggregated statistics view, and a 2D latent-space map of retrieved projects and their neighbours. Each project also gets two LLM-backed features (via [Ollama](https://ollama.com/)), both grounded in that project's title/objective plus the search query, active filters, and similarity score: an "Ask about this project" multi-turn chat, and — when the search included free text — a one-click "Why is this relevant?" box giving a 1-2 sentence, single-shot explanation (with the generating model name shown, for comparing across models).
- **Topics** (`/topics`): browse the LLM-generated topic taxonomy, rank organisations within a topic by number of projects, funding, or publications, and compare two topics to find shared top players.
- **Organisations** (`/organisations`): look up an organisation's research footprint by topic, and compare two organisations to find joint projects.
- **Concept** (`/concept`, the home page): an overview of the dataset with KPIs, an interactive latent-space datamap (via [DataMapPlot](https://github.com/TutteInstitute/datamapplot)), and a topic treemap.
- **Settings** (`/settings`): configure the Ollama server URL and model used by the per-project chat, test the connection (lists the models actually installed on that server), and save — takes effect immediately, no restart required.
- **About** (`/about`): project/thesis credits.

Every data page supports filtering (Framework Programme, country, organisation type/role, topic) and CSV/JSON export of the current view.

## Architecture

The app is a single [Dash](https://dash.plotly.com/) instance using [`use_pages`](https://dash.plotly.com/urls) for multi-page routing, [Dash Bootstrap Components](https://dash-bootstrap-components.opensource.faculty.ai/) (Cyborg theme) for layout/styling, and [Plotly](https://plotly.com/python/) for charts.

```text
app.py           # Dash app instantiation, navbar, page routing, global clientside callbacks
utils.py         # CLI args, data loading (parquet/pickle/npy), shared constants (country codes, etc.)
llm_settings.py  # Persisted (llm_settings.json), live-editable Ollama URL/model used by the chat feature
pages/           # One module per route: layout + callbacks (see pages/README.md)
scripts/         # Data-processing / figure-building logic used by pages (see scripts/README.md)
assets/          # CSS, JS, images, and the standalone datamap HTML (see assets/README.md)
data/            # Parquet datasets, embeddings, and the ONNX ranking model (gitignored, see data/README.md)
```

Data is loaded once at startup in `utils.py` into module-level pandas DataFrames (`projects_df`, `orgs_df`, `topics_df`, `org_topics_df`, `org_projects_df`, `deliverables_df`, `publications_df`) and NumPy arrays (`RAG_EMBS`, `D2_RAG_EMBS`), then imported wherever needed. Each `pages/*.py` module registers its layout and callbacks with Dash and delegates data wrangling / figure construction to a matching module in `scripts/`.

Semantic search embeds the user's query with a local ONNX build of [BGE-M3](https://huggingface.co/BAAI/bge-m3) (via `optimum`/`onnxruntime`) and ranks projects by cosine similarity against precomputed project embeddings.

Per-project chat (on the Projects page) sends the project's `title`/`objective`, the retrieval context (search query, active filters, and that project's cosine similarity score, threaded through via `query-context-store`), and the running conversation to a locally running [Ollama](https://ollama.com/) server for a grounded reply — see `scripts/_rag__chat.py`. The target URL and model are read live from `llm_settings.py` on every request, so they can be changed from the Settings page (`pages/settings.py`) without restarting the app.

## Requirements

- Python 3.11+ (`numpy==2.3.2` requires it)
- Dependencies listed in `requirements.txt` (Dash, dash-bootstrap-components, Flask, pandas, numpy, plotly, scikit-learn, torch, transformers, optimum/optimum-onnx, onnxruntime, pyarrow, rank_bm25, requests)
- The contents of `data/` (parquet files, embeddings, and the ONNX model) — gitignored, must be provided separately
- [Ollama](https://ollama.com/) running with the `qwen3.6:latest` model pulled, for the per-project chat feature — reachable at `127.0.0.1:11434` by default, changeable any time from the in-app Settings page (see below)

## Setup

```bash
pip install -r requirements.txt
```

Place the required data files under `data/` (see `data/README.md` for the expected layout).

## Running the app

```bash
python app.py --path /research_intelligence/ --port 8050
```

- `--path`: base URL prefix the app is served under (default `/research_intelligence/`). The root `/` route redirects to `<path>/projects`.
- `--port`: port to listen on (default `8050`).
- `--llm-url`: initial Ollama server URL for the per-project chat (default `http://127.0.0.1:11434`, or the `OLLAMA_URL` env var if set). Only used to seed `llm_settings.json` the first time the app runs — after that, the persisted file (editable from the Settings page) takes over and this flag is ignored.

The app runs in debug mode on `0.0.0.0` by default (see the bottom of `app.py`).
