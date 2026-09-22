# -*- coding: utf-8 -*-
import time
import json
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots"
LOG_PATH = r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots\transcript_log.json"

log = {"console": [], "steps": []}

def record_console(msg):
    entry = {"type": msg.type, "text": msg.text, "location": str(msg.location)}
    log["console"].append(entry)

def get_last_assistant_text(page):
    # message bubbles - try to find all message containers
    return None

def wait_for_reply_and_capture(page, timeout_ms=120000, poll_ms=500):
    """Poll for staged progress text and final reply, return dict with staged texts seen and final text."""
    staged_texts_seen = []
    start = time.time()
    last_seen_text = None
    # We will poll the last message area's text content repeatedly
    while (time.time() - start) * 1000 < timeout_ms:
        try:
            # capture any element that looks like a status/progress line
            status_candidates = page.locator("text=/Searching|Analyzing|Thinking|Looking|Querying|Fetching|Retrieving|Checking|Gathering/i")
            if status_candidates.count() > 0:
                for i in range(status_candidates.count()):
                    t = status_candidates.nth(i).inner_text()
                    if t and t not in staged_texts_seen:
                        staged_texts_seen.append(t)
        except Exception:
            pass
        time.sleep(poll_ms / 1000)
        # Check if send button re-enabled / no longer "sending" - handled by caller via other means
        break_check = page.locator("button:has-text('Send')")
        try:
            if break_check.count() > 0 and break_check.first.is_enabled():
                # small extra wait to ensure DOM settled
                time.sleep(1)
                break
        except Exception:
            pass
    return staged_texts_seen

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("console", record_console)

    # ---------- STEP 1 ----------
    t0 = time.time()
    page.goto("http://127.0.0.1:8000", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.screenshot(path=f"{SCREENSHOT_DIR}\\01_initial_load.png", full_page=True)
    step1_html = page.locator("body").inner_html()
    log["steps"].append({
        "step": 1,
        "action": "Load http://127.0.0.1:8000",
        "elapsed_s": round(time.time() - t0, 2),
        "body_snapshot_len": len(step1_html),
        "sidebar_text": page.locator("nav").inner_text() if page.locator("nav").count() else None,
        "main_text": page.locator("main").inner_text() if page.locator("main").count() else None,
    })

    # Start new conversation
    page.get_by_role("button", name="+ New conversation").click()
    page.wait_for_timeout(500)

    input_box = page.get_by_placeholder("Ask about a packaging specification's replication status...")
    send_btn = page.get_by_role("button", name="Send")

    def send_message(text, step_num, filename, wait_timeout=150000):
        t_start = time.time()
        input_box.fill(text)
        send_btn.click()
        # capture staged progress by polling periodically and screenshotting mid-flight once
        staged_seen = []
        mid_shot_taken = False
        deadline = time.time() + wait_timeout / 1000
        last_status_text = None
        while time.time() < deadline:
            # look for a status/progress indicator - try common patterns
            try:
                possible = page.locator("main").inner_text()
            except Exception:
                possible = ""
            # heuristic: capture any short line near bottom mentioning progress verbs
            for kw in ["Searching", "Analyzing", "Thinking", "Looking", "Querying", "Fetching",
                       "Retrieving", "Checking", "Gathering", "Processing", "Splunk", "Loading"]:
                if kw in possible:
                    # extract the line containing kw
                    for line in possible.splitlines():
                        if kw in line and line.strip() not in staged_seen:
                            staged_seen.append(line.strip())
            if not mid_shot_taken and time.time() - t_start > 1.5:
                try:
                    page.screenshot(path=f"{SCREENSHOT_DIR}\\{filename}_mid.png", full_page=True)
                except Exception:
                    pass
                mid_shot_taken = True
            # check if send button disabled state cleared (i.e. reply finished) -
            # use disabled attribute on send button as proxy for "in flight"
            try:
                is_disabled = send_btn.is_disabled()
            except Exception:
                is_disabled = True
            if not is_disabled and time.time() - t_start > 2:
                break
            time.sleep(0.5)
        # extra settle time
        page.wait_for_timeout(1500)
        elapsed = round(time.time() - t_start, 2)
        page.screenshot(path=f"{SCREENSHOT_DIR}\\{filename}.png", full_page=True)
        main_text = page.locator("main").inner_text()
        return {
            "step": step_num,
            "sent": text,
            "elapsed_s": elapsed,
            "staged_texts_seen": staged_seen,
            "main_text_after": main_text,
        }

    # ---------- STEP 2 ----------
    r2 = send_message("Hi", 2, "02_after_hi")
    log["steps"].append(r2)

    # ---------- STEP 3 ----------
    r3 = send_message("What's the status of PS 00000000040001498023?", 3, "03_after_ps_status")
    log["steps"].append(r3)

    # ---------- STEP 4 ----------
    r4 = send_message("Why did PS 00000000040000054543 fail?", 4, "04_after_ps_fail")
    log["steps"].append(r4)

    # ---------- STEP 5 ----------
    r5 = send_message("Show me failed transfers for plant 0580 in the last 7 hours", 5, "05_after_plant_0580", wait_timeout=180000)
    log["steps"].append(r5)
    # capture inner HTML of last message bubble for markdown rendering check
    try:
        last_msg_html = page.locator("main").inner_html()
        with open(f"{SCREENSHOT_DIR}\\05_main_inner_html.html", "w", encoding="utf-8") as f:
            f.write(last_msg_html)
    except Exception as e:
        log["steps"].append({"step": "5b_error", "error": str(e)})

    # ---------- STEP 6 ----------
    r6 = send_message("What about the other one at a different plant?", 6, "06_after_other_one", wait_timeout=180000)
    log["steps"].append(r6)

    # ---------- STEP 7 ----------
    r7 = send_message("What about PS 00000000099999999999?", 7, "07_after_fake_ps")
    log["steps"].append(r7)

    # save conversation title for later reference
    try:
        first_conv_title = page.locator("nav li").first.locator("p").first.inner_text()
    except Exception:
        first_conv_title = None
    log["first_conv_title_after_step7"] = first_conv_title

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    browser.close()

print("DONE - main flow (steps 1-7) complete. Log written to", LOG_PATH)
