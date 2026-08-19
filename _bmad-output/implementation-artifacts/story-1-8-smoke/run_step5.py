import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-1-8-smoke")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15000)
        page.goto("http://localhost:3000", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path=str(SMOKE / "step-5-error.png"))
        body = page.locator("body").inner_text()
        ok = ("could not" in body.lower()) or ("error" in body.lower()) or ("failed" in body.lower())
        print(("PASS" if ok else "FAIL"), "step5_error_block", body[:200])
        browser.close()
        sys.exit(0 if ok else 1)
except Exception as e:
    print("FAIL step5_exception", repr(e))
    sys.exit(1)