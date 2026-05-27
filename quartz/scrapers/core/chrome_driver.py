"""Shared ChromeDriver service resolution."""

import shutil
from pathlib import Path
from typing import Optional

from selenium.webdriver.chrome.service import Service as ChromeService

from quartz.utils.logging import warning_print

# macOS Homebrew default — falls back to Selenium Manager on other platforms
DEFAULT_CHROMEDRIVER_PATH = "/opt/homebrew/bin/chromedriver"


def chrome_service(driver_path: Optional[str] = None) -> ChromeService:
    """
    Return a ChromeService for the current platform.

    Resolution order:
      1. Explicit driver_path from config (or SCRAPER_DRIVER_PATH env var via ScraperConfig)
      2. macOS Homebrew default (/opt/homebrew/bin/chromedriver) if it exists
      3. Selenium Manager (automatic cross-platform resolution)

    Warns when an explicit path is configured but the file is missing.
    """
    if driver_path:
        resolved = Path(driver_path).expanduser()
        if resolved.exists():
            return ChromeService(str(resolved))
        warning_print(f"ChromeDriver not found at {driver_path} — falling back to Selenium Manager")
        return ChromeService()

    # macOS Homebrew shortcut
    if Path(DEFAULT_CHROMEDRIVER_PATH).exists():
        return ChromeService(DEFAULT_CHROMEDRIVER_PATH)

    # Linux: check standard package manager locations
    linux_driver = shutil.which("chromedriver")
    if linux_driver:
        return ChromeService(linux_driver)

    # Fall back to Selenium Manager (handles Windows + anything else)
    return ChromeService()
