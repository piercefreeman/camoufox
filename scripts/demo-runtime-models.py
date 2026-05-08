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
DEFAULT_PARAGRAPH = (
    "Rotunda runtime models should make browser input look continuous: "
    "the pointer plans a path to each target, then the keyboard model types "
    "this longer paragraph as a sequence of timed edits."
)

BUTTONS = {
    "preview": "#preview",
    "approve": "#approve",
    "flag": "#flag",
    "archive": "#archive",
    "submit": "#submit",
    "reset": "#reset",
}


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
    body { margin: 0; background: #f1f5f7; color: #16212b; }
    main { min-height: 100vh; padding: 28px; box-sizing: border-box; }
    .workspace { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 18px; align-items: start; }
    .panel, .rail { background: white; border: 1px solid #d8e0e6; border-radius: 8px; box-shadow: 0 18px 60px rgb(25 40 55 / 10%); }
    .panel { padding: 24px; }
    .rail { padding: 18px; position: sticky; top: 18px; }
    h1 { margin: 0 0 18px; font-size: 24px; line-height: 1.2; }
    h2 { margin: 0 0 12px; font-size: 15px; line-height: 1.25; color: #334957; }
    .field { margin-top: 18px; }
    label { display: block; font-size: 13px; font-weight: 650; color: #4b5a66; margin-bottom: 8px; }
    textarea { width: 100%; box-sizing: border-box; resize: vertical; border: 1px solid #aab8c3; border-radius: 6px; padding: 12px; font: 16px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; outline-color: #175b9f; background: #fbfdfe; }
    #message { min-height: 96px; }
    #paragraph { min-height: 210px; }
    .button-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    button { border: 0; background: #175b9f; color: white; border-radius: 6px; padding: 10px 12px; min-height: 40px; font-weight: 700; cursor: pointer; }
    button.secondary { background: #3e596b; }
    button.warning { background: #9b4d16; }
    button.danger { background: #9b2635; }
    output { display: block; color: #39505f; font-size: 14px; min-height: 22px; }
    .preview { min-height: 86px; border: 1px solid #d8e0e6; background: #f7fafb; border-radius: 6px; padding: 12px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; }
    pre { height: 320px; overflow: auto; background: #101820; color: #d8f2ff; border-radius: 6px; padding: 12px; font-size: 12px; line-height: 1.4; white-space: pre-wrap; }
    @media (max-width: 900px) { .workspace { grid-template-columns: 1fr; } .rail { position: static; } }
  </style>
</head>
<body>
  <main>
    <div class="workspace">
      <section class="panel">
        <h1>Runtime Model Demo</h1>
        <div class="field">
          <label for="message">Short text field</label>
          <textarea id="message" autocomplete="off" spellcheck="false"></textarea>
        </div>
        <div class="field">
          <label for="paragraph">Long paragraph field</label>
          <textarea id="paragraph" autocomplete="off" spellcheck="false"></textarea>
        </div>
      </section>

      <aside class="rail">
        <h2>Actions</h2>
        <output id="status">Waiting for CLI command</output>
        <div class="button-grid">
          <button id="preview" type="button" class="secondary" data-action="preview">Preview</button>
          <button id="approve" type="button" data-action="approve">Approve</button>
          <button id="flag" type="button" class="warning" data-action="flag">Flag</button>
          <button id="archive" type="button" class="secondary" data-action="archive">Archive</button>
          <button id="submit" type="button" data-action="submit">Submit</button>
          <button id="reset" type="button" class="danger" data-action="reset">Reset</button>
        </div>
        <h2 style="margin-top: 18px;">Preview</h2>
        <div id="previewPane" class="preview"></div>
        <h2 style="margin-top: 18px;">Event log</h2>
        <pre id="log"></pre>
      </aside>
    </div>
  </main>
  <script>
    window.__rotundaEvents = [];
    window.__rotundaActions = [];
    const log = document.getElementById("log");
    const status = document.getElementById("status");
    const message = document.getElementById("message");
    const paragraph = document.getElementById("paragraph");
    const previewPane = document.getElementById("previewPane");

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
        targetId: event.target && event.target.id || null,
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

    for (const button of document.querySelectorAll("button[data-action]")) {
      button.addEventListener("click", () => {
        const action = button.dataset.action;
        const details = {
          action,
          ts: performance.now(),
          shortLength: message.value.length,
          paragraphLength: paragraph.value.length
        };
        if (action === "preview") {
          previewPane.textContent = [message.value, paragraph.value].filter(Boolean).join("\\n\\n");
          status.textContent = `Previewed ${details.shortLength + details.paragraphLength} chars`;
        } else if (action === "reset") {
          message.value = "";
          paragraph.value = "";
          previewPane.textContent = "";
          status.textContent = "Cleared both fields";
        } else {
          status.textContent = `${button.textContent} clicked after ${details.shortLength + details.paragraphLength} chars`;
        }
        window.__rotundaActions.push(details);
      });
    }

    window.__rotundaSnapshot = () => ({
      message: message.value,
      paragraph: paragraph.value,
      status: status.textContent,
      preview: previewPane.textContent,
      actionCount: window.__rotundaActions.length
    });
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return page_path


def summarize(
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    mouse_events = [
        event
        for event in events
        if event.get("type") in {"mousemove", "mousedown", "mouseup", "click"}
    ]
    move_events = [event for event in events if event.get("type") == "mousemove"]
    input_events = [event for event in events if event.get("type") == "input"]
    key_events = [event for event in events if event.get("type") in {"keydown", "keyup"}]
    button_clicks = [
        event
        for event in mouse_events
        if event.get("type") == "click" and event.get("targetId") in BUTTONS
    ]
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
        "snapshot": snapshot,
        "event_count": len(events),
        "mouse": {
            "event_count": len(mouse_events),
            "mousemove_count": len(move_events),
            "unique_mousemove_coords": len(coords),
            "button_click_count": len(button_clicks),
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
        "actions": {
            "count": len(actions),
            "items": actions,
        },
    }


def click_selector(page: Any, selector: str, label: str) -> None:
    locator = page.locator(selector)
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    if not box:
        raise click.ClickException(f"Demo target has no bounding box: {label}")
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(72, 96)
    page.mouse.click(x, y)


def type_into(page: Any, selector: str, text: str, label: str) -> None:
    click_selector(page, selector, label)
    page.keyboard.insert_text(text)


def run_scripted_sequence(page: Any, short_text: str, paragraph_text: str) -> None:
    type_into(page, "#message", short_text, "short text field")
    type_into(page, "#paragraph", paragraph_text, "long paragraph field")
    for button in ["preview", "approve", "flag", "archive", "submit"]:
        click_selector(page, BUTTONS[button], button)


def print_commands() -> None:
    click.echo(
        "\nCommands:\n"
        "  [1] run                         type both fields, then click preview/approve/flag/archive/submit\n"
        "  [2] short custom text           click the short field and type custom text\n"
        "  [3] paragraph custom text       click the paragraph field and type custom text\n"
        "  [4] click preview               click one button: preview approve flag archive submit reset\n"
        "  [5] screenshot optional-name    save a screenshot in the output directory\n"
        "  [6] summary                     print current field values and event counts\n"
        "  [7] events optional-count       print the last recorded browser events\n"
        "  [8] help                        show this menu\n"
        "  [9] quit                        write the report and close the browser\n"
    )


def browser_snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate("window.__rotundaSnapshot()")


def command_loop(
    page: Any,
    output_dir: Path,
    short_text: str,
    paragraph_text: str,
) -> None:
    print_commands()
    while True:
        try:
            raw = input("runtime-demo [1-9]> ").strip()
        except EOFError:
            click.echo()
            return
        if not raw:
            continue

        command, _, rest = raw.partition(" ")
        command = command.lower()
        rest = rest.strip()
        numeric_commands = {
            "1": "run",
            "2": "short",
            "3": "paragraph",
            "4": "click",
            "5": "screenshot",
            "6": "summary",
            "7": "events",
            "8": "help",
            "9": "quit",
        }
        command = numeric_commands.get(command, command)

        if command in {"q", "quit", "exit"}:
            return
        if command in {"h", "help", "?"}:
            print_commands()
            continue
        if command == "run":
            run_scripted_sequence(page, short_text, paragraph_text)
            click.echo("Ran the default two-field and button sequence.")
            continue
        if command in {"short", "first"}:
            type_into(page, "#message", rest or short_text, "short text field")
            continue
        if command in {"paragraph", "para", "second"}:
            type_into(page, "#paragraph", rest or paragraph_text, "long paragraph field")
            continue
        if command == "click":
            button = rest.lower()
            if button not in BUTTONS:
                click.echo(f"Unknown button {button!r}. Choices: {', '.join(BUTTONS)}")
                continue
            click_selector(page, BUTTONS[button], button)
            continue
        if command == "screenshot":
            name = rest or f"runtime-model-demo-{time.strftime('%H%M%S')}.png"
            if not name.endswith(".png"):
                name += ".png"
            screenshot_path = output_dir / name
            page.screenshot(path=str(screenshot_path), full_page=True)
            click.echo(f"Wrote {screenshot_path}")
            continue
        if command == "summary":
            events = page.evaluate("window.__rotundaEvents")
            actions = page.evaluate("window.__rotundaActions")
            click.echo(json.dumps(summarize(events, actions, browser_snapshot(page)), indent=2))
            continue
        if command == "events":
            try:
                count = int(rest) if rest else 12
            except ValueError:
                click.echo("events expects an integer count.")
                continue
            events = page.evaluate("window.__rotundaEvents")
            click.echo(json.dumps(events[-count:], indent=2))
            continue

        click.echo(f"Unknown command {command!r}. Type help for commands.")


@click.command()
@click.option("--executable-path", type=click.Path(path_type=Path), default=None)
@click.option("--mouse-model", type=click.Path(path_type=Path), default=DEFAULT_MOUSE_MODEL)
@click.option("--keyboard-model", type=click.Path(path_type=Path), default=DEFAULT_KEYBOARD_MODEL)
@click.option("--text", default=DEFAULT_TEXT, show_default=True)
@click.option("--paragraph-text", default=DEFAULT_PARAGRAPH, show_default=True)
@click.option("--output-root", type=click.Path(path_type=Path), default=DEFAULT_OUTPUT_ROOT)
@click.option("--headless", is_flag=True, help="Run without opening a visible browser window.")
@click.option("--keep-open", is_flag=True, help="Leave the browser open until Enter is pressed.")
@click.option("--pause-seconds", type=float, default=2.0, show_default=True)
@click.option("--scripted-start", is_flag=True, help="Run the default sequence before the command loop.")
@click.option("--no-interactive", is_flag=True, help="Run once and exit after the scripted sequence.")
@click.option(
    "--use-bundled-models",
    is_flag=True,
    help="Do not put model paths in the profile; let the browser resolve shipped runtime-models.",
)
def main(
    executable_path: Path | None,
    mouse_model: Path,
    keyboard_model: Path,
    text: str,
    paragraph_text: str,
    output_root: Path,
    headless: bool,
    keep_open: bool,
    pause_seconds: float,
    scripted_start: bool,
    no_interactive: bool,
    use_bundled_models: bool,
) -> None:
    executable = find_executable(executable_path)
    mouse_model = mouse_model.expanduser().resolve()
    keyboard_model = keyboard_model.expanduser().resolve()
    if not use_bundled_models:
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
        },
    }
    if not use_bundled_models:
        config["humanize"]["mouseModelPath"] = str(mouse_model)
        config["humanize"]["keyboardModelPath"] = str(keyboard_model)
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

        if scripted_start or no_interactive:
            run_scripted_sequence(page, text, paragraph_text)

        if no_interactive:
            if pause_seconds > 0:
                page.wait_for_timeout(int(pause_seconds * 1000))
        else:
            command_loop(page, output_dir, text, paragraph_text)

        if keep_open and no_interactive:
            click.echo("Browser is open. Press Enter to close it.")
            input()

        events = page.evaluate("window.__rotundaEvents")
        actions = page.evaluate("window.__rotundaActions")
        snapshot = browser_snapshot(page)
        screenshot_path = output_dir / "runtime-model-demo.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()

    summary = summarize(events, actions, snapshot)
    report = {
        "executable": str(executable),
        "config": str(config_path),
        "page": str(page_path),
        "screenshot": str(screenshot_path),
        "models": {
            "source": "bundled" if use_bundled_models else "profile",
            "mouse": None if use_bundled_models else str(mouse_model),
            "keyboard": None if use_bundled_models else str(keyboard_model),
        },
        "summary": summary,
        "events": events,
        "actions": actions,
    }
    report_path = output_dir / "runtime-model-demo-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if no_interactive and snapshot.get("message") != text:
        raise click.ClickException(
            f"Final short text mismatch: expected {text!r}, got {snapshot.get('message')!r}"
        )
    if no_interactive and snapshot.get("paragraph") != paragraph_text:
        raise click.ClickException(
            "Final paragraph text mismatch: "
            f"expected {paragraph_text!r}, got {snapshot.get('paragraph')!r}"
        )
    if no_interactive and summary["mouse"]["mousemove_count"] < 2:
        raise click.ClickException("Mouse demo did not emit enough mousemove events")
    if no_interactive and summary["keyboard"]["value_change_input_count"] < 1:
        raise click.ClickException("Keyboard demo did not emit value-changing input events")

    click.echo(json.dumps({"summary": summary, "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
