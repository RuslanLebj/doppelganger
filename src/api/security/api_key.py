import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader


def check_api_key(
    request: Request,
    api_key: Annotated[
        str | None, Security(APIKeyHeader(name="X-API-Key", auto_error=False))
    ],
) -> None:
    if not api_key:
        raise HTTPException(401, "API key is required")
    if not secrets.compare_digest(api_key.encode(), request.app.state.api_token):
        raise HTTPException(403, "Invalid API key")
