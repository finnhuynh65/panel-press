"""Manual browser smoke test for the local Panel Press UI.

Run through the webapp-testing server helper on an unused port.
"""

import json
import os

from playwright.sync_api import sync_playwright


base_url = os.environ.get("PANEL_PRESS_TEST_URL", "http://127.0.0.1:8091")
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    assert page.title() == "Panel Press"
    assert page.locator("#scan").is_visible()
    assert page.locator("#convert").is_disabled()

    result = {
        "title": "Example Series",
        "chapters": [{"number": "1", "title": "Chapter 1", "url": "https://example.org/chapter/1", "chapter_id": "1"}],
        "preview": [{"index": 0, "title": "Chapter 1", "url": "https://example.org/chapter/1",
                     "page_count": 1, "first_page": "https://example.org/page.jpg", "error": None}],
        "ready": True,
        "suggestions": [],
    }
    page.route("**/api/v1/scans", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(result)))
    page.locator("#url").fill("https://example.org/series")
    page.locator("#scan").click()
    page.locator("#convert").wait_for(state="visible")
    assert page.locator("#convert").is_enabled()
    assert "Example Series" in page.locator("#scanStatus").inner_text()
    assert not errors, errors
    browser.close()
print("Browser smoke check passed")
