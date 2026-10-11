# Debezium Server plumbing proof - operator entry points.
# Every target is a thin wrapper around docker compose; see README.md.
SHELL := /bin/bash
COMPOSE := docker compose
RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: build up down start stop restart recover ps health logs tail psql seed generate verify outage-short outage-long reset

build:            ## Build the receiver image
	$(COMPOSE) build receiver

up: build         ## Build and start postgres, receiver, debezium (detached)
	mkdir -p logs runs
	$(COMPOSE) up -d --wait postgres receiver debezium

down:             ## Stop and remove containers. KEEPS volumes (data + offsets) and logs.
	$(COMPOSE) down

stop:             ## Stop containers without removing them. Keeps everything.
	$(COMPOSE) stop

start:            ## Start previously stopped containers
	$(COMPOSE) start

restart:          ## Ordinary restart of the whole stack (data and offsets preserved)
	$(COMPOSE) restart

recover:          ## Recover Debezium after HTTP retry exhaustion (engine stopped, health DOWN)
	$(COMPOSE) restart debezium

ps:
	$(COMPOSE) ps

health:           ## Receiver and Debezium health endpoints
	python3 verify/host_health.py

logs:             ## Container logs (follow)
	$(COMPOSE) logs -f --tail=100

tail:             ## Tail the delivered event envelopes on the host
	tail -f logs/events.jsonl

psql:             ## Interactive psql inside the postgres container
	$(COMPOSE) exec postgres psql -U dbz -d appdb

seed:             ## Re-apply seed data (idempotent). Normally done automatically on first start.
	$(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -U dbz -d appdb -f /docker-entrypoint-initdb.d/20-seed.sql

generate:         ## Run the deterministic change scenario. Override: make generate RUN_ID=myrun
	mkdir -p runs
	RUN_ID=$(RUN_ID) $(COMPOSE) run --rm generator

verify:           ## Full automated verification against the running stack
	python3 verify/verify.py all

outage-short:     ## Receiver outage inside the Debezium retry budget
	python3 verify/verify.py outage-short

outage-long:      ## Receiver outage beyond the retry budget, then explicit recovery
	python3 verify/verify.py outage-long

reset:            ## DESTRUCTIVE. Removes containers, volumes dbzproof_pg_data and dbzproof_debezium_data, logs/*.jsonl, logs/receiver.log and runs/*.
	@echo "This deletes: docker volumes dbzproof_pg_data, dbzproof_debezium_data; files logs/events.jsonl logs/receipts.jsonl logs/receiver.log; directory contents of runs/"
	$(COMPOSE) --profile tools down -v --remove-orphans
	rm -f logs/events.jsonl logs/receipts.jsonl logs/receiver.log
	find runs -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf {} +
