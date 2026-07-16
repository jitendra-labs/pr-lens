
from contextlib import asynccontextmanager
from fastapi import FastAPI
from datetime import datetime

from .api import webhook
from .core.logging_config import setup_logging, logger
from .db.config import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown lifecycles."""
    logger.info("Starting up PRLens Engine: Initializing database infrastructure...")
    try:
        await init_db()
    except Exception as e:
        logger.critical("Database initialization failed! Exiting server process.", exc_info=e)
        raise e
        
    yield  # 🟢 Server is running and listening for GitHub webhooks here
    
    logger.info("Shutting down PRLens Engine: Cleaning connection pools...")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="PRLens AI API",
        description="Backend API to process GitHub PR webhooks and run AI reviews.",
        version="1.0.0",
        lifespan=lifespan
    )
    app.include_router(webhook.router, prefix="/api")
    logger.info("App created and routes registered")
    return app


app = create_app()

# Root endpoint just to check if the API is alive
@app.get("/")
def read_root():
    return {"success": True, "service": "PRLens AI Engine"}

@app.get("/health")
def get_health():
    return {"success": True, "datetime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
