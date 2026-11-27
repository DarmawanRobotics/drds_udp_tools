PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

.PHONY: help setup build run serve mock dev test clean

help: ## show targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

setup: ## create .venv, install backend (editable) and web deps
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e "backend[dev]"
	cd web && npm ci

build: ## build the GUI into web/out
	cd web && npm run build

run: build ## build + serve API and GUI on http://127.0.0.1:8765
	$(BIN)/ezra-udp serve --open

serve: ## serve without rebuilding
	$(BIN)/ezra-udp serve

mock: ## fake robot on 127.0.0.1 (udp 30000, dtls 30004, tcp 30001, tls 30003)
	$(BIN)/ezra-udp mock --faults

dev: ## backend :8765 + Next.js dev server :3000 (hot reload)
	@trap 'kill 0' EXIT; $(BIN)/ezra-udp serve --no-web & (cd web && npm run dev)

test: ## backend tests + TypeScript check
	cd backend && ../$(BIN)/pytest -q
	cd web && npm run typecheck

clean: ## remove build output
	rm -rf web/.next web/out backend/*.egg-info
