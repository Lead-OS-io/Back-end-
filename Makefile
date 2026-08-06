SHELL := /bin/bash

COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)

ALL_SERVICES := auth-service tenant-service users-service files-service
SKIP_SERVICES ?= $(shell grep -E '^SKIP_SERVICES=' .env 2>/dev/null | cut -d= -f2 | tr ',' ' ')
PROFILES := $(subst $(SPACE),$(COMMA),$(strip $(filter-out $(SKIP_SERVICES),$(ALL_SERVICES))))
# down/prune deben apagar TODO, incluidos servicios skippeados en el último up:
# compose solo opera sobre servicios con profiles activos.
ALL_PROFILES := $(subst $(SPACE),$(COMMA),$(ALL_SERVICES))

.PHONY: up down prune push-images

.env:
	@echo "Creando .env desde .env.example (valores de desarrollo)"
	@cp .env.example .env

up: .env  ## Levanta el stack (todos los servicios menos SKIP_SERVICES)
	COMPOSE_PROFILES=$(PROFILES) docker compose up --build 
	COMPOSE_PROFILES=$(PROFILES) docker compose ps

down:    ## Apaga todos los contenedores
	COMPOSE_PROFILES=$(ALL_PROFILES) docker compose down

prune:   ## Borra contenedores y sus volúmenes (nada más)
	COMPOSE_PROFILES=$(ALL_PROFILES) docker compose down -v --remove-orphans

push-images: ## Build & push de los 5 servicios a carlos0550/lead_os_test
	bash scripts/push-images.sh
