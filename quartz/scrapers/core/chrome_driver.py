"""Shared ChromeDriver service resolution."""

from pathlib import Path
from typing import Optional

from selenium.webdriver.chrome.service import Service as ChromeService

DEFAULT_CHROMEDRIVER_PATH = "/opt/homebrew/bin/chromedriver"


def chrome_service(driver_path: Optional[str] = None) -> ChromeService:
    """
    Return a Chrome service using an explicit driver only when it exists.

    When no usable path is provided, Selenium Manager resolves the driver for
    the current platform.
    """
    path = driver_path or DEFAULT_CHROMEDRIVER_PATH
    if path and Path(path).expanduser().exists():
        return ChromeService(str(Path(path).expanduser()))
    return ChromeService()
