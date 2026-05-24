"""
ScraperConfig
YAML-based configuration loader for Quartz scrapers.

Supports dot-notation access, deep merging of base + site-specific configs,
and environment variable overrides. All selectors live in YAML only.

Usage:
    config = ScraperConfig("opgg_config.yaml")
    config.get("urls.player_profile")
    config.get_selectors("search_input")
"""

import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path


class ScraperConfig:
    """
    Loads and merges YAML config files for Quartz scrapers.

    Config resolution order (highest priority last wins):
      1. base_config.yaml  (defaults)
      2. site-specific config (e.g. opgg_config.yaml)
      3. environment variable overrides
    """

    def __init__(self, config_file: str, base_config: str = "base_config.yaml"):
        self.config_dir = Path(__file__).parent.parent / "configs"
        self.base_config_path = self.config_dir / base_config
        self.config_path = self.config_dir / config_file
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        base = {}
        if self.base_config_path.exists():
            with open(self.base_config_path, "r") as f:
                base = yaml.safe_load(f) or {}

        site = {}
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                site = yaml.safe_load(f) or {}

        merged = self._deep_merge(base, site)
        self._apply_env_overrides(merged)
        return merged

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_env_overrides(self, config: Dict) -> None:
        if "SCRAPER_BROWSER" in os.environ:
            config.setdefault("browser", {})["type"] = os.environ["SCRAPER_BROWSER"]
        if "SCRAPER_HEADLESS" in os.environ:
            config.setdefault("browser", {})["headless"] = os.environ["SCRAPER_HEADLESS"].lower() == "true"
        if "SCRAPER_TIMEOUT" in os.environ:
            config.setdefault("timeouts", {})["default"] = int(os.environ["SCRAPER_TIMEOUT"])

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by dot-notation key. e.g. 'timeouts.element_wait'"""
        parts = key.split(".")
        value = self.config
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value

    def get_selectors(self, element_name: str) -> Dict[str, str]:
        """Return all selector strategies for a named element."""
        selectors = self.get(f"selectors.{element_name}", {})
        if not selectors:
            return {"xpath": f'//*[contains(text(), "{element_name}")]'}
        return selectors

    def get_browser_config(self) -> Dict[str, Any]:
        return self.get("browser", {
            "type": "chrome",
            "headless": True,
            "driver_path": "/opt/homebrew/bin/chromedriver",
        })

    def get_timeouts(self) -> Dict[str, int]:
        return self.get("timeouts", {"default": 10, "element_wait": 10, "page_load": 30})

    def get_urls(self) -> Dict[str, str]:
        return self.get("urls", {})

    def get_rate_limits(self) -> Dict[str, Any]:
        return self.get("rate_limits", {
            "requests_per_minute": 20,
            "delay_between_accounts": 3,
        })
