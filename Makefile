# first Python >= 3.10 on PATH (macOS /usr/bin/python3 is 3.9 — too old)
PY      ?= $(shell for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do \
             command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null \
             && { echo $$p; break; }; done)
VENV    := .venv
BIN     := $(VENV)/bin

.PHONY: help setup build run demo serve mock probe dev test smoke manual clean

help: ## show targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

setup: ## create .venv, install backend (editable) and web deps
	@test -n "$(PY)" || { echo "Need Python >= 3.10 (macOS: brew install python@3.13)"; exit 1; }
	@node -e 'process.exit(+process.versions.node.split(".")[0] < 20)' 2>/dev/null || { echo "Need Node >= 20 (brew install node)"; exit 1; }
	@echo "using $$($(PY) --version) and node $$(node --version)"
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e "backend[dev]"
	cd web && npm ci

build: ## build the GUI into web/out
	cd web && npm run build

run: build ## build + serve API and GUI on http://127.0.0.1:8765
	$(BIN)/ezra-udp serve --open

demo: build ## build + serve GUI with a built-in mock robot (one terminal, no robot needed)
	$(BIN)/ezra-udp serve --mock-faults --open

serve: ## serve without rebuilding
	$(BIN)/ezra-udp serve

mock: ## fake robot on 127.0.0.1 (udp 30000, dtls 30004, tcp 30001, tls 30003)
	$(BIN)/ezra-udp mock --faults

probe: ## which mode/port does the robot answer on? (HOST=10.21.33.103)
	$(BIN)/ezra-udp probe --host $(or $(HOST),10.21.33.103)

dev: ## backend :8765 + Next.js dev server :3000 (hot reload)
	@trap 'kill 0' EXIT; $(BIN)/ezra-udp serve --no-web & (cd web && npm run dev)

test: ## backend tests + TypeScript check
	cd backend && ../$(BIN)/pytest -q
	cd web && npm run typecheck

smoke: build ## end-to-end check: GUI + API + mock robot over all four transports (no robot needed)
	$(BIN)/python scripts/smoke.py --gui

manual: ## rebuild the PDF manual in docs/manual (needs xelatex + Carlito font)
	cd docs/manual && latexmk -xelatex -interaction=nonstopmode -halt-on-error ezra-udp-debugger-manual.tex

clean: ## remove build output
	rm -rf web/.next web/out backend/*.egg-info
