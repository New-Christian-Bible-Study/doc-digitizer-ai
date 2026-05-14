"""Tests for legacy transcription JSON conversion to schema_version 2."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

STRATEGY_ROOT = Path(__file__).resolve().parents[1]
CONVERT_SCRIPT = STRATEGY_ROOT / 'convert-transcription-boxes.py'
RAW_SCHEMA_PATH = STRATEGY_ROOT / 'raw-transcription.schema.json'


def test_convert_cli_migrates_legacy_to_v2(tmp_path: Path):
    legacy = {
        'lines': [
            {
                'page_number': 1,
                'text': 'hello',
                'box_2d': [10, 20, 30, 40],
                'ai_confidence_label': 'high',
                'ai_notes': '',
            }
        ],
        'confidence_score': 1.0,
        'confidence_label': 'high',
    }
    src = tmp_path / 'chunk_raw.json'
    src.write_text(json.dumps(legacy), encoding='utf-8')
    out = tmp_path / 'chunk_raw_v2.json'
    proc = subprocess.run(
        [
            sys.executable,
            str(CONVERT_SCRIPT),
            str(src),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['schema_version'] == 2
    lb = data['lines'][0]['line_box']
    assert lb == {'ymin': 10, 'xmin': 20, 'ymax': 30, 'xmax': 40}
    assert 'box_2d' not in data['lines'][0]
    schema = json.loads(RAW_SCHEMA_PATH.read_text(encoding='utf-8'))
    jsonschema.validate(instance=data, schema=schema)
