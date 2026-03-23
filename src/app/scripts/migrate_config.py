import json
from pathlib import Path

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
            app_config = AppConfig(id=1, active_model=active_model)
            session.add(app_config)

        session.commit()


if __name__ == "__main__":
    migrate_config_json_to_db()
