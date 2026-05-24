"""
ElementLocator
Smart element finding with multiple selector strategies and graceful fallback.

Tries selectors in preferred order (id → xpath → css → class → name → tag).
Never raises — returns None / False / [] on failure.

Usage:
    locator = ElementLocator(driver, default_timeout=10)
    el = locator.find_element({"xpath": "//div[@class='rank']", "css": ".rank"})
    text = locator.get_text({"css": ".tier-label"})
"""

from typing import Dict, List, Optional

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class ElementLocator:
    """Finds Selenium elements using a dict of selector strategies, with fallback."""

    SELECTOR_TYPES: Dict[str, str] = {
        "xpath":             By.XPATH,
        "css":               By.CSS_SELECTOR,
        "id":                By.ID,
        "class":             By.CLASS_NAME,
        "tag":               By.TAG_NAME,
        "name":              By.NAME,
        "link_text":         By.LINK_TEXT,
        "partial_link_text": By.PARTIAL_LINK_TEXT,
    }

    PREFERRED_ORDER = ["id", "xpath", "css", "class", "name", "tag", "link_text", "partial_link_text"]

    def __init__(self, driver, default_timeout: int = 10):
        self.driver = driver
        self.default_timeout = default_timeout

    def find_element(self, selectors: Dict[str, str], timeout: Optional[int] = None,
                     context: str = "element") -> Optional[WebElement]:
        """Return the first matching WebElement, or None if nothing found."""
        timeout = timeout or self.default_timeout
        for selector_type in self.PREFERRED_ORDER:
            if selector_type in selectors:
                el = self._try_selector(selector_type, selectors[selector_type], timeout)
                if el is not None:
                    return el
        for selector_type, selector_value in selectors.items():
            if selector_type not in self.PREFERRED_ORDER:
                el = self._try_selector(selector_type, selector_value, timeout)
                if el is not None:
                    return el
        return None

    def find_elements(self, selectors: Dict[str, str], timeout: Optional[int] = None) -> List[WebElement]:
        """Return all matching WebElements, or [] if nothing found."""
        timeout = timeout or self.default_timeout
        for selector_type in ["id", "css", "xpath", "class", "name", "tag"]:
            if selector_type not in selectors or selector_type not in self.SELECTOR_TYPES:
                continue
            try:
                by = self.SELECTOR_TYPES[selector_type]
                WebDriverWait(self.driver, min(timeout, 5)).until(
                    EC.presence_of_element_located((by, selectors[selector_type]))
                )
                elements = self.driver.find_elements(by, selectors[selector_type])
                if elements:
                    return elements
            except (TimeoutException, NoSuchElementException, Exception):
                continue
        return []

    def wait_for_element(self, selectors: Dict[str, str], timeout: Optional[int] = None,
                         context: str = "element") -> bool:
        return self.find_element(selectors, timeout, context) is not None

    def click_element(self, selectors: Dict[str, str], timeout: Optional[int] = None,
                      context: str = "element") -> bool:
        el = self.find_element(selectors, timeout, context)
        if el:
            try:
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(el))
                el.click()
                return True
            except Exception:
                return False
        return False

    def get_text(self, selectors: Dict[str, str], timeout: Optional[int] = None,
                 context: str = "element") -> Optional[str]:
        el = self.find_element(selectors, timeout, context)
        return el.text.strip() if el else None

    def send_keys(self, selectors: Dict[str, str], text: str, timeout: Optional[int] = None,
                  context: str = "input") -> bool:
        el = self.find_element(selectors, timeout, context)
        if el:
            try:
                el.clear()
                el.send_keys(text)
                return True
            except Exception:
                return False
        return False

    def _try_selector(self, selector_type: str, selector_value: str,
                      timeout: int) -> Optional[WebElement]:
        if selector_type not in self.SELECTOR_TYPES:
            return None
        try:
            by = self.SELECTOR_TYPES[selector_type]
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector_value))
            )
        except (TimeoutException, Exception):
            return None
