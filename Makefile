.PHONY: install build migrate migrate-local api worker test lint up api-up scheduler-up storage-init down

COMPOSE_FILE = docker/local-docker-compose.yaml
TESTS_COMPOSE_FILE = docker/tests-docker-compose.yaml
COMPOSE_PROJECT = doppelganger
DOCKER_COMPOSE = docker compose --env-file .env -f $(COMPOSE_FILE) -p $(COMPOSE_PROJECT)
DOCKER_COMPOSE_TEST = docker compose -f $(TESTS_COMPOSE_FILE) -p $(COMPOSE_PROJECT)-tests
PROFILE ?= full

install:
	uv sync --frozen

build:
	$(DOCKER_COMPOSE) --profile app build doppelganger

migrate:
	$(DOCKER_COMPOSE) --profile app run --rm --workdir /opt/app/src doppelganger alembic upgrade head

migrate-local:
	cd src && uv run alembic upgrade head

api:
	PYTHONPATH=src uv run granian --interface asgi --host 127.0.0.1 --port 8010 --workers 1 bootstrap.rest:app

worker:
	PYTHONPATH=src uv run python -m bootstrap.schedulers

test:
	@set -eu; \
	trap '$(DOCKER_COMPOSE_TEST) down' EXIT; \
	$(DOCKER_COMPOSE_TEST) up -d --wait; \
	uv run pytest $(PYTEST_ARGS)

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

up:
	$(DOCKER_COMPOSE) --profile $(PROFILE) up -d --build

api-up:
	$(DOCKER_COMPOSE) --profile app up -d --build doppelganger

scheduler-up:
	$(DOCKER_COMPOSE) --profile execution up -d --build doppelganger-scheduler

storage-init:
	$(DOCKER_COMPOSE) --profile dbs up -d doppelganger-minio
	$(DOCKER_COMPOSE) --profile app run --rm --no-deps doppelganger python -c "from app.infrastructure.s3.minio.adapter import initialize; from config import Settings; initialize(Settings())"

down:
	$(DOCKER_COMPOSE) --profile down/restart down --remove-orphans
