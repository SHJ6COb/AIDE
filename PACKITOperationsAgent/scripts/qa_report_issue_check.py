# -*- coding: utf-8 -*-
"""Check Report Issue button state/behavior when a real conversation with
messages is actually open (the main run's check happened on an empty pane
due to a selector bug, so it always reported disabled)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOT_DIR = Path(r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://127.0.0.1:8000", wait_until="networkidle")
    page.wait_for_timeout(600)

    target = page.locator("aside nav ul li").filter(has_text="dca1d0").locator("p").first
    target.click()
    page.wait_for_timeout(1000)

    btn = page.get_by_role("button", name="Report Issue")
    print("Report Issue enabled with active conversation open:", btn.is_enabled())
    page.screenshot(path=str(SHOT_DIR / "15_report_issue_enabled_state.png"))

    try:
        with page.expect_event("popup", timeout=3000) as popup_info:
            btn.click()
        popup = popup_info.value
        print("Popup URL:", popup.url)
    except Exception as e:
        print(f"No popup captured within 3s ({e.__class__.__name__})")
    page.wait_for_timeout(500)
    page.screenshot(path=str(SHOT_DIR / "16_after_report_issue_click.png"))

    browser.close()
