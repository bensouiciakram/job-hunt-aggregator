import sys, time, json, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-1-8-smoke")
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, detail)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15000)

        page.goto("http://localhost:3000", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path=str(SMOKE / "step-1-load.png"))
        titles = page.locator("h2").all_inner_texts()
        check("step1_newest_title_renders", len(titles) >= 3, f"titles={titles[:3]}")
        body = page.locator("body").inner_text()
        check("step1_sweep_stamp", "Last sweep" in body, "stamp present")

        first_t1 = titles[0] if titles else ""
        page.locator("button", has_text="Next").first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=str(SMOKE / "step-2-page2.png"))
        t2 = page.locator("h2").first.inner_text()
        check("step2_page2_different_first_title", t2 != first_t1, f"t1={first_t1[:30]!r} t2={t2[:30]!r}")

        with urllib.request.urlopen("http://127.0.0.1:8000/api/listings/?page=1") as r:
            env = json.loads(r.read())
        newest = env["data"]["items"][0]["published_at"]
        shell_new = f"from listings.models import Listing, Source; s=Source.objects.first(); Listing.objects.create(source=s, title='SMOKE REFRESH PROOF', company='Smoke Corp', url='https://smoke.example/job-refresh', published_at='2099-01-01T00:00:00Z', keywords=['smoke'], raw_snapshot='{{}}'); print('created')"
        import subprocess
        subprocess.run(["uv", "run", "python", "manage.py", "shell", "-c", shell_new],
                       cwd=r"D:\personal projects\Job Hunt Mangement System\backend",
                       capture_output=True, text=True, timeout=120)

        page.goto("http://localhost:3000", wait_until="networkidle")
        time.sleep(1)
        page.locator("button", has_text="Refresh").first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        page.screenshot(path=str(SMOKE / "step-3-refresh.png"))
        body3 = page.locator("body").inner_text()
        check("step3_refresh_shows_new_listing", "SMOKE REFRESH PROOF" in body3)

        page.goto("http://localhost:3000?keyword=zzzzz", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path=str(SMOKE / "step-4-search.png"))
        body4 = page.locator("body").inner_text()
        check("step4_search_empty_copy", "No listings match your search" in body4)

        browser.close()
except Exception as e:
    import traceback
    traceback.print_exc()
    check("script_error", False, repr(e))

print("\n=== SUMMARY ===")
for name, ok, detail in results:
    print(("PASS" if ok else "FAIL"), "-", name, detail)
fails = [r for r in results if not r[1]]
print("TOTAL", len(results), "FAILED", len(fails))
sys.exit(1 if fails else 0)