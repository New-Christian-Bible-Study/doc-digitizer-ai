#!/bin/bash
set -euo pipefail

# Generate PDF and ground truth for one torture language fixture.
# Usage: ./gen-pdf-and-ground-truth.sh english
#        ./gen-pdf-and-ground-truth.sh italian

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
