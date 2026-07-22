# data/

Datasets and models loaded at startup by `utils.py`. **This folder is gitignored** (see the repo's `.gitignore`, which excludes `data/` and `*.parquet`) — its contents must be provided/generated separately and placed here before running the app.

All CORDIS data covers Horizon 2020 and Horizon Europe projects (Horizon Europe data current through end of 2024, per the Concept page).

| File | Loaded as | Description |
| --- | --- | --- |
| `docs.parquet` | `projects_df` | One row per CORDIS project: ID, title, objective/abstract, Framework Programme, topic assignment/hierarchy, participants, deliverable URL, etc. |
| `orgs.parquet` | `orgs_df` | One row per organisation: ID, name, country, activity type, URL. |
| `org_projects.parquet` | `org_projects_df` | Organisation ↔ project participation records (role, funding received, country, activity type) — the main table behind the Projects page filters and exports. |
| `org_topics.parquet` | `org_topics_df` | Organisation-level rollup of project counts, funding, and publication counts by topic — backs the Topics and Organisations pages. |
| `topics.parquet` | `topics_df` (columns `level_1..4`, `count`) | The 4-level hierarchical topic taxonomy structure and per-node project counts, used to build the Concept-page treemap. |
| `labels.pkl` | `labels_pkl` / `topic_names` | Pickle mapping topic node IDs to human-readable labels (LLM-generated). |
| `deliverables.parquet` | `deliverables_df` | Project deliverables (title, authors as JSON-encoded dict, download link), shown in the collapsible per-project section on the Projects page. |
| `publications.parquet` | `publications_df` | Scientific publications linked to projects (title, authors as JSON-encoded dict, link), shown alongside deliverables. |
| `bge_1024dim.npy` | `RAG_EMBS` | Precomputed 1024-dim BGE-M3 embeddings for every project in `docs.parquet` (row-aligned), used for semantic search cosine similarity. |
| `2D_embs.npy` | `D2_RAG_EMBS` | UMAP-reduced 2D projection of the same embeddings (row-aligned with `docs.parquet`), used for the latent-space scatter plots. |
| `bge-m3-onnx/` | — | Local ONNX export of [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (`config.json`, `tokenizer*.json`, `model.onnx`) plus its external weights file `model-001.onnx_data`, loaded via `optimum.onnxruntime.ORTModelForFeatureExtraction` in `scripts/_rag.py` to encode free-text search queries at request time. |

Row alignment matters: `RAG_EMBS[i]` and `D2_RAG_EMBS[i]` correspond to `projects_df.iloc[i]`, not to `projectID` — indices, not IDs, are threaded through the retrieval and latent-space code (`scripts/_rag.py`, `scripts/_rag__latent_space.py`).
