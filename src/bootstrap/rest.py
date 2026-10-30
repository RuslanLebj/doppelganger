from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from admin.setup import setup_admin
from api.base.exception_handlers.setup import setup_exception_handlers
from api.entrypoints.rest.router import main_router
from app.infrastructure.db.models import DatabaseTarget
from config import Settings
from db.postgresql.engine import make_engine, make_session_factory
from utils.cryptography.fernet import SecretCipher


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        if settings.CRYPT_KEY is None or settings.API_KEY is None:
            raise ValueError("CRYPT_KEY and API_KEY are required")
        app.state.cipher = SecretCipher(settings.CRYPT_KEY.get_secret_value())
        app.state.api_token = settings.API_KEY.get_secret_value().encode()
        engine = make_engine(settings)
        app.state.session_factory = make_session_factory(engine)
        try:
            with app.state.session_factory() as session:
                for encrypted in session.scalars(
                    select(DatabaseTarget.password_encrypted)
                ):
                    app.state.cipher.decrypt(encrypted)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)

    setup_admin(app, settings)
    setup_exception_handlers(app)
    app.include_router(main_router)
    return app


app = create_app()
