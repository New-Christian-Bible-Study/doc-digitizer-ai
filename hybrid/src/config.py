from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / "secrets.env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")
GEMINI_SYSTEM_PROMPT_PATH = Path(
    os.getenv("GEMINI_SYSTEM_PROMPT", "src\prompts\gemini_system.txt")
)

GEMINI_USER_PROMPT_PATH = Path(
    os.getenv("GEMINI_USER_PROMPT", "src\prompts\gemini_user.txt")
)

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY in environment or .env file.")