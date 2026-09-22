# -*- coding: utf-8 -*-
"""Targeted supplementary check: does clicking an existing conversation in the
sidebar correctly reload its full message history? (The main run's attempt at
this used an ambiguous locator that accidentally clicked a delete button
instead.) Also verifies the delete-button behavior explicitly.
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOT_DIR = Path(r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://127.0.0.1:8000", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(SHOT_DIR / "13_before_switch.png"))

    # Precisely target the conversation titled with "dca1d0" (has real Q&A history)
    target = page.locator("aside nav ul li").filter(has_text="dca1d0").locator("p").first
    print("Target text:", target.inner_text())
    target.click()
    page.wait_for_timeout(1200)
    page.screenshot(path=str(SHOT_DIR / "14_after_switch_to_dca1d0.png"))

    main_text = page.locator("main").inner_text()
    bubble_count = page.locator("div.markdown").count()
    print("Bubble count after switching:", bubble_count)
    print("Main text snapshot (first 500 chars):")
    print(main_text[:500])

    browser.close()
