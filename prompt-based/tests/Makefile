TESTS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(abspath $(TESTS_DIR)/../..)
PYTHON ?= python3

.PHONY: help realclean raw review

help:
	@echo "Targets (run from repo root: make -C prompt-based/tests <target>):"
	@echo "  realclean  Remove *_raw.json and downstream artifacts under tests/"
	@echo "  raw        Regenerate raw JSON (needs GEMINI_API_KEY; standard + torture)"
	@echo "  review     Open review-chunk.py per fixture workdir (sequential, GUI)"
	@echo ""
	@echo "Optional: TORTURE_OCR_LANG=english limits torture raw/review to one language."

realclean:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py realclean

raw:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py raw

review:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py review
