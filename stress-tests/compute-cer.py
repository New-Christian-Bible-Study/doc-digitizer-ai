#!/usr/bin/env python3
'''Character error rate (CER) from an AsciiDoc transcription vs plain ground truth.

Converts the transcription with AsciiDoc3 (HTML5) and html2text, then applies
the same normalization to both strings before Levenshtein distance / CER.
'''

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import html2text
import Levenshtein


def preprocess_adoc_for_asciidoc3(raw: str) -> str:
    '''Drop Asciidoctor-only role lines; protect ~#hex tokens from subscript rules.'''
    lines = []
    for line in raw.splitlines():
        if re.match(r'^\[\.[^]]+\]\s*$', line):
            continue
        lines.append(line)
    text = '\n'.join(lines) + '\n'

    def passthrough_tilde_hex(match: re.Match[str]) -> str:
        return '+++' + match.group(0) + '+++'

    return re.sub(r'~#[0-9A-Fa-f]+', passthrough_tilde_hex, text)


def normalize_for_cer(text: str, strip_html_emphasis: bool) -> str:
    '''Normalize plain text so AsciiDoc/HTML extraction aligns with hand-written GT.'''
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines_out = []
    for line in text.splitlines():
        if re.match(r'^\s*Last updated\b', line):
            continue
        if re.match(r'^\s*(\*\s*){3,}\s*$', line) or re.match(r'^\s*-{3,}\s*$', line):
            continue
        line = line.rstrip()
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            line = heading.group(2).replace('\\.', '.')
        if not strip_html_emphasis:
            line = re.sub(r'_([A-Za-z0-9])_', r"'\1'", line)
        lines_out.append(line)
    text = '\n'.join(lines_out)
    trans = {
        '\u2019': "'",
        '\u2018': "'",
        '\u201c': '"',
        '\u201d': '"',
        '\u2013': '-',
        '\u2014': '-',
    }
    for key, val in trans.items():
        text = text.replace(key, val)
    return re.sub(r'\s+', ' ', text).strip()


def adoc_to_plain_via_html5(
    adoc_path: Path,
    *,
    strip_html_emphasis: bool,
) -> str:
    adoc_path = adoc_path.resolve()
    if not adoc_path.is_file():
        raise FileNotFoundError(f'transcription not found: {adoc_path}')

    raw = adoc_path.read_text(encoding='utf-8')
    preprocessed = preprocess_adoc_for_asciidoc3(raw)

    tmp_adoc_path: str | None = None
    tmp_html: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            suffix='.adoc',
            dir=str(adoc_path.parent),
            delete=False,
        ) as tmp_adoc:
            tmp_adoc.write(preprocessed)
            tmp_adoc_path = tmp_adoc.name

        fd, tmp_html = tempfile.mkstemp(suffix='.html', text=True)
        os.close(fd)

        cmd = [
            sys.executable,
            '-m',
            'asciidoc3.asciidoc3',
            '-b',
            'html5',
            '-o',
            tmp_html,
            tmp_adoc_path,
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(adoc_path.parent),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            msg = proc.stderr or proc.stdout or '(no output)'
            raise RuntimeError(
                f'asciidoc3 failed (exit {proc.returncode}):\n{msg}',
            )

        html = Path(tmp_html).read_text(encoding='utf-8', errors='replace')
    finally:
        if tmp_adoc_path:
            try:
                os.unlink(tmp_adoc_path)
            except OSError:
                pass
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except OSError:
                pass

    converter = html2text.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.ignore_emphasis = strip_html_emphasis
    return converter.handle(html)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Compute character error rate (CER) of an AsciiDoc transcription '
            'against a plain-text ground truth file.'
        ),
    )
    parser.add_argument(
        'transcription_adoc',
        type=Path,
        help='Path to the transcription .adoc file',
    )
    parser.add_argument(
        'ground_truth',
        type=Path,
        help='Path to the ground truth plain-text file',
    )
    emphasis = parser.add_mutually_exclusive_group()
    emphasis.add_argument(
        '--strip-html-emphasis',
        action='store_true',
        help=(
            'Pass ignore_emphasis=True to html2text (strip bold/italic markup). '
            'This is the default unless --keep-emphasis-markers is set.'
        ),
    )
    emphasis.add_argument(
        '--keep-emphasis-markers',
        action='store_true',
        help=(
            'Pass ignore_emphasis=False to html2text (keep *_ markers). '
            'Useful when normalizing single-character italics to quotes for '
            'plain-text ground truth.'
        ),
    )
    args = parser.parse_args()
    strip_html_emphasis = not args.keep_emphasis_markers
    if args.strip_html_emphasis:
        strip_html_emphasis = True
    gt_path = args.ground_truth
    if not gt_path.is_file():
        print(f'Error: ground truth not found: {gt_path}', file=sys.stderr)
        return 1

    try:
        hypothesis_raw = adoc_to_plain_via_html5(
            args.transcription_adoc,
            strip_html_emphasis=strip_html_emphasis,
        )
    except FileNotFoundError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    truth_raw = gt_path.read_text(encoding='utf-8')
    truth = normalize_for_cer(truth_raw, strip_html_emphasis)
    hypothesis = normalize_for_cer(hypothesis_raw, strip_html_emphasis)

    distance = Levenshtein.distance(truth, hypothesis)
    cer = distance / len(truth) if len(truth) else 0.0

    print(f'Edit distance: {distance}')
    print(f'Character error rate: {cer:.4%}')
    print(f'Ground truth length (normalized): {len(truth)}')
    print(f'Hypothesis length (normalized): {len(hypothesis)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
