DOCKER ?= $(shell command -v docker 2>/dev/null || echo /Applications/Docker.app/Contents/Resources/bin/docker)
export PATH := /Applications/Docker.app/Contents/Resources/bin:$(PATH)
COMPOSE := $(DOCKER) compose -f docker-compose.yml

.PHONY: docker-build docker-up docker-down docker-logs docker-ps docker-migrate docker-test docker-clean

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up --build

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=200

docker-ps:
	$(COMPOSE) ps

docker-migrate:
	$(COMPOSE) run --rm api alembic upgrade head

docker-test:
	$(COMPOSE) run --rm api pytest -q

docker-clean:
	$(COMPOSE) down -v --remove-orphans
