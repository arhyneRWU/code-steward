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

.PHONY: types
types: guard-venv ## Run mypy over src and benchmarks
	@$(PY) -m mypy

.PHONY: fmt
fmt: guard-venv ## Apply ruff formatting and import sorting
	@$(RUFF) check --fix .
	@$(RUFF) format .

.PHONY: fmt-check
fmt-check: guard-venv ## Verify formatting without writing
	@$(RUFF) format --check .

.PHONY: docs-check
docs-check: guard-venv ## Check docstring coverage and documented commands
	@$(PY) scripts/docs_check.py

.PHONY: docs-check-update
docs-check-update: guard-venv ## Raise the committed docstring coverage ratchet
	@$(PY) scripts/docs_check.py --update-baseline

.PHONY: check
check: lint fmt-check docs-check test ## Everything CI enforces

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

.PHONY: bench-grep
bench-grep: guard-venv ## Run the text-search control arm (ROOT=, DB=, OUT= required)
	@$(PY) -m benchmarks.real_repo.grep_baseline \
	  --project-root $(ROOT) --database $(DB) \
	  --cases benchmarks/real_repo/requests_retrieval.json --output-dir $(OUT)

.PHONY: bench-labels
bench-labels: guard-venv ## Emit blind labeling sheets (ROOT=, DB=, OUT= required)
	@$(PY) -m benchmarks.real_repo.label_sheet \
	  --project-root $(ROOT) --database $(DB) \
	  --cases benchmarks/real_repo/requests_retrieval.json \
	  --arm code-steward=$(OUT)/retrieval-baseline.json \
	  --arm text-search=$(OUT)/grep-baseline.json \
	  --output $(OUT)/label-sheet.json

.PHONY: bench-precision
bench-precision: guard-venv ## Score packet precision and noise (OUT= required)
	@$(PY) -m benchmarks.real_repo.precision \
	  --labels benchmarks/real_repo/requests_candidate_labels.json \
	  --arm code-steward=$(OUT)/retrieval-baseline.json \
	  --arm text-search=$(OUT)/grep-baseline.json \
	  --output-dir $(OUT)

.PHONY: bench-similarity-corpora
bench-similarity-corpora: ## Fetch the pinned similarity corpora (CHECKOUTS= required)
	@test -n "$(CHECKOUTS)" || { echo 'usage: make bench-similarity-corpora CHECKOUTS=<dir>'; exit 2; }
	@scripts/fetch_similarity_corpora.sh "$(CHECKOUTS)"

.PHONY: bench-similarity-pairs
bench-similarity-pairs: guard-venv ## Build the blind similarity sheet (CHECKOUTS=, WORK= required)
	@$(PY) -m benchmarks.similarity.make_pairs \
	  --checkouts $(CHECKOUTS) --work $(WORK) \
	  --sheet $(WORK)/sheet.json --key $(WORK)/key.json

.PHONY: bench-similarity
bench-similarity: guard-venv ## Score every reuse-similarity arm (CHECKOUTS=, WORK= required)
	@$(PY) -m benchmarks.similarity.score \
	  --checkouts $(CHECKOUTS) --work $(WORK) \
	  --labels benchmarks/similarity/reuse_pair_labels.json \
	  --output $(WORK)/similarity-scores.json

.PHONY: bench-tokens
bench-tokens: guard-venv ## Recalibrate byte figures against tiktoken (CHECKOUTS= required)
	@$(PY) -m benchmarks.tokens \
	  --checkouts $(CHECKOUTS) --output benchmarks/token_calibration.json

.PHONY: bench-similarity-depth
bench-similarity-depth: guard-venv ## Measure the gold set's usable depth (CHECKOUTS= required)
	@$(PY) -m benchmarks.similarity.depth \
	  --checkouts $(CHECKOUTS) --output benchmarks/similarity/depth.json

.PHONY: bench-verdict
bench-verdict: guard-venv ## Measure whether reuse evidence reaches the reviewer (CHECKOUTS=)
	@$(PY) -m benchmarks.verdict.run \
	  --checkouts $(CHECKOUTS) --output benchmarks/verdict/evidence.json

.PHONY: bench-reviewer-prompts
bench-reviewer-prompts: guard-venv ## Build blinded reviewer prompts (CHECKOUTS=, OUT= required)
	@test -n "$(OUT)" || { echo 'usage: make bench-reviewer-prompts CHECKOUTS=<dir> OUT=<file>'; exit 2; }
	@$(PY) -m benchmarks.verdict.agent_prompts \
	  --checkouts $(CHECKOUTS) --output $(OUT)

.PHONY: bench-reviewer-score
bench-reviewer-score: guard-venv ## Score reviewer verdicts (PROMPTS=, ANSWERS= required)
	@test -n "$(PROMPTS)" && test -n "$(ANSWERS)" || \
	  { echo 'usage: make bench-reviewer-score PROMPTS=<file> ANSWERS=<dir>'; exit 2; }
	@$(PY) -m benchmarks.verdict.agent_score \
	  --prompts $(PROMPTS) --answers $(ANSWERS) \
	  --output benchmarks/verdict/reviewer.json

.PHONY: bench-floor
bench-floor: guard-venv ## Choose the relevance floor on held-out data (CHECKOUTS= required)
	@$(PY) -m benchmarks.similarity.floor \
	  --checkouts $(CHECKOUTS) --output benchmarks/similarity/floor.json

.PHONY: bench-draft-prompts
bench-draft-prompts: guard-venv ## Build drafting prompts (CHECKOUTS=, OUT= required)
	@test -n "$(OUT)" || { echo 'usage: make bench-draft-prompts CHECKOUTS=<dir> OUT=<file>'; exit 2; }
	@$(PY) -m benchmarks.verdict.draft_prompts \
	  --checkouts $(CHECKOUTS) --output $(OUT)

.PHONY: bench-draft-score
bench-draft-score: guard-venv ## Score realistic drafts (CHECKOUTS=, PROMPTS=, DRAFTS= required)
	@test -n "$(PROMPTS)" && test -n "$(DRAFTS)" || \
	  { echo 'usage: make bench-draft-score CHECKOUTS=<dir> PROMPTS=<file> DRAFTS=<dir>'; exit 2; }
	@$(PY) -m benchmarks.verdict.draft_score \
	  --checkouts $(CHECKOUTS) --prompts $(PROMPTS) --drafts $(DRAFTS) \
	  --output benchmarks/verdict/realistic_draft.json

.PHONY: bench-alarm
bench-alarm: guard-venv ## Measure how often check fires on ordinary code (CHECKOUTS= required)
	@$(PY) -m benchmarks.similarity.alarm \
	  --checkouts $(CHECKOUTS) --output benchmarks/similarity/alarm.json

.PHONY: bench-check-history
bench-check-history: guard-venv ## Replay commits through check (REPO=, OUT= required)
	@test -n "$(REPO)" && test -n "$(OUT)" || \
	  { echo 'usage: make bench-check-history REPO=<clone> OUT=<file>'; exit 2; }
	@echo 'NOTE: this checks out commits in REPO. Use a throwaway clone.'
	@$(PY) -m benchmarks.check_history \
	  --repo $(REPO) --commits $(or $(COMMITS),40) \
	  --label $(or $(LABEL),replay) --output $(OUT)

.PHONY: bench-trace
bench-trace: guard-venv ## Measure trace bundle compression (ROOT=, LABEL= required)
	@test -n "$(ROOT)" && test -n "$(LABEL)" || \
	  { echo 'usage: make bench-trace ROOT=<indexed repo> LABEL=<name> [PREFIX=]'; exit 2; }
	@$(PY) -m benchmarks.trace_bundle \
	  --root $(ROOT) --label $(LABEL) --prefix "$(PREFIX)" \
	  --output benchmarks/trace_bundle_$(LABEL).json

.PHONY: bench-bundle-prompts
bench-bundle-prompts: guard-venv ## Build small-model DRY bundles (CHECKOUTS=, OUT= required)
	@test -n "$(OUT)" || { echo 'usage: make bench-bundle-prompts CHECKOUTS=<dir> OUT=<file>'; exit 2; }
	@$(PY) -m benchmarks.verdict.bundle_prompts \
	  --checkouts $(CHECKOUTS) --output $(OUT)

.PHONY: bench-bundle-score
bench-bundle-score: guard-venv ## Score small-model DRY judgement (PROMPTS=, ANSWERS=, MODEL=)
	@test -n "$(PROMPTS)" && test -n "$(ANSWERS)" || \
	  { echo 'usage: make bench-bundle-score PROMPTS=<file> ANSWERS=<dir> MODEL=<name>'; exit 2; }
	@$(PY) -m benchmarks.verdict.bundle_score \
	  --prompts $(PROMPTS) --answers $(ANSWERS) --model $(or $(MODEL),unknown) \
	  --output benchmarks/verdict/small_model_dry.json
