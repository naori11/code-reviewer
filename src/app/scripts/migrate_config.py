import json
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session

from ..core.database import engine, init_db
from ..models.entities import AppConfig, utc_now


def migrate_config_json_to_db() -> None:
    init_db()
    config_path = Path("config.json")

    if not config_path.exists():
        return

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    active_model = data.get("active_model")
    if not active_model:
        return

    with Session(engine) as session:
        app_config = session.get(AppConfig, 1)
        if app_config:
            app_config.active_model = active_model
            app_config.updated_at = utc_now()
        else:
            app_config = AppConfig(
                id=1,
                active_model=active_model,
                ai_review_prompt="",
                prompt_version=1,
            )
            session.add(app_config)

        session.commit()


def migrate_prompt_observability_columns(default_prompt: str) -> None:
    init_db()
    inspector = inspect(engine)

    with engine.begin() as conn:
        appconfig_columns = {column["name"] for column in inspector.get_columns("appconfig")}
        reviewhistory_columns = {column["name"] for column in inspector.get_columns("reviewhistory")}

        if "ai_review_prompt" not in appconfig_columns:
            conn.execute(text("ALTER TABLE appconfig ADD COLUMN ai_review_prompt TEXT"))
        if "prompt_version" not in appconfig_columns:
            conn.execute(text("ALTER TABLE appconfig ADD COLUMN prompt_version INTEGER"))
        if "prompt_version" not in reviewhistory_columns:
            conn.execute(text("ALTER TABLE reviewhistory ADD COLUMN prompt_version INTEGER"))
        if "prompt_hash" not in reviewhistory_columns:
            conn.execute(text("ALTER TABLE reviewhistory ADD COLUMN prompt_hash TEXT"))

        conn.execute(
            text(
                "UPDATE appconfig "
                "SET ai_review_prompt = :default_prompt "
                "WHERE ai_review_prompt IS NULL OR ai_review_prompt = ''"
            ),
            {"default_prompt": default_prompt},
        )
        conn.execute(
            text("UPDATE appconfig SET prompt_version = 1 WHERE prompt_version IS NULL OR prompt_version < 1")
        )


if __name__ == "__main__":
    migrate_config_json_to_db()
