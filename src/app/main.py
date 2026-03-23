import logging
import logging.config

from fastapi import FastAPI
from sqlmodel import Session

from .api.admin import router as admin_router
from .api.webhooks import router as webhooks_router
from .core.config import get_settings
from .core.database import engine, init_db
from .models.entities import AppConfig

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


async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()

    with Session(engine) as session:
        app_config = session.get(AppConfig, 1)
        if not app_config:
            session.add(AppConfig(id=1, active_model=settings.ai_model_name))
            session.commit()

    yield


app = FastAPI(lifespan=lifespan)
app.include_router(webhooks_router)
app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=False)
