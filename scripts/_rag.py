import re
import torch
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

from utils import projects_tbl, participants_tbl, RETRIEVAL_THRESHOLD

_rag_tokenizer = None
_rag_model = None

def update_dropdown(search_value, country_list, typeorg_list):
    conditions = []

    if country_list:
        countries = ", ".join(f"'{c}'" for c in country_list)
        conditions.append(f"countryCode IN ({countries})")

    if typeorg_list:
        types = ", ".join(f"'{t}'" for t in typeorg_list)
        conditions.append(f"activityType IN ({types})")

    if search_value:
        safe_value = search_value.lower().replace("'", "''")
        conditions.append(f"LOWER(name) LIKE '%{safe_value}%'")

    where_clause = " AND ".join(conditions) if conditions else None

    query = participants_tbl.search().select(["name"])
    if where_clause:
        query = query.where(where_clause)

    arrow_tbl = query.limit(200).to_arrow()

    seen = set()
    result = []
    for name in arrow_tbl.column("name"):
        val = name.as_py()
        if val not in seen:
            seen.add(val)
            result.append(val)
            if len(result) == 20:
                break

    return [{'label': org, 'value': org} for org in result]


def get_rank_model():
    global _rag_tokenizer, _rag_model
    if _rag_model is None:
        _rag_tokenizer = AutoTokenizer.from_pretrained('data/bge-m3-onnx')
        _rag_model = ORTModelForFeatureExtraction.from_pretrained(
            'data/bge-m3-onnx', provider='CPUExecutionProvider'
        )
    return _rag_tokenizer, _rag_model


def normalize_for_embedding(text: str) -> str:
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def encode(text, max_length=8192):
    tokenizer, model = get_rank_model()
    text = normalize_for_embedding(text)

    inputs = tokenizer(
        text,
        max_length=max_length,
        padding=True,
        truncation=True,
        return_tensors='pt'
    )

    outputs = model(**inputs)
    
    embeddings = outputs.last_hidden_state[:, 0, :]
    
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
    
    return embeddings.detach().cpu().numpy()


def _sql_in_clause(values):
    formatted = []
    for v in values:
        if isinstance(v, str):
            escaped = v.replace("'", "''")  # escape apici per sicurezza
            formatted.append(f"'{escaped}'")
        else:
            formatted.append(str(v))  # numeri, niente apici
    return f"({', '.join(formatted)})"

def _sql_scalar_in_clause(column, values):
    return f"{column} IN {_sql_in_clause(values)}"

def _sql_array_overlap_clause(column, values):
    formatted = []
    for v in values:
        if isinstance(v, str):
            escaped = v.replace("'", "''")
            formatted.append(f"'{escaped}'")
        else:
            formatted.append(str(v))
    array_literal = f"[{', '.join(formatted)}]"
    return f"array_has_any({column}, {array_literal})"

def retrieve_results_df(fp_list, country_list, typeorg_list, org_list, topic_list,
                        user_input, coordinator=False,
                        min_results=50, expansion_threshold=0.60, base_threshold=0.55,
                        ):

    conditions = []
    if fp_list:
        conditions.append(_sql_scalar_in_clause("fp", fp_list))
    if topic_list:
        conditions.append(_sql_array_overlap_clause('topic_name_hierarchy', topic_list))
    if coordinator:
        conditions.append("role = 'coordinator'")
    if country_list:
        conditions.append(f"countryCode IN {_sql_in_clause(country_list)}")
    if typeorg_list:
        conditions.append(f"activityType IN {_sql_in_clause(typeorg_list)}")
    if org_list:
        conditions.append(f"name IN {_sql_in_clause(org_list)}")
    
    where_clause = " AND ".join(conditions) if conditions else None

    search_part = participants_tbl.search()
    if where_clause:
        search_part = search_part.where(where_clause)
    results_part = search_part.to_arrow()
    project_ids = results_part.column("projectID").unique()

    if not project_ids:
        return [], '' 
    project_tbl_where_clause = _sql_scalar_in_clause("projectID", project_ids)

    if not user_input:
        return project_ids, results_part.to_pandas().to_json(orient='split')

    query_emb = encode(user_input, max_length=8192)[0]

    search_proj = projects_tbl.search(query_emb).metric("cosine")
    if where_clause:
        search_proj = search_proj.where(project_tbl_where_clause, prefilter=True)
    results_proj = search_proj.limit(RETRIEVAL_THRESHOLD).to_pandas()   
    results_proj = results_proj[results_proj["_distance"] <= (1 - base_threshold)]

    if results_proj.empty:
        return [], ''
    
    results_proj = results_proj.sort_values("_distance")
    new_project_ids = results_proj['projectID'].tolist()

    top_score = results_proj.iloc[0]["_distance"]
    strong_results = results_proj[results_proj["_distance"] <= top_score * 1.10]
    # strong_results = results_proj[results_proj["_distance"] <= (1 - expansion_threshold)]
    
    if len(strong_results) >= min_results or len(strong_results) == 0:
        results_part = results_part.filter(
            pc.is_in(results_part["projectID"], value_set=pa.array(new_project_ids))
        )
        return new_project_ids, results_part.to_pandas().to_json(orient='split')

    # FALLBACK: ricerca dei progetti più soddisfacenti per la query.
    # Si attiva quando i risultati molto simili sono meno di 50.
    # Empiricamente, in questi casi vale la pena il rischio di overfitting per 
    # cercare più dati.

    seed_vectors = np.stack(strong_results["vector"].to_numpy())
    centroid = seed_vectors.mean(axis=0)
    centroid = centroid / np.linalg.norm(centroid)

    search2 = projects_tbl.search(centroid).metric("cosine")
    if where_clause:
        search2 = search2.where(project_tbl_where_clause, prefilter=True)
    expanded_results = search2.limit(RETRIEVAL_THRESHOLD).to_pandas()
    expanded_results = expanded_results[expanded_results["_distance"] <= (1 - base_threshold)]
    expanded_results = expanded_results.sort_values("_distance")
    expanded_results = pd.concat([strong_results, expanded_results], ignore_index=True)
    expanded_results = expanded_results.drop_duplicates(subset=["projectID"], keep="first")
    expanded_results = expanded_results.iloc[:RETRIEVAL_THRESHOLD]
    new_project_ids = expanded_results['projectID'].tolist()

    results_part = results_part.filter(
        pc.is_in(results_part["projectID"], value_set=pa.array(new_project_ids))
    )
    return new_project_ids, results_part.to_pandas().to_json(orient='split')