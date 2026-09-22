"""Focused live verification of the reload-restore and delete-confirmation
fixes. Not part of the pytest suite.
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
SHOT_DIR = Path(__file__).parent / "verify_screenshots"
SHOT_DIR.mkdir(exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(BASE_URL, wait_until="networkidle")
        page.get_by_role("button", name="New conversation").click()
        time.sleep(0.5)
        textarea = page.get_by_placeholder("Ask about a packaging specification's replication status...")
        textarea.click()
        textarea.fill("Hi")
        page.get_by_role("button", name="Send").click()

        # Wait for a reply (bounded)
        deadline = time.time() + 30
        while time.time() < deadline:
            if page.locator("div.markdown").count() > 0:
                break
            time.sleep(0.5)

        bubbles_before = page.locator("div.markdown, div.bg-sky-600").count()
        print(f"bubbles before reload: {bubbles_before}")

        # --- RELOAD-RESTORE CHECK ---
        page.reload(wait_until="networkidle")
        time.sleep(1.5)
        bubbles_after = page.locator("div.markdown, div.bg-sky-600").count()
        header_text = page.locator("main p.text-slate-400, main div.text-slate-400").all_inner_texts()
        print(f"bubbles after reload: {bubbles_after}")
        print(f"empty-state text after reload (should be empty list if a conversation IS shown): {header_text}")
        page.screenshot(path=str(SHOT_DIR / "after_reload.png"))

        # --- DELETE-CONFIRMATION CHECK ---
        dialog_seen = {"triggered": False, "message": None}

        def handle_dialog(dialog):
            dialog_seen["triggered"] = True
            dialog_seen["message"] = dialog.message
            dialog.dismiss()  # cancel -- conversation should NOT be deleted

        page.on("dialog", handle_dialog)

        # hover to reveal the delete button, then click it
        conv_row = page.locator("aside nav ul li").first
        conv_row.hover()
        delete_btn = conv_row.get_by_label("Delete conversation")
        delete_btn.click()
        time.sleep(0.5)

        print(f"confirm dialog triggered: {dialog_seen['triggered']}")
        print(f"confirm dialog message: {dialog_seen['message']!r}")

        # Verify the conversation is STILL there since we dismissed the dialog
        remaining = page.locator("aside nav ul li").count()
        print(f"conversations remaining after dismissed delete: {remaining}")

        browser.close()


if __name__ == "__main__":
    main()
