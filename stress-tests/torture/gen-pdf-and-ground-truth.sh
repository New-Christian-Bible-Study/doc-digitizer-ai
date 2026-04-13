#!/bin/bash
set -euo pipefail

# Generate PDF and ground truth for one torture language fixture.
# Usage: ./gen-pdf-and-ground-truth.sh english
#        ./gen-pdf-and-ground-truth.sh italian
#
# Toolchain: Asciidoctor (PDF + HTML) uses the full fixture; pandoc turns HTML
# into plain ground-truth.txt. That file is what integration CER compares
# against (after normalize_for_cer)—not the output of compute-cer.py's
# AsciiDoc3/html2text path, which is only for .adoc transcriptions.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANG_REL="${1:?usage: $0 <english|italian>}"
LANG_DIR="$HERE/$LANG_REL"

if [[ ! -d "$LANG_DIR" ]]; then
  echo "not a directory: $LANG_DIR" >&2
  exit 1
fi

cd "$LANG_DIR"

python3 "$HERE/gen-noise-stress-images.py" --lang-dir "$LANG_DIR"

asciidoctor-pdf -a pdf-theme="$HERE/ocr-torture-theme.yml" test-ocr.adoc -o test-ocr.pdf

asciidoctor test-ocr.adoc -o temp.html

pandoc temp.html -t plain -o ground-truth.txt

rm temp.html
