# Code Steward developer tasks.
#
# Every target works from the main clone and from any linked worktree.
# The virtualenv always resolves to the main clone, so a new worktree is
# usable immediately without reinstalling dependencies.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# --- paths ------------------------------------------------------------

# In a worktree, --git-common-dir points at the main clone's .git, so this
# resolves to the main checkout from anywhere in the repo.
GIT_COMMON := $(shell git rev-parse --git-common-dir 2>/dev/null)
MAIN_ROOT  := $(realpath $(dir $(GIT_COMMON)))
VENV       ?= $(MAIN_ROOT)/.venv
PY         := $(VENV)/bin/python
RUFF       := $(VENV)/bin/ruff
CS         := $(VENV)/bin/code-steward

# Worktrees live OUTSIDE the repository on purpose. indexer.iter_python_files
# does not exclude in-repo worktree directories, so a worktree placed inside
# the checkout is indexed as live source and collides on duplicate unit IDs.
WT_ROOT ?= $(realpath $(dir $(MAIN_ROOT)))/code-steward-worktrees

# Fixture trees declare intentionally duplicated unit IDs and must not be
# indexed as production source. Remove once persistent excludes are supported.
IDX_EXCLUDES ?= --exclude tests/fixtures --exclude benchmarks/retrieval/fixture_repo

FROM ?= main
SLUG  = $(subst /,-,$(NAME))
WT    = $(WT_ROOT)/$(SLUG)

# --- meta -------------------------------------------------------------

.PHONY: help
help: ## Show this help
	@echo "Code Steward — make targets"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| sort \
		| awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Worktrees:  make wt NAME=fix/thing [FROM=main]"
	@echo "Root:       $(MAIN_ROOT)"
	@echo "Worktrees:  $(WT_ROOT)"

.PHONY: venv
venv: ## Create the virtualenv and install dev dependencies
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"
	@$(VENV)/bin/pip install -q --upgrade pip
	@$(VENV)/bin/pip install -q -e "$(MAIN_ROOT)[dev]"
	@echo "venv ready: $(VENV)"

.PHONY: guard-venv
guard-venv:
	@test -x "$(PY)" || { \
		echo "No virtualenv at $(VENV). Run: make venv"; exit 2; }

# --- quality ----------------------------------------------------------

.PHONY: test
test: guard-venv ## Run the test suite
	@$(PY) -m pytest -q

.PHONY: lint
lint: guard-venv ## Run ruff lint checks
	@$(RUFF) check .

.PHONY: fmt
fmt: guard-venv ## Apply ruff formatting and import sorting
	@$(RUFF) check --fix .
	@$(RUFF) format .

.PHONY: fmt-check
fmt-check: guard-venv ## Verify formatting without writing
	@$(RUFF) format --check .

.PHONY: check
check: lint fmt-check test ## Everything CI enforces

# --- code steward itself ----------------------------------------------

.PHONY: index
index: guard-venv ## Build the Code Steward index for this checkout
	@$(CS) build $(IDX_EXCLUDES)

.PHONY: packet
packet: guard-venv ## Emit a reviewer packet (Q="task intent")
	@test -n "$(Q)" || { echo 'usage: make packet Q="task intent"'; exit 2; }
	@$(CS) packet "$(Q)"

.PHONY: bench
bench: guard-venv ## Run the frozen retrieval benchmark
	@$(PY) -m benchmarks.retrieval.run

.PHONY: bench-matrix
bench-matrix: guard-venv ## Run the retrieval validity matrix (PIPELINE=retrieve|search)
	@$(PY) -m benchmarks.retrieval.matrix --pipeline $(or $(PIPELINE),retrieve)

# --- worktrees --------------------------------------------------------

.PHONY: guard-name
guard-name:
	@test -n "$(NAME)" || { \
		echo 'NAME is required, e.g. make wt NAME=fix/thing'; exit 2; }

.PHONY: wt
wt: guard-name ## Create a worktree and branch (NAME=fix/thing [FROM=main])
	@mkdir -p "$(WT_ROOT)"
	@git -C "$(MAIN_ROOT)" worktree add -b "$(NAME)" "$(WT)" "$(FROM)"
	@echo
	@echo "branch:   $(NAME)  (from $(FROM))"
	@echo "worktree: $(WT)"
	@echo "run:      make -C $(WT) check"

.PHONY: wt-ls
wt-ls: ## List worktrees
	@git -C "$(MAIN_ROOT)" worktree list

.PHONY: wt-rm
wt-rm: guard-name ## Remove a worktree, keeping its branch (NAME=fix/thing)
	@git -C "$(MAIN_ROOT)" worktree remove "$(WT)"
	@echo "removed worktree $(WT); branch $(NAME) kept"

.PHONY: wt-prune
wt-prune: ## Forget worktrees whose directories are already gone
	@git -C "$(MAIN_ROOT)" worktree prune -v

.PHONY: wt-check
wt-check: guard-name ## Run the full check suite inside a worktree
	@$(MAKE) -C "$(WT)" check

# --- git --------------------------------------------------------------

.PHONY: sync
sync: ## Fetch and rebase the current branch onto origin/main
	@git fetch --prune origin
	@git rebase origin/main

.PHONY: clean
clean: ## Remove build, cache, and index artifacts
	@rm -rf "$(MAIN_ROOT)"/.pytest_cache "$(MAIN_ROOT)"/.ruff_cache \
		"$(MAIN_ROOT)"/.code-steward "$(MAIN_ROOT)"/dist "$(MAIN_ROOT)"/build
	@find "$(MAIN_ROOT)" -name __pycache__ -type d -prune -not -path '*/.venv/*' -exec rm -rf {} +
	@echo "cleaned"
