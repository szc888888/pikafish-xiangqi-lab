"""Load the project-level environment file before services read settings."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE, override=False)
