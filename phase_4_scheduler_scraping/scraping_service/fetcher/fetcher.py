from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib import robotparser
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when a URL cannot be fetched via any available method."""


@dataclass
class FetchResult:
    url: str
    html: str
    method: str  # "playwright" | "httpx"


class RobotsCache:
    """Per-day cached robots.txt lookup. Aborts fetch if URL is disallowed."""

    def __init__(self, user_agent: str, ttl_seconds: int = 24 * 3600):
        self.user_agent = user_agent
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, robotparser.RobotFileParser]] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        now = time.time()
        entry = self._cache.get(base)
        if entry and now - entry[0] < self.ttl:
            rp = entry[1]
        else:
            rp = robotparser.RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception as e:
                log.warning("robots.txt fetch failed for %s: %s — allowing", base, e)
                return True
            self._cache[base] = (now, rp)
        return rp.can_fetch(self.user_agent, url)


class Fetcher:
    """Fetches rendered HTML. Playwright primary, httpx fallback."""

    def __init__(
        self,
        user_agent: str,
        nav_timeout_ms: int = 30000,
        wait_until: str = "networkidle",
        anchor_selector_text: Optional[str] = None,
        robots: Optional[RobotsCache] = None,
    ):
        self.user_agent = user_agent
        self.nav_timeout_ms = nav_timeout_ms
        self.wait_until = wait_until
        self.anchor_selector_text = anchor_selector_text
        self.robots = robots or RobotsCache(user_agent=user_agent)

    def fetch(self, url: str) -> FetchResult:
        if not self.robots.can_fetch(url):
            raise FetchError(f"robots.txt disallows fetching {url}")

        try:
            html = self._fetch_playwright(url)
            return FetchResult(url=url, html=html, method="playwright")
        except Exception as e:
            log.warning("Playwright fetch failed for %s: %s — trying httpx", url, e)

        try:
            html = self._fetch_httpx(url)
            return FetchResult(url=url, html=html, method="httpx")
        except Exception as e:
            raise FetchError(f"both Playwright and httpx failed for {url}: {e}") from e

    def _fetch_playwright(self, url: str) -> str:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                page.goto(url, wait_until=self.wait_until, timeout=self.nav_timeout_ms)
                if self.anchor_selector_text:
                    page.wait_for_selector(
                        f"text={self.anchor_selector_text}",
                        timeout=self.nav_timeout_ms,
                    )
                return page.content()
            finally:
                browser.close()

    def _fetch_httpx(self, url: str) -> str:
        import httpx  # type: ignore

        headers = {"User-Agent": self.user_agent}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
