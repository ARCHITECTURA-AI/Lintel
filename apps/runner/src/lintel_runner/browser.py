"""A visible browser on the person's own machine, with an egress allowlist.

The runner uses its own browser profile. It navigates only to hosts in the registry plus the
asset hosts a reviewed page needs, and blocks everything else.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, Playwright, Route, sync_playwright

log = logging.getLogger("lintel.runner")
JS_DIR = Path(__file__).parent / "js"


def _candidates() -> list[str]:
    paths = []
    if os.environ.get("LINTEL_CHROMIUM_PATH"):
        paths.append(os.environ["LINTEL_CHROMIUM_PATH"])
    paths += sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"), reverse=True)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            paths.append(found)
    return paths


class Browser:
    def __init__(self, profile_dir: Path, *, headless: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
        self.allowed_hosts: set[str] = set()
        self.blocked: list[str] = []
        self._pw: Playwright | None = None
        self.context: BrowserContext | None = None
        self.pages: dict[str, Page] = {}

    def start(self) -> BrowserContext:
        self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kw = dict(headless=self.headless, viewport={"width": 1280, "height": 900}, accept_downloads=False)
        attempts: list[dict] = []
        if os.environ.get("LINTEL_BROWSER_CHANNEL"):
            attempts.append({"channel": os.environ["LINTEL_BROWSER_CHANNEL"]})
        attempts.append({})
        attempts += [{"executable_path": p} for p in _candidates()]
        last: Exception | None = None
        for extra in attempts:
            try:
                self.context = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kw, **extra)
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if self.context is None:
            raise RuntimeError(f"Couldn't start a browser. Run `playwright install chromium`. ({last})")
        self.context.route("**/*", self._route)
        from .forms import INIT_SCRIPT

        self.context.add_init_script(script=INIT_SCRIPT)
        for name in ("banner.js", "guard.js"):
            self.context.add_init_script(path=str(JS_DIR / name))
        return self.context

    def stop(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    # -- egress allowlist ---------------------------------------------------------

    def set_allowlist(self, hosts: list[str]) -> None:
        self.allowed_hosts = {h.lower() for h in hosts}

    def host_allowed(self, url: str) -> bool:
        p = urlparse(url)
        if p.scheme in ("data", "blob", "about", "chrome-extension"):
            return True
        return p.netloc.lower() in self.allowed_hosts

    def _route(self, route: Route) -> None:
        url = route.request.url
        if self.host_allowed(url):
            route.continue_()
            return
        self.blocked.append(url[:200])
        log.info("blocked request outside the allowlist: %s", url[:120])
        route.abort("blockedbyclient")

    # -- pages ----------------------------------------------------------------------

    def page_for(self, app_id: str) -> Page:
        page = self.pages.get(app_id)
        if page is not None and not page.is_closed():
            return page
        page = self.context.new_page()
        self.pages[app_id] = page
        return page

    def existing_page(self, app_id: str) -> Page | None:
        page = self.pages.get(app_id)
        return page if page is not None and not page.is_closed() else None

    def show_banner(self, page: Page, method: str, *args) -> None:
        try:
            page.evaluate(f"(a) => window.__lintelBanner && window.__lintelBanner.{method}(...a)", list(args))
        except Exception:  # noqa: BLE001 - the banner is a courtesy, never a dependency
            pass
