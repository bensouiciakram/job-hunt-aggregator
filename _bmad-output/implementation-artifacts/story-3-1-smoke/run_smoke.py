import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-3-1-smoke")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(20000)

    page.goto("http://localhost:3000/?bucket=all", wait_until="networkidle")
    time.sleep(1)
    page.screenshot(path=str(SMOKE / "step-1-scores.png"))

    chips = page.locator("span[title='Interest score']")
    count = chips.count()
    check("step1_chips_render", count >= 3, f"{count} rows with chips")

    all_ok = True
    tones = {"emerald", "red", "zinc"}
    seen_tones = set()
    for i in range(count):
        text = chips.nth(i).inner_text()
        cls = chips.nth(i).get_attribute("class") or ""
        ok = text.isdigit() and 0 <= int(text) <= 100
        tone = next((t for t in tones if t in cls), None)
        all_ok = all_ok and ok and tone is not None
        if tone:
            seen_tones.add(tone)
    check("step2_chip_values_and_tones", all_ok, f"tones seen: {sorted(seen_tones)}")
    check("step3_tone_variety", len(seen_tones) >= 2, f"tones seen: {sorted(seen_tones)}")

    body = page.locator("body").inner_text()
    check("step4_no_chip_errors", "undefined" not in body, "no 'undefined' chip text")

    browser.close()

failed = any(not ok for _, ok, _ in results)
print("TOTAL", len(results), "FAILED", sum(1 for _, ok, _ in results if not ok))
sys.exit(1 if failed else 0)