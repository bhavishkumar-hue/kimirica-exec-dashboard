"""
Open the dashboard in a real browser so Streamlit Community Cloud sees a viewer session, and wake it
if it's already asleep. A plain HTTP request doesn't work: curl never got past Streamlit Cloud's
cookie redirect (exit 47, too many redirects), and even a page fetch doesn't start an app session,
which is what counts as activity.

    python keep_alive.py https://<app>.streamlit.app/
"""
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1]
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


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 800})
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
            print("App is up" + (" (woken from sleep)." if woke else "."), flush=True)
            time.sleep(20)  # hold the session open briefly so it registers as a visit
            browser.close()
            sys.exit(0)
        time.sleep(5)
    page.screenshot(path="keep_alive_failure.png", full_page=True)
    print("App did not come up within 6 minutes; see the keep_alive_failure.png artifact.", flush=True)
    browser.close()
    sys.exit(1)
