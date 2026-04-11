# Stress-test PDFs

Place **source PDFs** here that are intentionally difficult for transcription (poor scans, unusual fonts, damage, etc.). They are **shared** across digitization strategies in this repository so you can compare outputs—for example with **character error rate (CER)**—on the same inputs.

## How strategies use these files

Nothing in this folder is consumed automatically. Each pipeline uses its own working-directory layout (typically `source-pdfs/`, `chunk-pdfs/`, `transcriptions/`). To run a strategy on a stress PDF:

1. Copy or symlink the PDF from `stress-tests/` into that work directory’s `source-pdfs/`, **or**
2. Point your strategy’s preparation step at an absolute path under `stress-tests/`, if your tooling supports it.

For the **prompt-based** flow, see [`prompt-based/README.md`](../prompt-based/README.md): run `generate-chunk-pdf.py` (or equivalent) with `--working-dir` set to a directory that contains `source-pdfs/` where you placed the file.

Optional: set an environment variable in your own scripts (for example `STRESS_TESTS_DIR` pointing at this directory) and resolve paths from there when batching comparisons.

## Character error rate (CER)

[`compute-cer.py`](compute-cer.py) compares a transcription **AsciiDoc** file to a **plain-text** ground truth file. It runs [AsciiDoc3](https://asciidoc3.org/) to HTML5 (via `python -m asciidoc3.asciidoc3`, so configuration files from the installed package are found), converts HTML with [html2text](https://github.com/Alir3z4/html2text/), then applies the same normalization to both sides before reporting Levenshtein edit distance and CER (distance ÷ ground-truth length).

Install dependencies from the repository root (`pip install -r requirements.txt`). The script drops Asciidoctor-only `[.role]` lines and wraps `~#` hex color tokens for AsciiDoc3 so they are not parsed as subscript markup.

Example (run from the repository root; the torture fixture matches with emphasis markers preserved):

```bash
python stress-tests/compute-cer.py \
  stress-tests/torture/test-ocr.adoc \
  stress-tests/torture/ground-truth.txt \
  --keep-emphasis-markers
```

### Why `--keep-emphasis-markers` exists

AsciiDoc treats **paired single quotes** around short text as *quotes / emphasis*, not necessarily as literal apostrophe characters that survive unchanged into HTML. For example, in [`torture/test-ocr.adoc`](torture/test-ocr.adoc) the phrase `distinguish 'e' from 'o'` uses ASCII single quotes in the source, but AsciiDoc3 still applies its **quoting and substitution rules** so those letters are emitted as **emphasized** spans in HTML (italic-style markup), not as three plain text characters `'` + `e` + `'` in the same way a hand-written ground truth file spells them.

After that, **html2text** decides how emphasis becomes characters:

- **Default (`ignore_emphasis=True`):** italic markup is removed and you get bare letters (`e`, `o`). If your ground truth keeps the **quote characters** around those letters (`'e'`, `'o'`), the normalized strings differ slightly and CER is non-zero even when the transcription is “right.”
- **With `--keep-emphasis-markers` (`ignore_emphasis=False`):** html2text represents emphasis using Markdown-style underscores (for example `_e_`). There is **no** `_e_` in your `.adoc` file; that form appears only in html2text’s output. The script then maps each **single-character** `_x_` to `'x'` during normalization so the hypothesis matches plain-text ground truth that uses ASCII quotes around individual letters.

Use **`--keep-emphasis-markers`** when your reference text uses punctuation (quotes) around letters or words that AsciiDoc has turned into emphasized HTML. If your ground truth never encodes that distinction, the default emphasis stripping may be enough.
