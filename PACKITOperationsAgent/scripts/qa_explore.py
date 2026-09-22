from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    console_msgs = []
    def on_console(msg):
        console_msgs.append(f"[{msg.type}] {msg.text}")
    page.on("console", on_console)

    page.goto("http://127.0.0.1:8000", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{SCREENSHOT_DIR}\\00_explore_initial.png", full_page=True)

    print("=== TITLE ===")
    print(page.title())

    print("=== BODY HTML (first 8000 chars) ===")
    content = page.content()
    print(content[:8000])

    print("=== CONSOLE MESSAGES SO FAR ===")
    for m in console_msgs:
        print(m)

    browser.close()
