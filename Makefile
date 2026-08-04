SHELL := /bin/bash

COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)

ALL_SERVICES := auth-service tenant-service users-service files-service
SKIP_SERVICES ?= $(shell grep -E '^SKIP_SERVICES=' .env 2>/dev/null | cut -d= -f2 | tr ',' ' ')
PROFILES := $(subst $(SPACE),$(COMMA),$(strip $(filter-out $(SKIP_SERVICES),$(ALL_SERVICES))))

.PHONY: up down prune

up:      ## Levanta el stack (todos los servicios menos SKIP_SERVICES)
	COMPOSE_PROFILES=$(PROFILES) docker compose up --build -d
	COMPOSE_PROFILES=$(PROFILES) docker compose ps

down:    ## Apaga todos los contenedores
	docker compose down

prune:   ## Borra contenedores y sus volúmenes (nada más)
	docker compose down -v --remove-orphans
