from contextlib import asynccontextmanager
import logging
import logging.config

import httpx
from fastapi import FastAPI
from google import genai
from sqlmodel import Session

from .api.admin import router as admin_router
from .api.webhooks import router as webhooks_router
from .core.config import get_settings
from .core.database import engine, init_db
from .crud.app_config import ensure_app_config_singleton
from .scripts.migrate_config import migrate_prompt_observability_columns

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "httpx": {
            "level": "WARNING",
            "propagate": False,
            "handlers": ["console"],
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    migrate_prompt_observability_columns(settings.ai_review_prompt)

    with Session(engine) as session:
        ensure_app_config_singleton(session, settings.ai_model_name, settings.ai_review_prompt)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        app.state.http_client = http_client
        app.state.gemini_client = genai.Client(api_key=settings.gemini_api_key)
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(webhooks_router)
app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=False)
