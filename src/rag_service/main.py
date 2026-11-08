from fastapi import FastAPI

from rag_service import __version__

app = FastAPI(title="rag-service", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
