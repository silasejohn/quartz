"""
BaseScraper
Abstract base class for all Quartz scrapers.

Manages Chrome WebDriver lifecycle and exposes named-element access so that
all selectors remain in YAML config — never hardcoded in Python.

Usage:
    class MyScraper(BaseScraper):
        def __init__(self):
            super().__init__("mysite_config.yaml")

    scraper = MyScraper()
    scraper.setup()
    scraper.navigate_to("https://example.com")
    el = scraper.find_element("search_input")
    scraper.close()
"""

import os
import shutil
import time
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions

from quartz.scrapers.core.chrome_driver import chrome_service
from quartz.scrapers.core.element_locator import ElementLocator
from quartz.scrapers.core.scraper_config import ScraperConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print


class BaseScraper:
    """
    Base class for Quartz scrapers. Subclasses inherit WebDriver management and
    config-driven element access; they only need to implement scraping logic.

    Class attributes to override in subclasses:
      requires_visible_browser — set to False only after confirming the scraper works
                                 in headless mode. Defaults True: scrapers that rely on
                                 hover/tooltip interactions (OP.GG, LOG) silently return
                                 incomplete data in headless mode with no other warning.
    """

    requires_visible_browser: bool = True

    def __init__(self, config_file: str, website_timeout: int = 5):
        self.config = ScraperConfig(config_file)
        self.driver: Optional[webdriver.Chrome] = None
        self.element_locator: Optional[ElementLocator] = None
        self.website_timeout = website_timeout

        self.main_website = self.config.get("urls.main", "")
        self.website_name = self.config.get("website.name", "Unknown")

        info_print(f"Initialized {self.__class__.__name__} for {self.website_name}")

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def setup(self, browser_headless: Optional[bool] = None) -> int:
        """
        Initialize WebDriver and navigate to the main page.
        Returns 1 on success, 0 if driver already exists, -1 on error.
        """
        if self.driver is not None:
            warning_print("WebDriver already exists — skipping setup")
            return 0

        if browser_headless and self.requires_visible_browser:
            raise RuntimeError(
                f"{self.__class__.__name__} requires a visible browser (hover tooltips). "
                "Call setup() without browser_headless=True, or verify headless works and "
                "set requires_visible_browser = False on the class."
            )

        try:
            info_print(f"Setting up {self.website_name} scraper")
            result = self._setup_webdriver(browser_headless)
            if result == -1:
                return -1

            self.element_locator = ElementLocator(self.driver, self.website_timeout)

            if self.main_website:
                warning_print(f"{self.website_name} WebDriver loading...")
                self.driver.get(self.main_website)
                success_print(f"{self.website_name} WebDriver ready!")

            return 1

        except Exception as e:
            error_print(f"Failed to setup {self.website_name}: {e}")
            self.close()
            return -1

    def close(self) -> None:
        """Quit WebDriver and clean up."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.element_locator = None
            success_print(f"{self.website_name} scraper closed")

    # ------------------------------------------------------------------
    # Element access (all backed by YAML selectors)
    # ------------------------------------------------------------------

    def find_element(self, element_name: str, timeout: Optional[int] = None):
        """Find a named element using its YAML-configured selectors."""
        if not self.element_locator:
            error_print("Element locator not initialized — call setup() first")
            return None
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.find_element(selectors, timeout, element_name)

    def find_elements(self, element_name: str, timeout: Optional[int] = None):
        """Find all matching elements for a named selector."""
        if not self.element_locator:
            error_print("Element locator not initialized — call setup() first")
            return []
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.find_elements(selectors, timeout)

    def wait_for_element(self, element_name: str, timeout: Optional[int] = None) -> bool:
        """Return True if named element appears within timeout."""
        if not self.element_locator:
            return False
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.wait_for_element(selectors, timeout, element_name)

    def click_element(self, element_name: str, timeout: Optional[int] = None) -> bool:
        """Find and click a named element."""
        if not self.element_locator:
            return False
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.click_element(selectors, timeout, element_name)

    def get_element_text(self, element_name: str, timeout: Optional[int] = None) -> Optional[str]:
        """Return the text of a named element, or None."""
        if not self.element_locator:
            return None
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.get_text(selectors, timeout, element_name)

    def send_keys_to_element(self, element_name: str, text: str, timeout: Optional[int] = None) -> bool:
        """Clear and type into a named element."""
        if not self.element_locator:
            return False
        selectors = self.config.get_selectors(element_name)
        timeout = timeout or self.config.get("timeouts.element_wait", 10)
        return self.element_locator.send_keys(selectors, text, timeout, element_name)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def navigate_to(self, url: str) -> None:
        """Navigate to a URL and wait for the page to settle."""
        if not self.driver:
            error_print("WebDriver not initialized — call setup() first")
            return
        self.driver.get(url)
        self.buffer()

    def buffer(self, seconds: Optional[int] = None) -> None:
        """Sleep briefly to let the page settle."""
        time.sleep(seconds or self.website_timeout)

    # ------------------------------------------------------------------
    # WebDriver setup (internal)
    # ------------------------------------------------------------------

    def _setup_webdriver(self, browser_headless: Optional[bool] = None) -> int:
        browser_config = self.config.get_browser_config()
        browser_type = browser_config.get("type", "chrome").lower()

        if browser_type != "chrome":
            error_print(f"Unsupported browser type: {browser_type} (only chrome supported)")
            return -1

        try:
            self.driver = self._setup_chrome(browser_config, browser_headless)
            return 1
        except WebDriverException as e:
            self._handle_webdriver_error(e)
            return -1
        except Exception as e:
            error_print(f"Unexpected error setting up WebDriver: {e}")
            return -1

    def _setup_chrome(self, config: dict, browser_headless: Optional[bool] = None) -> webdriver.Chrome:
        options = ChromeOptions()
        use_headless = self._resolve_headless(config, browser_headless)
        self._set_chrome_binary(options)
        self._add_chrome_options(options, use_headless)

        page_load_strategy = self.config.get("browser.page_load_strategy", "eager")
        options.page_load_strategy = page_load_strategy
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        service = chrome_service(config.get("driver_path"))
        return webdriver.Chrome(service=service, options=options)

    def _resolve_headless(self, config: dict, browser_headless: Optional[bool]) -> bool:
        use_headless = browser_headless if browser_headless is not None else config.get("headless", True)
        if not use_headless and os.name != "nt" and not os.environ.get("DISPLAY"):
            warning_print("No display detected — using headless Chrome")
            return True
        return use_headless

    def _set_chrome_binary(self, options: ChromeOptions) -> None:
        chrome_binary = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if chrome_binary:
            options.binary_location = chrome_binary

    def _add_chrome_options(self, options: ChromeOptions, use_headless: bool) -> None:
        chrome_options_config = self.config.get("browser.chrome_options", {})
        if chrome_options_config:
            mode = "headless_mode" if use_headless else "visible_mode"
            for arg in chrome_options_config.get(mode, []):
                options.add_argument(arg)
            return

        for arg in self._default_chrome_args(use_headless):
            options.add_argument(arg)

    def _default_chrome_args(self, use_headless: bool) -> list[str]:
        mode_args = ["--headless", "--window-size=1920,1080"] if use_headless else ["--start-maximized"]
        return [*mode_args, "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

    def _handle_webdriver_error(self, error: WebDriverException) -> None:
        msg = str(error).lower()
        if "permission denied" in msg or "operation not permitted" in msg:
            error_print("ChromeDriver blocked by macOS — run: xattr -d com.apple.quarantine /opt/homebrew/bin/chromedriver")
        elif "version" in msg and "supports" in msg:
            error_print("ChromeDriver version mismatch — run: brew install --cask chromedriver")
        elif "no such file" in msg and "chromedriver" in msg:
            error_print("ChromeDriver not found — install Chrome/Chromium or set SCRAPER_DRIVER_PATH")
        elif "unable to obtain driver" in msg:
            error_print("Unable to obtain ChromeDriver — install Chrome/Chromium or set SCRAPER_DRIVER_PATH")
        else:
            error_print(f"WebDriver error: {error}")
