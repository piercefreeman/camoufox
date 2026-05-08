#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import click
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "rotunda-150.0.1-beta.25"
DEFAULT_MOUSE_MODEL = ROOT / "bundle" / "runtime-models" / "mouse.safetensors"
DEFAULT_KEYBOARD_MODEL = ROOT / "bundle" / "runtime-models" / "keyboard.safetensors"
DEFAULT_OUTPUT_ROOT = ROOT / "Training" / "debug_media"
DEFAULT_TEXT = "rotunda models ship"


def _existing_executable(path: Path) -> Path | None:
    if path.is_file() and os.access(path, os.X_OK):
        return path
    return None


def find_executable(explicit_path: Path | None) -> Path:
    if explicit_path:
        resolved = explicit_path.expanduser().resolve()
        executable = _existing_executable(resolved)
        if executable:
            return executable
        raise click.ClickException(f"Rotunda executable is not executable: {resolved}")

    env_path = os.getenv("ROTUNDA_EXECUTABLE_PATH")
    if env_path:
        executable = _existing_executable(Path(env_path).expanduser().resolve())
        if executable:
            return executable
        raise click.ClickException(f"ROTUNDA_EXECUTABLE_PATH is not executable: {env_path}")

    patterns = [
        "obj-*/dist/Rotunda.app/Contents/MacOS/rotunda",
        "obj-*/dist/Rotunda.app/Contents/MacOS/Rotunda",
        "obj-*/dist/Nightly.app/Contents/MacOS/firefox",
        "obj-*/dist/Firefox Nightly.app/Contents/MacOS/firefox",
        "obj-*/dist/bin/rotunda-bin",
        "obj-*/dist/bin/rotunda",
        "obj-*/dist/bin/firefox",
    ]
    for pattern in patterns:
        for candidate in sorted(SOURCE_DIR.glob(pattern)):
            executable = _existing_executable(candidate)
            if executable:
                return executable.resolve()

    raise click.ClickException(
        "Could not find a built Rotunda executable. Run `make build` first or pass --executable-path."
    )


def write_demo_page(output_dir: Path) -> Path:
    page_path = output_dir / "runtime-model-demo.html"
    page_path.write_text(
        """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Rotunda Runtime Model Demo</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }
    body { margin: 0; background: #f4f7f9; color: #16212b; }
    main { min-height: 100vh; display: grid; place-items: center; padding: 32px; box-sizing: border-box; }
    .panel { width: min(760px, 100%); background: white; border: 1px solid #d8e0e6; border-radius: 8px; padding: 24px; box-shadow: 0 18px 60px rgb(25 40 55 / 12%); }
    h1 { margin: 0 0 18px; font-size: 24px; line-height: 1.2; }
    label { display: block; font-size: 13px; font-weight: 650; color: #4b5a66; margin-bottom: 8px; }
    textarea { width: 100%; min-height: 120px; box-sizing: border-box; resize: vertical; border: 1px solid #aab8c3; border-radius: 6px; padding: 12px; font: 16px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .row { display: flex; gap: 12px; align-items: center; margin-top: 16px; }
    button { border: 0; background: #175b9f; color: white; border-radius: 6px; padding: 10px 14px; font-weight: 700; cursor: pointer; }
    output { color: #39505f; font-size: 14px; }
    pre { height: 260px; overflow: auto; background: #101820; color: #d8f2ff; border-radius: 6px; padding: 12px; font-size: 12px; line-height: 1.4; white-space: pre-wrap; }
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Runtime Model Demo</h1>
      <label for="message">Text field</label>
      <textarea id="message" autocomplete="off" spellcheck="false"></textarea>
      <div class="row">
        <button id="submit" type="button">Submit</button>
        <output id="status">Waiting</output>
      </div>
      <pre id="log"></pre>
    </section>
  </main>
  <script>
    window.__rotundaEvents = [];
    const log = document.getElementById("log");
    const status = document.getElementById("status");
    const message = document.getElementById("message");
    const submit = document.getElementById("submit");

    function targetValue(event) {
      const target = event.target;
      if (target && typeof target.value === "string")
        return target.value;
      return undefined;
    }

    function record(event) {
      const entry = {
        type: event.type,
        ts: performance.now(),
        eventTimeStamp: event.timeStamp,
        x: Number.isFinite(event.clientX) ? event.clientX : null,
        y: Number.isFinite(event.clientY) ? event.clientY : null,
        button: event.button,
        buttons: event.buttons,
        key: event.key,
        code: event.code,
        data: event.data,
        inputType: event.inputType,
        value: targetValue(event)
      };
      window.__rotundaEvents.push(entry);
      const last = window.__rotundaEvents.slice(-28);
      log.textContent = last.map(item => JSON.stringify(item)).join("\\n");
    }

    for (const type of ["mousemove", "mousedown", "mouseup", "click"]) {
      window.addEventListener(type, record, true);
    }
    for (const type of ["keydown", "keyup", "beforeinput", "input", "compositionstart", "compositionupdate", "compositionend"]) {
      document.addEventListener(type, record, true);
    }

    submit.addEventListener("click", () => {
      status.textContent = `Submitted ${message.value.length} chars`;
    });
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return page_path


def summarize(events: list[dict[str, Any]], final_text: str) -> dict[str, Any]:
    mouse_events = [
        event
        for event in events
        if event.get("type") in {"mousemove", "mousedown", "mouseup", "click"}
    ]
    move_events = [event for event in events if event.get("type") == "mousemove"]
    input_events = [event for event in events if event.get("type") == "input"]
    key_events = [event for event in events if event.get("type") in {"keydown", "keyup"}]
    value_change_input_events: list[dict[str, Any]] = []
    last_value: str | None = None
    for event in input_events:
        value = event.get("value")
        if not isinstance(value, str) or value == last_value:
            continue
        value_change_input_events.append(event)
        last_value = value

    coords = {
        (round(event["x"], 2), round(event["y"], 2))
        for event in move_events
        if event.get("x") is not None and event.get("y") is not None
    }
    input_intervals = [
        round(value_change_input_events[index]["ts"] - value_change_input_events[index - 1]["ts"], 3)
        for index in range(1, len(value_change_input_events))
    ]
    mouse_duration = 0.0
    if len(mouse_events) >= 2:
        mouse_duration = round(mouse_events[-1]["ts"] - mouse_events[0]["ts"], 3)

    return {
        "final_text": final_text,
        "event_count": len(events),
        "mouse": {
            "event_count": len(mouse_events),
            "mousemove_count": len(move_events),
            "unique_mousemove_coords": len(coords),
            "duration_ms": mouse_duration,
            "first": mouse_events[0] if mouse_events else None,
            "last": mouse_events[-1] if mouse_events else None,
        },
        "keyboard": {
            "input_event_count": len(input_events),
            "value_change_input_count": len(value_change_input_events),
            "key_event_count": len(key_events),
            "input_interval_ms": input_intervals,
            "input_interval_median_ms": round(statistics.median(input_intervals), 3)
            if input_intervals
            else None,
        },
    }


@click.command()
@click.option("--executable-path", type=click.Path(path_type=Path), default=None)
@click.option("--mouse-model", type=click.Path(path_type=Path), default=DEFAULT_MOUSE_MODEL)
@click.option("--keyboard-model", type=click.Path(path_type=Path), default=DEFAULT_KEYBOARD_MODEL)
@click.option("--text", default=DEFAULT_TEXT, show_default=True)
@click.option("--output-root", type=click.Path(path_type=Path), default=DEFAULT_OUTPUT_ROOT)
@click.option("--headless", is_flag=True, help="Run without opening a visible browser window.")
@click.option("--keep-open", is_flag=True, help="Leave the browser open until Enter is pressed.")
@click.option("--pause-seconds", type=float, default=2.0, show_default=True)
def main(
    executable_path: Path | None,
    mouse_model: Path,
    keyboard_model: Path,
    text: str,
    output_root: Path,
    headless: bool,
    keep_open: bool,
    pause_seconds: float,
) -> None:
    executable = find_executable(executable_path)
    mouse_model = mouse_model.expanduser().resolve()
    keyboard_model = keyboard_model.expanduser().resolve()
    for model_path in [mouse_model, keyboard_model]:
        if not model_path.is_file():
            raise click.ClickException(f"Model file does not exist: {model_path}")

    output_dir = output_root.expanduser().resolve() / f"runtime-browser-demo-{time.strftime('%Y%m%d-%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    page_path = write_demo_page(output_dir)
    config_path = output_dir / "rotunda-runtime-model-profile.json"
    config = {
        "debug": True,
        "humanize": {
            "enabled": True,
            "mouseModelPath": str(mouse_model),
            "keyboardModelPath": str(keyboard_model),
        },
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    env = {**os.environ, "ROTUNDA_CONFIG_PATH": str(config_path)}
    click.echo(f"Launching {executable}")
    click.echo(f"Writing demo artifacts to {output_dir}")

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(
            executable_path=str(executable),
            headless=headless,
            env=env,
        )
        page = browser.new_page(viewport={"width": 1024, "height": 760})
        page.goto(page_path.as_uri())

        field = page.locator("#message")
        button = page.locator("#submit")
        field_box = field.bounding_box()
        button_box = button.bounding_box()
        if not field_box or not button_box:
            raise click.ClickException("Demo page controls did not produce bounding boxes")

        page.mouse.move(72, 96)
        page.mouse.click(field_box["x"] + 48, field_box["y"] + 36)
        page.keyboard.insert_text(text)
        page.mouse.move(96, 120)
        page.mouse.click(button_box["x"] + button_box["width"] / 2, button_box["y"] + button_box["height"] / 2)

        if keep_open:
            click.echo("Browser is open. Press Enter to close it.")
            input()
        elif pause_seconds > 0:
            page.wait_for_timeout(int(pause_seconds * 1000))

        events = page.evaluate("window.__rotundaEvents")
        final_text = field.input_value()
        screenshot_path = output_dir / "runtime-model-demo.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()

    summary = summarize(events, final_text)
    report = {
        "executable": str(executable),
        "config": str(config_path),
        "page": str(page_path),
        "screenshot": str(screenshot_path),
        "models": {
            "mouse": str(mouse_model),
            "keyboard": str(keyboard_model),
        },
        "summary": summary,
        "events": events,
    }
    report_path = output_dir / "runtime-model-demo-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if final_text != text:
        raise click.ClickException(f"Final text mismatch: expected {text!r}, got {final_text!r}")
    if summary["mouse"]["mousemove_count"] < 2:
        raise click.ClickException("Mouse demo did not emit enough mousemove events")
    if summary["keyboard"]["value_change_input_count"] < 1:
        raise click.ClickException("Keyboard demo did not emit value-changing input events")

    click.echo(json.dumps({"summary": summary, "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
