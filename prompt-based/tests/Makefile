TESTS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(abspath $(TESTS_DIR)/../..)
PYTHON ?= python3

.PHONY: help realclean raw review check-boxes

help:
	@echo "Targets (run from repo root: make -C prompt-based/tests <target>):"
	@echo "  realclean    Remove *_raw.json and downstream artifacts under tests/"
	@echo "  raw          Regenerate raw JSON (needs GEMINI_API_KEY; standard + torture)"
	@echo "  review       Open review-chunk.py per fixture workdir (sequential, GUI)"
	@echo "  check-boxes  Headless box-alignment check on archaic test fixtures"
	@echo ""
	@echo "Optional: TORTURE_OCR_LANG=english limits torture raw/review to one language."

realclean:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py realclean

raw:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py raw

review:
	$(PYTHON) $(TESTS_DIR)raw-artifact-tasks.py review

check-boxes:
	$(PYTHON) $(TESTS_DIR)check_box_ink.py \
	  $(TESTS_DIR)archaic/ac-marchant/transcriptions/ac-marchant-genesis-16_011-013_raw.json \
	  $(TESTS_DIR)archaic/ac-marchant/chunk-pdfs/ac-marchant-genesis-16_011-013.pdf
	$(PYTHON) $(TESTS_DIR)check_box_ink.py \
	  $(TESTS_DIR)archaic/ac-marchant/transcriptions/ac-marchant-genesis-16_014-023_raw.json \
	  $(TESTS_DIR)archaic/ac-marchant/chunk-pdfs/ac-marchant-genesis-16_014-023.pdf
