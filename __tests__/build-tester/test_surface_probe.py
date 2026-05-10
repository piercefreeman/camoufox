from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

pytestmark = pytest.mark.integration


PROBE_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Rotunda Surface Probe</title>
</head>
<body></body>
</html>
"""


SURFACE_PROBE_SCRIPT = r"""async () => {
  const finiteNumber = value =>
    typeof value === "number" && Number.isFinite(value) ? value : null;

  const rectPayload = rect => ({
    width: finiteNumber(rect.width),
    height: finiteNumber(rect.height),
    top: finiteNumber(rect.top),
    left: finiteNumber(rect.left),
  });

  const match = (win, query) => {
    try {
      return win.matchMedia(query).matches;
    } catch (error) {
      return `error: ${String(error)}`;
    }
  };

  const collectWindow = win => {
    const doc = win.document;
    const root = doc.documentElement;
    const body = doc.body || doc.createElement("body");
    if (!doc.body) root.appendChild(body);

    const innerWidth = win.innerWidth;
    const innerHeight = win.innerHeight;
    const screenWidth = win.screen.width;
    const screenHeight = win.screen.height;
    const dpr = win.devicePixelRatio || 1;
    const colorComponents = Math.max(0, Math.floor((win.screen.colorDepth || 0) / 3));

    const style = doc.createElement("style");
    style.textContent = `
      html, body {
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        height: 100% !important;
        overflow: hidden !important;
      }
      :root {
        --rotunda-mq-width: no;
        --rotunda-mq-height: no;
        --rotunda-mq-device-width: no;
        --rotunda-mq-device-height: no;
        --rotunda-mq-resolution: no;
        --rotunda-mq-color: no;
      }
      #rotunda-vw-probe {
        position: fixed;
        left: 0;
        top: 0;
        width: 100vw;
        height: 100vh;
        pointer-events: none;
      }
      #rotunda-dvw-probe {
        position: fixed;
        left: 0;
        top: 0;
        width: 100dvw;
        height: 100dvh;
        pointer-events: none;
      }
      #rotunda-percent-probe {
        position: fixed;
        left: 0;
        top: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
      }
      @media (width: ${innerWidth}px) {
        :root { --rotunda-mq-width: yes; }
      }
      @media (height: ${innerHeight}px) {
        :root { --rotunda-mq-height: yes; }
      }
      @media (device-width: ${screenWidth}px) {
        :root { --rotunda-mq-device-width: yes; }
      }
      @media (device-height: ${screenHeight}px) {
        :root { --rotunda-mq-device-height: yes; }
      }
      @media (resolution: ${dpr}dppx) {
        :root { --rotunda-mq-resolution: yes; }
      }
      @media (color: ${colorComponents}) {
        :root { --rotunda-mq-color: yes; }
      }
    `;
    (doc.head || root).appendChild(style);

    const viewportProbe = doc.createElement("div");
    viewportProbe.id = "rotunda-vw-probe";
    const dynamicViewportProbe = doc.createElement("div");
    dynamicViewportProbe.id = "rotunda-dvw-probe";
    const percentProbe = doc.createElement("div");
    percentProbe.id = "rotunda-percent-probe";
    body.appendChild(viewportProbe);
    body.appendChild(dynamicViewportProbe);
    body.appendChild(percentProbe);

    root.setAttribute("data-rotunda-screen-width", String(screenWidth));
    root.setAttribute("data-rotunda-screen-height", String(screenHeight));
    body.setAttribute("data-rotunda-inner-width", String(innerWidth));
    body.setAttribute("data-rotunda-inner-height", String(innerHeight));

    const rootStyle = win.getComputedStyle(root);
    const rootRect = root.getBoundingClientRect();
    const bodyRect = body.getBoundingClientRect();
    const viewportRect = viewportProbe.getBoundingClientRect();
    const dynamicViewportRect = dynamicViewportProbe.getBoundingClientRect();
    const percentRect = percentProbe.getBoundingClientRect();
    const visualViewport = win.visualViewport;
    const orientation = win.screen.orientation;

    return {
      navigator: {
        userAgent: win.navigator.userAgent || "",
        appVersion: win.navigator.appVersion || "",
        platform: win.navigator.platform || "",
        oscpu: win.navigator.oscpu || "",
        hardwareConcurrency: win.navigator.hardwareConcurrency || 0,
        maxTouchPoints: win.navigator.maxTouchPoints || 0,
        language: win.navigator.language || "",
        languages: Array.from(win.navigator.languages || []),
        product: win.navigator.product || "",
        productSub: win.navigator.productSub || "",
        vendor: win.navigator.vendor || "",
        cookieEnabled: !!win.navigator.cookieEnabled,
        onLine: !!win.navigator.onLine,
        doNotTrack: win.navigator.doNotTrack || "",
        globalPrivacyControl: win.navigator.globalPrivacyControl ?? null,
      },
      screen: {
        width: finiteNumber(win.screen.width),
        height: finiteNumber(win.screen.height),
        availWidth: finiteNumber(win.screen.availWidth),
        availHeight: finiteNumber(win.screen.availHeight),
        availLeft: finiteNumber(win.screen.availLeft),
        availTop: finiteNumber(win.screen.availTop),
        colorDepth: finiteNumber(win.screen.colorDepth),
        pixelDepth: finiteNumber(win.screen.pixelDepth),
        orientation: orientation ? {
          type: orientation.type || "",
          angle: finiteNumber(orientation.angle),
        } : null,
        isExtended: typeof win.screen.isExtended === "boolean" ? win.screen.isExtended : null,
      },
      window: {
        innerWidth: finiteNumber(win.innerWidth),
        innerHeight: finiteNumber(win.innerHeight),
        outerWidth: finiteNumber(win.outerWidth),
        outerHeight: finiteNumber(win.outerHeight),
        screenX: finiteNumber(win.screenX),
        screenY: finiteNumber(win.screenY),
        screenLeft: finiteNumber(win.screenLeft),
        screenTop: finiteNumber(win.screenTop),
        devicePixelRatio: finiteNumber(win.devicePixelRatio),
        pageXOffset: finiteNumber(win.pageXOffset),
        pageYOffset: finiteNumber(win.pageYOffset),
      },
      documentElement: {
        clientWidth: finiteNumber(root.clientWidth),
        clientHeight: finiteNumber(root.clientHeight),
        scrollWidth: finiteNumber(root.scrollWidth),
        scrollHeight: finiteNumber(root.scrollHeight),
        rect: rectPayload(rootRect),
      },
      body: {
        clientWidth: finiteNumber(body.clientWidth),
        clientHeight: finiteNumber(body.clientHeight),
        scrollWidth: finiteNumber(body.scrollWidth),
        scrollHeight: finiteNumber(body.scrollHeight),
        rect: rectPayload(bodyRect),
      },
      visualViewport: visualViewport ? {
        width: finiteNumber(visualViewport.width),
        height: finiteNumber(visualViewport.height),
        scale: finiteNumber(visualViewport.scale),
        offsetLeft: finiteNumber(visualViewport.offsetLeft),
        offsetTop: finiteNumber(visualViewport.offsetTop),
        pageLeft: finiteNumber(visualViewport.pageLeft),
        pageTop: finiteNumber(visualViewport.pageTop),
      } : null,
      css: {
        viewportProbe: rectPayload(viewportRect),
        dynamicViewportProbe: rectPayload(dynamicViewportRect),
        percentProbe: rectPayload(percentRect),
        customProperties: {
          mqWidth: rootStyle.getPropertyValue("--rotunda-mq-width").trim(),
          mqHeight: rootStyle.getPropertyValue("--rotunda-mq-height").trim(),
          mqDeviceWidth: rootStyle.getPropertyValue("--rotunda-mq-device-width").trim(),
          mqDeviceHeight: rootStyle.getPropertyValue("--rotunda-mq-device-height").trim(),
          mqResolution: rootStyle.getPropertyValue("--rotunda-mq-resolution").trim(),
          mqColor: rootStyle.getPropertyValue("--rotunda-mq-color").trim(),
        },
      },
      attributes: {
        rootScreenWidth: root.getAttribute("data-rotunda-screen-width"),
        rootScreenHeight: root.getAttribute("data-rotunda-screen-height"),
        bodyInnerWidth: body.getAttribute("data-rotunda-inner-width"),
        bodyInnerHeight: body.getAttribute("data-rotunda-inner-height"),
        rootByScreenWidth: doc.querySelector(`[data-rotunda-screen-width="${screenWidth}"]`) === root,
        rootByScreenHeight: doc.querySelector(`[data-rotunda-screen-height="${screenHeight}"]`) === root,
        bodyByInnerWidth: doc.querySelector(`[data-rotunda-inner-width="${innerWidth}"]`) === body,
        bodyByInnerHeight: doc.querySelector(`[data-rotunda-inner-height="${innerHeight}"]`) === body,
      },
      matchMedia: {
        widthExact: match(win, `(width: ${innerWidth}px)`),
        heightExact: match(win, `(height: ${innerHeight}px)`),
        deviceWidthExact: match(win, `(device-width: ${screenWidth}px)`),
        deviceHeightExact: match(win, `(device-height: ${screenHeight}px)`),
        resolutionExact: match(win, `(resolution: ${dpr}dppx)`),
        colorExact: match(win, `(color: ${colorComponents})`),
        orientationLandscape: match(win, "(orientation: landscape)"),
        orientationPortrait: match(win, "(orientation: portrait)"),
        colorGamutSRGB: match(win, "(color-gamut: srgb)"),
        colorGamutP3: match(win, "(color-gamut: p3)"),
        colorGamutRec2020: match(win, "(color-gamut: rec2020)"),
        dynamicRangeStandard: match(win, "(dynamic-range: standard)"),
        dynamicRangeHigh: match(win, "(dynamic-range: high)"),
        videoDynamicRangeStandard: match(win, "(video-dynamic-range: standard)"),
        videoDynamicRangeHigh: match(win, "(video-dynamic-range: high)"),
      },
      timezone: {
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
        offset: new Date().getTimezoneOffset(),
      },
    };
  };

  const workerSnapshot = await new Promise(resolve => {
    const code = `
      self.onmessage = () => {
        self.postMessage({
          hasWindow: typeof window !== "undefined",
          hasScreen: typeof screen !== "undefined",
          navigator: {
            userAgent: navigator.userAgent || "",
            platform: navigator.platform || "",
            hardwareConcurrency: navigator.hardwareConcurrency || 0,
            language: navigator.language || "",
            languages: Array.from(navigator.languages || [])
          },
          timezone: {
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
            offset: new Date().getTimezoneOffset()
          }
        });
      };
    `;
    const url = URL.createObjectURL(new Blob([code], { type: "application/javascript" }));
    const worker = new Worker(url);
    const timeout = setTimeout(() => {
      worker.terminate();
      URL.revokeObjectURL(url);
      resolve({ error: "worker timeout" });
    }, 5000);
    worker.onmessage = event => {
      clearTimeout(timeout);
      worker.terminate();
      URL.revokeObjectURL(url);
      resolve(event.data);
    };
    worker.onerror = event => {
      clearTimeout(timeout);
      worker.terminate();
      URL.revokeObjectURL(url);
      resolve({ error: String(event.message || event) });
    };
    worker.postMessage({});
  });

  const iframe = document.createElement("iframe");
  iframe.width = String(window.innerWidth);
  iframe.height = String(window.innerHeight);
  iframe.style.width = `${window.innerWidth}px`;
  iframe.style.height = `${window.innerHeight}px`;
  iframe.style.border = "0";
  iframe.style.display = "block";
  iframe.srcdoc = "<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>";
  document.body.appendChild(iframe);
  await new Promise(resolve => {
    iframe.onload = resolve;
    setTimeout(resolve, 1000);
  });

  return {
    top: collectWindow(window),
    iframe: collectWindow(iframe.contentWindow),
    worker: workerSnapshot,
  };
}"""


@contextmanager
def _probe_server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []
    body = PROBE_HTML.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return

            requests.append(
                {
                    "path": self.path,
                    "headers": {key: value for key, value in self.headers.items()},
                }
            )

            if self.path not in ("/probe", "/probe/"):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/probe", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_MISSING = object()


def _get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _assert_value(surface: dict[str, Any], path: tuple[str, ...], expected: Any, label: str) -> None:
    if expected is None:
        return

    actual = _get(surface, path)
    path_label = f"{label}.{'.'.join(path)}"
    assert actual is not _MISSING, f"{path_label} is missing"

    if isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=0.01), path_label
    else:
        assert actual == expected, path_label


def _assert_pixels(surface: dict[str, Any], path: tuple[str, ...], expected: int, label: str) -> None:
    actual = _get(surface, path)
    path_label = f"{label}.{'.'.join(path)}"
    assert actual is not _MISSING, f"{path_label} is missing"
    assert actual == pytest.approx(expected, abs=1), path_label


def _assert_true(surface: dict[str, Any], path: tuple[str, ...], label: str) -> None:
    actual = _get(surface, path)
    path_label = f"{label}.{'.'.join(path)}"
    assert actual is True, f"{path_label} expected True, got {actual!r}"


def _assert_profile_surface(profile: dict[str, Any], surface: dict[str, Any], label: str) -> None:
    screen = profile["screen"]
    window = profile["window"]
    navigator = profile["navigator"]

    for key in (
        "width",
        "height",
        "availWidth",
        "availHeight",
        "availLeft",
        "availTop",
        "colorDepth",
        "pixelDepth",
    ):
        _assert_value(surface, ("screen", key), screen.get(key), label)

    for key in (
        "innerWidth",
        "innerHeight",
        "outerWidth",
        "outerHeight",
        "screenX",
        "screenY",
        "devicePixelRatio",
    ):
        _assert_value(surface, ("window", key), window.get(key), label)

    _assert_value(surface, ("window", "screenLeft"), window.get("screenX"), label)
    _assert_value(surface, ("window", "screenTop"), window.get("screenY"), label)

    for key in (
        "userAgent",
        "appVersion",
        "platform",
        "oscpu",
        "hardwareConcurrency",
        "maxTouchPoints",
        "language",
        "languages",
        "product",
        "productSub",
        "cookieEnabled",
        "onLine",
        "doNotTrack",
        "globalPrivacyControl",
    ):
        _assert_value(surface, ("navigator", key), navigator.get(key), label)

    if timezone := profile.get("timezone"):
        _assert_value(surface, ("timezone", "timeZone"), timezone, label)

    inner_width = window["innerWidth"]
    inner_height = window["innerHeight"]
    screen_width = screen["width"]
    screen_height = screen["height"]

    for path in (
        ("documentElement", "clientWidth"),
        ("body", "clientWidth"),
        ("documentElement", "rect", "width"),
        ("body", "rect", "width"),
        ("css", "viewportProbe", "width"),
        ("css", "percentProbe", "width"),
    ):
        _assert_pixels(surface, path, inner_width, label)

    for path in (
        ("documentElement", "clientHeight"),
        ("body", "clientHeight"),
        ("documentElement", "rect", "height"),
        ("body", "rect", "height"),
        ("css", "viewportProbe", "height"),
        ("css", "percentProbe", "height"),
    ):
        _assert_pixels(surface, path, inner_height, label)

    if _get(surface, ("visualViewport", "width")) is not _MISSING:
        _assert_pixels(surface, ("visualViewport", "width"), inner_width, label)
        _assert_pixels(surface, ("visualViewport", "height"), inner_height, label)

    assert _get(surface, ("attributes", "rootScreenWidth")) == str(screen_width)
    assert _get(surface, ("attributes", "rootScreenHeight")) == str(screen_height)
    assert _get(surface, ("attributes", "bodyInnerWidth")) == str(inner_width)
    assert _get(surface, ("attributes", "bodyInnerHeight")) == str(inner_height)
    _assert_true(surface, ("attributes", "rootByScreenWidth"), label)
    _assert_true(surface, ("attributes", "rootByScreenHeight"), label)
    _assert_true(surface, ("attributes", "bodyByInnerWidth"), label)
    _assert_true(surface, ("attributes", "bodyByInnerHeight"), label)

    for key in ("mqWidth", "mqHeight", "mqDeviceWidth", "mqDeviceHeight", "mqResolution", "mqColor"):
        actual = _get(surface, ("css", "customProperties", key))
        assert actual == "yes", f"{label}.css.customProperties.{key} expected yes, got {actual!r}"

    for key in (
        "widthExact",
        "heightExact",
        "deviceWidthExact",
        "deviceHeightExact",
        "resolutionExact",
        "colorExact",
    ):
        _assert_true(surface, ("matchMedia", key), label)

    expected_orientation = "orientationLandscape" if inner_width >= inner_height else "orientationPortrait"
    _assert_true(surface, ("matchMedia", expected_orientation), label)

    if color_gamut := screen.get("colorGamut"):
        media_key = {
            "srgb": "colorGamutSRGB",
            "p3": "colorGamutP3",
            "rec2020": "colorGamutRec2020",
        }[color_gamut]
        _assert_true(surface, ("matchMedia", media_key), label)

    if dynamic_range := screen.get("dynamicRange"):
        media_key = {
            "standard": "dynamicRangeStandard",
            "high": "dynamicRangeHigh",
        }[dynamic_range]
        _assert_true(surface, ("matchMedia", media_key), label)

    if video_dynamic_range := screen.get("videoDynamicRange"):
        media_key = {
            "standard": "videoDynamicRangeStandard",
            "high": "videoDynamicRangeHigh",
        }[video_dynamic_range]
        _assert_true(surface, ("matchMedia", media_key), label)


def _assert_worker_surface(profile: dict[str, Any], worker: dict[str, Any]) -> None:
    assert worker.get("error") is None, worker.get("error")
    assert worker["hasWindow"] is False
    assert worker["hasScreen"] is False

    navigator = profile["navigator"]
    for key in ("userAgent", "platform", "hardwareConcurrency", "language", "languages"):
        _assert_value(worker, ("navigator", key), navigator.get(key), "worker")

    if timezone := profile.get("timezone"):
        _assert_value(worker, ("timezone", "timeZone"), timezone, "worker")


def _assert_request_headers(profile: dict[str, Any], requests: list[dict[str, Any]]) -> None:
    request = next((entry for entry in requests if entry["path"] in ("/probe", "/probe/")), None)
    assert request is not None, "probe request was not captured"

    headers = request["headers"]
    expected_user_agent = (
        profile.get("headers", {}).get("User-Agent")
        or profile.get("navigator", {}).get("userAgent")
    )
    if expected_user_agent:
        assert headers.get("User-Agent") == expected_user_agent

    expected_gpc = profile.get("navigator", {}).get("globalPrivacyControl")
    if expected_gpc is True:
        assert headers.get("Sec-GPC") == "1"
    elif expected_gpc is False:
        assert headers.get("Sec-GPC") != "1"

    expected_language = (
        profile.get("headers", {}).get("Accept-Language")
        or profile.get("locale", {}).get("all")
        or profile.get("navigator", {}).get("language")
    )
    if expected_language:
        assert headers.get("Accept-Language", "").startswith(expected_language.split(",", 1)[0])


async def test_global_launch_surfaces_match_runtime_fingerprint(pytestconfig: pytest.Config) -> None:
    if not pytestconfig.getoption("--integration"):
        pytest.skip("Surface probe integration test requires --integration.")

    executable_path = os.getenv("ROTUNDA_EXECUTABLE_PATH")
    if not executable_path:
        pytest.skip("Surface probe requires ROTUNDA_EXECUTABLE_PATH.")

    playwright_api = pytest.importorskip("playwright.async_api")
    async_playwright = playwright_api.async_playwright

    from rotunda.addons import DefaultAddons
    from rotunda.fingerprints import generate_fingerprint
    from rotunda.utils import launch_options, persistent_context_options

    fingerprint = generate_fingerprint(window=(1280, 800))
    launch = launch_options(
        config={"timezone": "America/New_York"},
        executable_path=executable_path,
        exclude_addons=[DefaultAddons.UBO],
        fingerprint=fingerprint,
        headless=True,
        humanize=False,
        i_know_what_im_doing=True,
        locale="en-US",
        env=dict(os.environ),
    )

    profile_path = Path(str(launch["env"]["ROTUNDA_CONFIG_PATH"]))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    launch = persistent_context_options(launch)
    launch["timeout"] = 60_000

    try:
        with _probe_server() as (probe_url, requests):
            with tempfile.TemporaryDirectory(prefix="rotunda-surface-probe-") as user_data_dir:
                async with async_playwright() as playwright:
                    context = await playwright.firefox.launch_persistent_context(
                        user_data_dir,
                        **launch,
                    )
                    try:
                        page = context.pages[0] if context.pages else await context.new_page()
                        await page.goto(probe_url, wait_until="domcontentloaded", timeout=30_000)
                        payload = await page.evaluate(SURFACE_PROBE_SCRIPT)
                    finally:
                        await context.close()

            _assert_request_headers(profile, requests)
            _assert_profile_surface(profile, payload["top"], "top")
            _assert_profile_surface(profile, payload["iframe"], "iframe")
            _assert_worker_surface(profile, payload["worker"])
    finally:
        profile_path.unlink(missing_ok=True)
