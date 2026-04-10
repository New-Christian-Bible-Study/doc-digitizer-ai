#!/bin/bash
set -euo pipefail

# Generate the PDF and ground truth for the OCR stress test

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

python3 gen-noise-stress-images.py

asciidoctor-pdf -a pdf-theme=ocr-torture-theme.yml test-ocr.adoc -o test-ocr.pdf

# Generate a temporary HTML file
asciidoctor test-ocr.adoc -o temp.html

# Use pandoc to create the clean ground truth
pandoc temp.html -t plain -o ground-truth.txt

# Clean up the temporary HTML file
rm temp.html
