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
This code develops a Research Intelligence platform on the CORDIS database, 
which is the European Union information system for projects funded in the European framework programmes.

Its goals are to help identify organisation partners for a given project proposal, 
and to explore the European research landscape.

Data are not provided, but can be downloaded from [here](https://cordis.europa.eu/projects), 
in the section "Download projects as open data".

## Features

### Filters and inputs
The platform provides a range of filters to help narrowing one's research. 
As shown in the screenshot below, the possible filters are: 
- **framework programme**: includes only the projects approved in the specified framework programmes;
- **country**: includes only the projects carried by organisations from the given countries;
- **organisation type**: includes only the projects where there were at least one organisation of the types specified
  public body, private company, research organisation, higher education establishment, other);
- **organisation name**: includes only the projects where the given organisations were involved;
- **topic**: filters out only the projects pertaining to the given topics (see [below](#topics));
- **custom input**: lets users insert a custom string to better narrow their interests (see [below](#custom-input));
- **coordinator**: retrieves only the projects for the given organisations where the aforementioned organisations coordinated them. 

<img width="1866" height="285" alt="Screenshot from 2026-07-21 14-11-38" src="https://github.com/user-attachments/assets/f2963dd4-f4a7-4604-abea-6f67e4b79823" />

#### Topics
Topics were found using BERTopic with HDBSCAN and Specter2 embedding model. For each project, the embedding was retrieved from its title and objective.
The found topics were afterwards organised in a 4 level taxonomy, using a Human-in-the-Loop approach and agglomerative clustering.
The resulting taxonomy is open for inspection in the Concept page.  

#### Custom input
The dashboard lets users define their own queries, in order to maximise usability and customisation. 
Some examples on what can be written here:
- users can search directly for a project title, objective or acronym (e.g. "ODEUROPA");
- users can ask for a certain category not found in the topic section, or difficult to define there (e.g. "disinformation in public speech");
- since the platform main goal is to help writing proposals, users can insert their whole proposal or project objective.

Given a custom input, the platform embeds it and search for the most similar projects. 
Internal tests discovered [BAAI's bge-m3 embedding model](https://huggingface.co/BAAI/bge-m3) suits this purpose the best.

### Results
Results are shown in three separate tabs. It is also possibile to download the .csv file of the results.

#### Tab "Project list"
It shows the list of projects retrieved by the combination of filters. 
If the custom input is defined, the order reflects the relevance of the documents towards the input.

<img width="1809" height="847" alt="Screenshot from 2026-07-21 14-35-33" src="https://github.com/user-attachments/assets/5b82f640-295c-4507-bf09-bf6ea016f54f" />

For every project, their title, programme, topic, participants and objective are displayed. Furthermore, the deliverables and publications linked to that project are shown, enriched with their authors and organisation, and a link to the source. Publications metadata were retrieved combining CORDIS and Scopus databases; deliverables metadata were found using a custom pipeline parsing the pdf documents with a GenAI model.

<img width="1643" height="817" alt="Progetto senza titolo" src="https://github.com/user-attachments/assets/11c390c2-f8ef-464f-aa8f-dd6b4d420fe5" />

#### Tab "Aggregated view"
It groups the information retrieved and show how every country, organisation type, organisation and topic contributes to the overall landscape found with one's query.
It is possible to define the comparison metric: number of projects participated, amount of money received, or number of organisation involved.

<img width="1803" height="852" alt="Screenshot from 2026-07-21 14-33-29" src="https://github.com/user-attachments/assets/b630d52b-482e-4b1f-b84d-3654f4694dc1" />

#### Tab "Latent space"
It projects the results shown in the "Project list" tab onto a different latent space. Coloured points are for the results. Grey points are the neighbours of those results in the new latent space.

The new latent space is the same as the one used for the topic modeling. In this way, users can explore a different view on the projects, and found thematic-similar projects to the ones retrieved.

<img width="1801" height="850" alt="Screenshot from 2026-07-21 14-34-09" src="https://github.com/user-attachments/assets/7b63a5ee-ab34-4848-adbb-8b42c96c00e3" />
