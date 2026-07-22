# scripts/

Data-processing and figure-building logic for the dashboard, one module per page (plus helper submodules for the `projects` page's three tabs). These modules contain no Dash routing/layout code — they're imported by the matching `pages/*.py` module (see [`pages/README.md`](../pages/README.md)) and return plain Dash components (`html.Div`, `dcc.Graph`, ...) or serialized data ready to be placed in a `dcc.Store` / `dcc.Download`.

All modules read shared, preloaded DataFrames/arrays from [`utils.py`](../utils.py) rather than re-reading parquet files themselves.

| File | Used by | Responsibility |
| --- | --- | --- |
| `_rag.py` | `pages/rag.py` | Organisation autocomplete; loads the local ONNX BGE-M3 model (`data/bge-m3-onnx`) and encodes free-text queries; filters `org_projects_df` by Framework Programme / country / org type / organisation / topic, then ranks by cosine similarity against `RAG_EMBS` (threshold `THRESHOLD = 0.55`) when text is supplied, returning the matched indices alongside a `{projectID: cosine_score}` map; builds the CSV export with an embedded metadata header. |
| `_rag__projects_list.py` | `pages/rag.py` (Projects list tab) | Builds the paginated `dbc.Accordion` of retrieved projects, including collapsible Deliverables/Publications sub-tables, a per-project chat section, and — only when the retrieval had a free-text query — a "Why is this relevant?" relevance-explanation section (author/affiliation formatting, links out). |
| `_rag__chat.py` | `pages/rag.py` (per-project chat + relevance explanation) | Two LLM-backed features, both grounded in a project's `title`/`objective` plus the retrieval context stored in `query-context-store` (free-text query, active filters, cosine similarity score from `_rag.py`): `ask_project_chat(...)` is a multi-turn Q&A that resends the full running history each call; `explain_relevance(...)` is a single-shot, history-free call that asks for a 1-2 sentence explanation of why a project matched, returning `(explanation, model_name)` so the UI can show which model produced it. Both call an [Ollama](https://ollama.com/) server via `/api/chat`; the server URL and model are read live from `llm_settings.py` (repo root) on every call, so changes made on the Settings page (`pages/settings.py`) apply immediately without a restart. |
| `_rag__aggregated_view.py` | `pages/rag.py` (Aggregated view tab) | Builds the KPI row (clickable cards linking to chart anchors) and the breakdown bar/pie charts by country, organisation type, organisation (top-k, slider-controlled), and topic. |
| `_rag__latent_space.py` | `pages/rag.py` (Latent space tab) | Builds the 2D scatter plot (`D2_RAG_EMBS`) of retrieved projects plus their nearest neighbours (within `LATENT_SPACE_RADIUS`), colored either by group or by query-similarity gradient; points are jittered (`spread_points`) to reduce overplotting. Clicking a point opens the project on CORDIS (wired up in `app.py`'s clientside callback). |
| `_organisations.py` | `pages/organisations.py` | Organisation autocomplete; per-organisation KPIs and topic breakdown bar chart (`show_info`); joint-project accordion between two organisations (`compare_organisations`); CSV/JSON export (`download_file`). |
| `_topics.py` | `pages/topics.py` | Topic autocomplete; per-topic KPIs and top-organisations bar chart with Framework Programme/country/org-type/role filters (`show_info`); shared top-players chart between two topics (`join_topics`); CSV/JSON export (`download_file`). |
| `_overview.py` | `pages/overview.py` | Builds the hierarchical topic treemap (levels 1–4, colored by top-level macro-cluster) shown on the Concept page; builds the project-detail panel (`populate_doc_canvas`) shown in the Offcanvas sidebar when a point is clicked on the datamap. |

## Conventions

- `show_info(...)` functions return a tuple of `(dash_children, serialized_data_for_store, *KPI_strings)` so the calling page can fan the results out to multiple `Output`s in one callback.
- Cross-filtering between two selections (two orgs, two topics) is done by reading back the `dcc.Store` JSON (`pd.read_json(..., orient='split')`) written by each side's `show_info` call, rather than recomputing from scratch.
- Bar/pie charts consistently disable zoom/drag (`dragmode=False`, `xaxis_fixedrange`/`yaxis_fixedrange`) and use a `custom_hover`/`hovertemplate` string built ahead of time for consistent tooltips.
- Money values are aggregated in raw euros and only formatted for display at the last moment (`f'{round(eur / 1_000_000, 1)} M'` or `format_money`).
