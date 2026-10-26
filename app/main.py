import logging

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = FastAPI(title=settings.app_name, version="1.0.0")
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
