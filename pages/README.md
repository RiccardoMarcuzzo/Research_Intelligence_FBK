# pages/

Route definitions for the Dash app. Each module is registered via `dash.register_page` (Dash's [multi-page apps](https://dash.plotly.com/urls) feature) and contains both the page `layout` and its `@callback` functions. Business logic (data filtering, aggregation, figure building) lives in the corresponding module under [`scripts/`](../scripts/README.md), keeping these files focused on layout and Dash wiring.

| File | Route | Nav label | Purpose |
| --- | --- | --- | --- |
| `rag.py` | `/projects` (order 0) | Projects | Filter- and free-text-driven semantic search over CORDIS projects. Renders three tabs: a paginated accordion project list, an aggregated statistics view, and a 2D latent-space scatter plot. Each project in the list also has an "Ask about this project" chat section, plus — only when the search included free text — a "Why is this relevant?" button giving a one-shot 1-2 sentence relevance explanation. Delegates to `scripts/_rag.py`, `_rag__projects_list.py`, `_rag__aggregated_view.py`, `_rag__latent_space.py`, and `_rag__chat.py`. |
| `organisations.py` | `/organisations` (order 1) | Organisations | Look up an organisation's topic breakdown (KPIs + bar chart + project accordion), with filters for Framework Programme and role, and a side-by-side comparison against a second organisation to surface joint projects. Delegates to `scripts/_organisations.py`. |
| `topics.py` | `/topics` (order 2) | Topics | Look up a topic's top organisations by project count, funding, or publications, with filters for Framework Programme, country, organisation type, and role, plus a comparison against a second topic. Delegates to `scripts/_topics.py`. |
| `overview.py` | `/concept` (order 3) | Concept | Landing/overview page: dataset-wide KPIs, an embedded interactive datamap (`assets/dmp_for_dash.html`) with a project-detail side panel, a topic treemap, and short descriptions linking to the other three pages. Delegates to `scripts/_overview.py`. |
| `settings.py` | `/settings` (order 5) | Settings | Lets the user view/edit the Ollama URL and model used by the per-project chat, "test connection" against a given URL to list the models actually installed there, and persist the choice to `llm_settings.json` via `llm_settings.py` (repo root) — no restart needed. |
| `about.py` | *(default path, order 6)* | — | Static credits page for the underlying thesis/project. |

## Conventions

- Each page sets `title=f"{PAGE_TITLE} | {TITLE}"` (from `utils.TITLE`) and an `order` used by Dash to sort pages / build the navbar in `app.py`.
- Filter widgets follow a `*-filter-proj` / `*-filter` / `*-filter-org` ID suffix convention depending on the page (projects / topics / organisations respectively), to keep callback `Input`/`State` IDs unambiguous.
- Pages that support two-way comparison (`organisations.py`, `topics.py`) duplicate their KPI cards, dropdowns, and `dcc.Store` components with a `1`/`2` suffix and reuse the same `scripts.show_info(...)` function with different arguments.
- Downloadable data (CSV/JSON) is produced by a `download_file(...)` function in the matching `scripts/_*.py` module and streamed via `dcc.Download`.
- Per-project collapsible sections (Deliverables, Publications, chat) all share one generic pattern-matching toggle callback keyed on `{'type': 'section-toggle', 'project': ..., 'section': ...}`, so a new section type doesn't need its own open/close callback.
- Per-project LLM features (chat, relevance explanation) each get their own `{'type': ..., 'project': projectID}` pattern-matching ID family (`chat-*`, `relevance-*`) with a `MATCH`-keyed callback, so every project's chat/explanation is independent and state-isolated without per-project Python loops over callbacks.
