import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-2-2-smoke")
TARGET = "SMOKE APPLY TARGET"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def dump(step):
    body = page.locator("body").inner_text()
    compact = " | ".join(line.strip() for line in body.splitlines() if line.strip())
    print(f"  [{step}] body: {compact[:300]}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(20000)

    # Step 1: default view is the New (24h) bucket with rows
    page.goto("http://localhost:3000", wait_until="networkidle")
    time.sleep(1)
    dump("step1")
    page.screenshot(path=str(SMOKE / "step-1-new-bucket.png"))
    body = page.locator("body").inner_text()
    new_active = page.locator("button", has_text="New (24h)").is_disabled()
    check("step1_default_new_bucket", new_active and TARGET in body, "New(24h) active + target visible")

    # Step 2: click the first "Mark as applied" (the target is the newest row)
    first_apply = page.locator("button", has_text="Mark as applied").first
    first_apply.click()
    time.sleep(1.5)
    dump("step2")
    page.screenshot(path=str(SMOKE / "step-2-applied-new.png"))
    body_after = page.locator("body").inner_text()
    check("step2_target_disappears_from_new", TARGET not in body_after, "row removed from New bucket")
    check("step2_no_error_shown", "HTTP" not in body_after and "Could not" not in body_after, "no error text")

    # Step 3: switch to All — target present with Applied badge
    page.locator("button", has_text="All").click()
    page.wait_for_url("**/?bucket=all", timeout=15000)
    time.sleep(1.5)
    dump("step3")
    page.screenshot(path=str(SMOKE / "step-3-applied-in-all.png"))
    body_all = page.locator("body").inner_text()
    check("step3_applied_badge_in_all", TARGET in body_all and "Applied" in body_all, "target + Applied badge")

    # Step 4: reload — state persists (server-side)
    page.goto("http://localhost:3000/?bucket=all", wait_until="networkidle")
    time.sleep(1)
    dump("step4")
    page.screenshot(path=str(SMOKE / "step-4-reload-persists.png"))
    body_reload = page.locator("body").inner_text()
    check("step4_state_persists_after_reload", TARGET in body_reload and "Applied" in body_reload, "badge survives reload")

    # Step 5: back in New — the applied target stays hidden
    page.locator("button", has_text="New (24h)").click()
    page.wait_for_url("http://localhost:3000/", timeout=15000)
    time.sleep(1.5)
    dump("step5")
    body_new2 = page.locator("body").inner_text()
    check("step5_applied_still_hidden_in_new", TARGET not in body_new2, "not in New bucket after toggle")

    browser.close()

failed = any(not ok for _, ok, _ in results)
print("TOTAL", sum(1 for _ in results), "FAILED", sum(1 for _, ok, _ in results if not ok))
sys.exit(1 if failed else 0)