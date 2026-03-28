from sqlmodel import Session

from ..models.entities import AppConfig, utc_now


def get_app_config_singleton(session: Session) -> AppConfig | None:
    return session.get(AppConfig, 1)


def ensure_app_config_singleton(session: Session, default_model: str, default_prompt: str) -> AppConfig:
    app_config = get_app_config_singleton(session)
    if not app_config:
        app_config = AppConfig(
            id=1,
            active_model=default_model,
            ai_review_prompt=default_prompt,
            prompt_version=1,
        )
        session.add(app_config)
        session.commit()
        session.refresh(app_config)
    return app_config


def set_active_model_singleton(session: Session, model_name: str, default_prompt: str) -> AppConfig:
    app_config = ensure_app_config_singleton(session, model_name, default_prompt)
    app_config.active_model = model_name
    app_config.updated_at = utc_now()
    session.add(app_config)
    session.commit()
    session.refresh(app_config)
    return app_config


def set_review_prompt_singleton(session: Session, prompt_text: str, default_model: str) -> AppConfig:
    app_config = ensure_app_config_singleton(session, default_model, prompt_text)
    if app_config.ai_review_prompt != prompt_text:
        app_config.ai_review_prompt = prompt_text
        app_config.prompt_version += 1
        app_config.updated_at = utc_now()
        session.add(app_config)
        session.commit()
        session.refresh(app_config)
    return app_config


def resolve_effective_review_prompt(app_config: AppConfig | None, fallback_prompt: str) -> tuple[str, int]:
    if app_config and app_config.ai_review_prompt:
        return app_config.ai_review_prompt, app_config.prompt_version
    return fallback_prompt, 0
