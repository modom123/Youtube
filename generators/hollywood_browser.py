"""
Hollywood Browser — Playwright-based browser automation for Hollywood agent.
Allows Hollywood to navigate, click, scrape, screenshot, and interact with any website.
"""
import base64
import os
import time

# Screenshot output directory
SCREENSHOT_DIR = "/tmp/hollywood_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Module-level browser state (lazy-init)
_playwright_instance = None
_browser_instance = None
_page_instance = None


def _is_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def get_page():
    """Return the persistent browser page, lazy-initialising as needed."""
    global _playwright_instance, _browser_instance, _page_instance

    if _page_instance is not None:
        try:
            # Quick liveness check
            _page_instance.url  # noqa: B018
            return _page_instance
        except Exception:
            _page_instance = None
            _browser_instance = None

    from playwright.sync_api import sync_playwright  # type: ignore

    _playwright_instance = sync_playwright().start()
    _browser_instance = _playwright_instance.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors"]
    )
    context = _browser_instance.new_context(
        viewport={"width": 1280, "height": 800},
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    )
    _page_instance = context.new_page()
    return _page_instance


def close_browser() -> dict:
    """Close and reset the browser instance."""
    global _playwright_instance, _browser_instance, _page_instance
    try:
        if _browser_instance:
            _browser_instance.close()
        if _playwright_instance:
            _playwright_instance.stop()
    except Exception:
        pass
    finally:
        _playwright_instance = None
        _browser_instance = None
        _page_instance = None
    return {"status": "browser closed"}


def navigate(url: str) -> dict:
    """Navigate to a URL. Returns page title and current URL."""
    page = get_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    return {"title": page.title(), "url": page.url}


def screenshot(path: str = None) -> dict:
    """Take a screenshot. Returns base64 PNG and file path."""
    page = get_page()
    if path is None:
        ts = int(time.time() * 1000)
        path = os.path.join(SCREENSHOT_DIR, f"hw_{ts}.png")
    page.screenshot(path=path, full_page=False)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"screenshot_path": path, "screenshot_b64": b64, "url": page.url}


def click(selector: str) -> dict:
    """Click an element by CSS selector or visible text."""
    page = get_page()
    try:
        page.click(selector, timeout=8000)
        return {"clicked": selector, "url": page.url}
    except Exception:
        # Fall back to text-based lookup
        page.get_by_text(selector).first.click(timeout=8000)
        return {"clicked_by_text": selector, "url": page.url}


def type_text(selector: str, text: str) -> dict:
    """Click, clear, and type text into an input field."""
    page = get_page()
    page.click(selector, timeout=8000)
    page.fill(selector, text, timeout=8000)
    return {"typed": text, "selector": selector}


def get_page_text() -> dict:
    """Return visible text of current page (stripped, max 4000 chars)."""
    page = get_page()
    text = page.inner_text("body")
    text = " ".join(text.split())[:4000]
    return {"text": text, "url": page.url, "length": len(text)}


def get_page_html(selector: str = None) -> dict:
    """Return innerHTML of selector or full body (max 4000 chars)."""
    page = get_page()
    target = selector or "body"
    html = page.inner_html(target, timeout=8000)[:4000]
    return {"html": html, "selector": target, "url": page.url}


def scroll(direction: str = "down", amount: int = 500) -> dict:
    """Scroll the page."""
    page = get_page()
    dy = amount if direction == "down" else -amount
    page.evaluate(f"window.scrollBy(0, {dy})")
    return {"scrolled": direction, "amount": amount}


def wait_for(selector: str, timeout: int = 10000) -> dict:
    """Wait for an element to appear on the page."""
    page = get_page()
    page.wait_for_selector(selector, timeout=timeout)
    return {"found": selector}


def get_current_url() -> dict:
    """Return the current page URL."""
    page = get_page()
    return {"url": page.url, "title": page.title()}


def fill_form(fields: dict) -> dict:
    """Fill multiple form fields at once. fields = {selector: value}."""
    page = get_page()
    filled = []
    errors = []
    for selector, value in fields.items():
        try:
            page.fill(selector, str(value), timeout=5000)
            filled.append(selector)
        except Exception as e:
            errors.append({"selector": selector, "error": str(e)})
    return {"filled": filled, "errors": errors}


def press_key(key: str) -> dict:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    page = get_page()
    page.keyboard.press(key)
    return {"pressed": key, "url": page.url}


def extract_links() -> dict:
    """Return list of all links on page with text and href."""
    page = get_page()
    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a[href]'))
            .map(a => ({ text: (a.innerText || '').trim(), href: a.href }))
            .filter(l => l.href && !l.href.startsWith('javascript:'))
            .slice(0, 100)
    """)
    return {"links": links, "count": len(links), "url": page.url}


def extract_table(selector: str) -> dict:
    """Extract a table as a list of dicts."""
    page = get_page()
    data = page.evaluate(f"""
        () => {{
            const table = document.querySelector({repr(selector)});
            if (!table) return null;
            const headers = Array.from(table.querySelectorAll('th')).map(h => h.innerText.trim());
            const rows = Array.from(table.querySelectorAll('tbody tr')).map(row =>
                Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim())
            );
            if (headers.length) {{
                return rows.map(row => Object.fromEntries(headers.map((h, i) => [h, row[i] || ''])));
            }}
            return rows;
        }}
    """)
    return {"table": data, "selector": selector}
