from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_REGISTRY = REPO_ROOT / "additions" / "juggler" / "TargetRegistry.js"


def _update_viewport_size_body() -> str:
    source = TARGET_REGISTRY.read_text(encoding="utf-8")
    start = source.index("  async updateViewportSize() {")
    end = source.index("\n  setEmulatedMedia", start)
    return source[start:end]


def test_viewport_resize_uses_rendered_browser_bounds() -> None:
    body = _update_viewport_size_body()

    assert "const currentBrowserRect = this._linkedBrowser.getBoundingClientRect();" in body
    assert (
        "this._window.resizeBy(width - currentBrowserRect.width, height - currentBrowserRect.height);"
        in body
    )
    assert "this._window.innerWidth" not in body
    assert "this._window.innerHeight" not in body
