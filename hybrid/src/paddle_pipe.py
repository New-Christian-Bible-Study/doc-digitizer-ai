import json
import argparse
from pathlib import Path

import numpy as np
from paddleocr import PaddleOCR

# Cache variables
_ocr_engine = None
_current_lang = None

def get_ocr_engine(lang: str) -> PaddleOCR:
    global _ocr_engine, _current_lang
    # Re-initialize only if engine is uninitialized or the selected language changed
    if _ocr_engine is None or _current_lang != lang:
        _ocr_engine = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang=lang,
            ocr_version="PP-OCRv5",
            device="cpu"
        )
        _current_lang = lang
    return _ocr_engine

def run_paddle_page(image_path: Path, output_json: Path, lang: str = "en") -> Path:
    engine = get_ocr_engine(lang)
    results = engine.predict(str(image_path))

    for res in results: 
        res.save_to_json(str(output_json))
        res.save_to_img(str(output_json) + "_img.png")

    return output_json