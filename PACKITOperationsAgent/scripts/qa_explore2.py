from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = r"C:\Users\SHJ6COB\Desktop\AIDE\PACKITOperationsAgent\scripts\qa_screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    page.goto("http://127.0.0.1:8000", wait_until="networkidle")
    page.wait_for_timeout(1000)

    page.get_by_role("button", name="New conversation").click()
    page.wait_for_timeout(1000)
    page.screenshot(path=f"{SCREENSHOT_DIR}\\00_explore_new_conv.png", full_page=True)

    print("=== BODY HTML after New conversation click ===")
    print(page.content()[3000:12000])

    browser.close()
