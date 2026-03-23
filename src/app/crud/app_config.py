from sqlmodel import Session

from ..models.entities import AppConfig, utc_now


def get_app_config_singleton(session: Session) -> AppConfig | None:
    return session.get(AppConfig, 1)


def ensure_app_config_singleton(session: Session, default_model: str) -> AppConfig:
    app_config = get_app_config_singleton(session)
    if not app_config:
        app_config = AppConfig(id=1, active_model=default_model)
        session.add(app_config)
        session.commit()
        session.refresh(app_config)
    return app_config


def set_active_model_singleton(session: Session, model_name: str) -> AppConfig:
    app_config = ensure_app_config_singleton(session, model_name)
    app_config.active_model = model_name
    app_config.updated_at = utc_now()
    session.add(app_config)
    session.commit()
    session.refresh(app_config)
    return app_config
