import httpx
from utils import BASE_URL, API_KEY, projects_tbl

async def call_relevance_api(project_id, query):
    row = (
        projects_tbl.search()
        .select(["projectID", "title", "objective"])
        .where(f"projectID IN ({project_id})")
        .to_arrow()
    )
    title = row["title"][0].as_py()
    objective = row["objective"][0].as_py()

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "http://research-llm-api-matita:8060/v1/project/relevance",
            #headers={"X-API-Key": API_KEY},
            json={
                "project": {
                    "title": title,
                    "objective": objective,
                },
                "query_context": {
                    "query_text": query,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("explanation", "Explainability bot not available at the moment.")