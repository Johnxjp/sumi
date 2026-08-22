import inspect
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.annotation.models import AnnotateRequest, SearchRequest, SearchResponse
from src.annotation.pooling import pool_results
from src.annotation.retrievers import load_retrievers
from src.annotation.store import AnnotationStore

load_dotenv()

REPO_ROOT = Path(__file__).parents[2]

app = FastAPI(title="RAG Annotation Tool")

retrievers = load_retrievers(REPO_ROOT / "retrievers.json")
store = AnnotationStore(REPO_ROOT / "annotations.json")


@app.post("/api/search")
async def search(request: SearchRequest) -> SearchResponse:
    per_retriever = {}
    errors = {}
    for name, retriever in retrievers.items():
        try:
            result = retriever.search(request.query, top_k=request.top_k)
            if inspect.isawaitable(result):
                result = await result
            per_retriever[name] = result
        # One broken retriever must not kill the pooled search, whatever it raises.
        except Exception as exc:  # noqa: BLE001
            errors[name] = str(exc)
    existing = store.get_for_query(request.query)
    chunks = pool_results(per_retriever, existing)
    return SearchResponse(query=request.query, chunks=chunks, retriever_errors=errors)


@app.post("/api/annotations")
def annotate(request: AnnotateRequest) -> dict[str, bool]:
    store.upsert(request)
    return {"ok": True}


@app.get("/api/retrievers")
def list_retrievers() -> dict[str, list[str]]:
    return {"retrievers": list(retrievers)}


app.mount("/", StaticFiles(directory=REPO_ROOT / "static", html=True))
