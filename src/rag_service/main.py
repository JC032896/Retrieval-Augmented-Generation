from fastapi import FastAPI

from rag_service import __version__
from rag_service.api.ask import router as ask_router

app = FastAPI(title="rag-service", version=__version__)
app.include_router(ask_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
