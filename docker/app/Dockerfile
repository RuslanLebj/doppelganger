ARG UV_VERSION="0.11.8"
ARG PYTHON_VERSION="3.14"

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_VERSION}-alpine

ARG PG_MAJOR=18
WORKDIR /opt/app

RUN apk add --no-cache postgresql${PG_MAJOR}-client

COPY pyproject.toml uv.lock ./

ENV VIRTUAL_ENV=/opt/.venv
ENV PATH="/opt/.venv/bin:$PATH"
ENV PYTHONPATH=/opt/app/src

RUN uv venv /opt/.venv \
 && uv sync --active --frozen --no-dev --no-cache \
 && mkdir /data && chown 1000:1000 /data

COPY src ./src

USER 1000:1000
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "bootstrap.rest:app"]
