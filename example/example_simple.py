from rotunda.sync_api import Rotunda

ACCEPT_ENCODING = "identity"

with Rotunda(headless=False) as browser:
    page = browser.new_page(extra_http_headers={"accept-encoding": ACCEPT_ENCODING})
    page.goto("https://abrahamjuliot.github.io/creepjs/")
    input("Press Enter to close...")
