#!/bin/bash

# Review torture test for English

python ../review-chunk.py \
  --chunk-dir ../../stress-tests/torture/english/ \
  --transcriptions-dir test-torture-ocr/english/transcriptions/
