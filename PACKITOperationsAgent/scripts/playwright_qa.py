"""Real-browser QA run of the live PackIT Operations Agent app via Playwright.
Not part of the pytest suite -- a one-off end-user navigation script. Prints
a structured transcript to stdout; screenshots go to scripts/qa_screenshots/.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
SHOT_DIR = Path(__file__).parent / "qa_screenshots"
SHOT_DIR.mkdir(exist_ok=True)

console_messages: list[str] = []


def shot(page, name: str) -> str:
    path = SHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    return str(path)


def wait_for_reply(page, prior_count: int, seen_steps: list, timeout_s: int = 150) -> str:
    """Wait until either a new assistant bubble appears or an error banner shows.
    Also polls for any transient staged-progress status text throughout the whole wait,
    not just the first couple seconds, since real queries can take a while before the
    first status line even appears.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # staged-progress candidates: pulsing/animated status line, or any short bubble
        # containing a leading bullet/dot and progress-ish wording
        for sel in ["div.animate-pulse", "text=/Interpreting|Searching|Analyzing|Thinking|Looking|Querying|Fetching|Retrieving|Checking|Gathering|Processing/i"]:
            try:
                loc = page.locator(sel)
                if loc.count():
                    txt = loc.first.inner_text().strip()
                    if txt and (not seen_steps or seen_steps[-1] != txt):
                        seen_steps.append(txt)
            except Exception:
                pass
        error_banner = page.locator("text=Something went wrong").count() or page.locator(
            "div.border-red-200"
        ).count()
        bubbles = page.locator("div.markdown")
        if bubbles.count() > prior_count:
            return bubbles.nth(bubbles.count() - 1).inner_text()
        if error_banner:
            return "[ERROR BANNER]: " + page.locator("div.border-red-200 span").first.inner_text()
        time.sleep(0.3)
    return "[TIMEOUT: no reply within {}s]".format(timeout_s)


def send_and_capture(page, text: str, step_name: str, report: list[str]) -> None:
    prior_bubbles = page.locator("div.markdown").count()
    textarea = page.get_by_placeholder("Ask about a packaging specification's replication status...")
    textarea.click()
    textarea.fill(text)
    send_btn = page.get_by_role("button", name="Send")
    t_start = time.time()
    send_btn.click()
    seen_steps: list[str] = []
    reply = wait_for_reply(page, prior_bubbles, seen_steps)
    elapsed = round(time.time() - t_start, 1)
    shot_path = shot(page, step_name)
    report.append(
        f"### {step_name}\n**Sent:** {text!r}\n**Elapsed:** {elapsed}s\n**Staged-progress observed:** {seen_steps}\n"
        f"**Reply (verbatim):** {reply!r}\n**Screenshot:** {shot_path}\n"
    )


def main() -> None:
    report: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda msg: console_messages.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: console_messages.append(f"[pageerror] {exc}"))

        # Step 1: initial load
        page.goto(BASE_URL, wait_until="networkidle")
        report.append(f"### Step 1: initial load\n**Screenshot:** {shot(page, '01_initial_load')}\n")

        # Step 2: create a new conversation explicitly (start clean)
        new_conv_btn = page.get_by_role("button", name="New conversation")
        new_conv_btn.click()
        time.sleep(0.5)
        report.append(f"### Step 2: clicked New conversation\n**Screenshot:** {shot(page, '02_new_conversation')}\n")

        # Steps 3-9: the query script
        send_and_capture(page, "Hi", "03_hi", report)
        send_and_capture(page, "What's the status of PS 00000000040001498023?", "04_ps_no_window", report)
        send_and_capture(page, "Why did PS 00000000040000054543 fail?", "05_ps_fail_no_window", report)
        send_and_capture(page, "Show me failed transfers for plant 0580 in the last 7 hours", "06_rich_answer", report)
        try:
            last_md = page.locator("div.markdown").last
            raw_html = last_md.inner_html()
            html_path = SHOT_DIR.parent / "06_rich_answer_raw.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(raw_html)
            report.append(f"### 06b_rich_answer_raw_html\n**Saved raw HTML of last bubble to:** {html_path}\n")
        except Exception as e:
            report.append(f"### 06b_rich_answer_raw_html\n**Error capturing raw HTML:** {e!r}\n")
        send_and_capture(page, "What about the other one at a different plant?", "07_loop_reference", report)
        send_and_capture(page, "What about PS 00000000099999999999?", "08_fake_ps", report)

        # Step 10a: reload, check persistence
        page.reload(wait_until="networkidle")
        time.sleep(1)
        bubble_count_after_reload = page.locator("div.markdown, div.bg-sky-600").count()
        report.append(
            f"### Step 10a: reload page\n**Message bubbles visible after reload:** {bubble_count_after_reload}\n"
            f"**Screenshot:** {shot(page, '09_after_reload')}\n"
        )

        # Step 10b: new conversation, check sidebar
        first_conv_button = page.locator("aside nav ul li button").first
        first_conv_title_before = first_conv_button.inner_text()
        new_conv_btn = page.get_by_role("button", name="New conversation")
        new_conv_btn.click()
        time.sleep(0.5)
        send_and_capture(page, "Hi", "10_second_conversation_hi", report)
        sidebar_items = page.locator("aside nav ul li button").all_inner_texts()
        report.append(
            f"### Step 10b: sidebar after second conversation\n"
            f"**First conversation's title before switching away:** {first_conv_title_before!r}\n"
            f"**All sidebar entries now:** {sidebar_items}\n"
            f"**Screenshot:** {shot(page, '11_sidebar_two_conversations')}\n"
        )

        # Step 10c: switch back to first conversation
        page.locator("aside nav ul li button").nth(1).click()
        time.sleep(1)
        report.append(
            f"### Step 10c: switched back to first conversation\n**Screenshot:** {shot(page, '12_switched_back')}\n"
        )

        # Step 10e: Report Issue button
        report_issue_btn = page.get_by_role("button", name="Report Issue")
        report.append(f"### Step 10e: Report Issue button state\n**Enabled:** {report_issue_btn.is_enabled()}\n")
        try:
            with page.expect_event("popup", timeout=3000) as popup_info:
                report_issue_btn.click()
            report.append("**Click result:** a popup/new page event fired\n")
        except Exception as e:
            report.append(f"**Click result:** no popup captured within 3s ({e.__class__.__name__}) -- likely attempted a mailto: navigation, which Playwright/headless Chromium may not surface as a popup\n")

        browser.close()

    full_text = "\n".join(report)
    full_text += "\n\n### Console messages captured across the whole session:\n"
    for m in console_messages:
        full_text += f"  {m}\n"

    out_path = SHOT_DIR.parent / "qa_report.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    # Best-effort console print (avoid crashing on cp1252-unencodable chars)
    try:
        print(full_text)
    except UnicodeEncodeError:
        print(full_text.encode("ascii", errors="replace").decode("ascii"))
    print(f"\n[report written to {out_path}]")


if __name__ == "__main__":
    main()
