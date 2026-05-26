"""
Quartz config loader.
Loads API keys and environment variables from config/api.env.
Never commit api.env to git (it's gitignored).
"""

import os
from pathlib import Path

import dotenv

_CONFIG_DIR = Path(__file__).parent


def get_riot_api_config(param: str = None):
    """Load a Riot API config value from config/api.env."""
    dotenv.load_dotenv(_CONFIG_DIR / "api.env", override=False)
    if param:
        return os.getenv(param)
    return None
