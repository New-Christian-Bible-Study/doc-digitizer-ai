import json
import argparse
import copy
from pathlib import Path

from google import genai
from google.genai import types 

import numpy as np

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_SYSTEM_PROMPT_PATH, GEMINI_USER_PROMPT_PATH

client = genai.Client(api_key=GEMINI_API_KEY)


def make_gemini_payload_file(paddle_json: Path, output_json: Path) -> Path:
    
    with paddle_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    payload_json = {
        "rec_texts": data["rec_texts"],
        "rec_polys": data["rec_polys"],
    }

    with output_json.open("w", encoding="utf-8") as f:
        json.dump(payload_json, f, indent=4, ensure_ascii=False)

    return output_json

def run_gemini_page(image_path: Path, payload_json: Path, output_json: Path) -> Path:
    image = client.files.upload(file=image_path)
    system_prompt = GEMINI_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = GEMINI_USER_PROMPT_PATH.read_text(encoding="utf-8")

    payload_text = payload_json.read_text(encoding="utf-8")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            "Extra user information: " + user_prompt,
            image,
            payload_text,
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
        ),
    )

    output_json.write_text(response.text, encoding="utf-8")
    return output_json


def merge_gemini_into_paddle_file(paddle_json: Path, gemini_json: Path, output_json: Path) -> Path:
    paddlej = json.loads(paddle_json.read_text(encoding="utf-8"))
    geminij = json.loads(gemini_json.read_text(encoding="utf-8"))


    paddlej["gemini_rec_texts"] = geminij["rec_texts"]
    paddlej["low_confidence"] = geminij.get("low_confidence", [])

    with output_json.open("w", encoding="utf-8") as f:
        json.dump(paddlej, f, indent=4, ensure_ascii=False)

    return output_json