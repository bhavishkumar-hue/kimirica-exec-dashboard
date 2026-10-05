"""
Open the dashboard in a real browser so Streamlit Community Cloud sees a viewer session, and wake it
if it's already asleep. A plain HTTP request doesn't work: curl never got past Streamlit Cloud's
cookie redirect (exit 47, too many redirects), and even a page fetch doesn't start an app session,
which is what counts as activity.

    python keep_alive.py https://<app>.streamlit.app/
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1]
# A normal desktop browser, not "HeadlessChrome", so the visit looks like any other viewer's.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
WAKE = "get this app back up"
UP_SELECTOR = 'input[type="password"], [data-testid="stDataFrame"]'


def find_wake_button(page):
    for frame in page.frames:
        btn = frame.get_by_role("button", name=WAKE)
        if btn.count():
            return btn.first
    return None


def app_is_up(page) -> bool:
    return any(f.locator(UP_SELECTOR).count() for f in page.frames)


def summary(line: str):
    """Print, and add to the run's summary page on GitHub."""
    print(line, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


start = time.time()
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 800}, user_agent=UA)
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    woke = False
    deadline = time.time() + 6 * 60
    while time.time() < deadline:
        btn = find_wake_button(page)
        if btn:
            print("App was asleep; clicking the wake button.", flush=True)
            btn.click()
            woke = True
            time.sleep(30)
            continue
        if app_is_up(page):
            summary(f"App is up{' (woken from sleep)' if woke else ''}; loaded in {time.time() - start:.0f}s.")
            time.sleep(20)  # hold the session open briefly so it registers as a visit
            browser.close()
            sys.exit(0)
        time.sleep(5)
    page.screenshot(path="keep_alive_failure.png", full_page=True)
    summary("App did not come up within 6 minutes; see the keep_alive_failure.png artifact.")
    browser.close()
    sys.exit(1)
