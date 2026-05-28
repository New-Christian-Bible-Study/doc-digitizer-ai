import json
import argparse
from pathlib import Path

import numpy as np
from paddleocr import PaddleOCR


ocr_engine = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang="fr",
    ocr_version="PP-OCRv5",
    device="cpu"
)


def run_paddle_page(image_path: Path, output_json: Path) -> Path:
    results = ocr_engine.predict(str(image_path))

    for res in results: 
        res.save_to_json(str(output_json))
        res.save_to_img(str(output_json) + "_img.png")

    return output_json