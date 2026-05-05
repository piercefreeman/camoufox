# Fingerprint Debugging Notes

Last updated: 2026-05-04 PDT

This file captures practical debugging notes from investigating why
`https://demo.fingerprint.com/playground` reports `developer_tools: true`.

## Local Build

Use the local arm64 macOS build path instead of guess-and-checking in CI:

```sh
source upstream.sh
BUILD_TARGET=macos,arm64 make build
```

The built executable is:

```text
camoufox-150.0.1-beta.25/obj-aarch64-apple-darwin/dist/Camoufox.app/Contents/MacOS/camoufox
```

Launch through the Python/Camoufox path when validating fingerprint behavior.
Directly running the executable can hit profile/config mismatches and is not the
same path that users exercise through Playwright.

## Patch Verification

Before spending time on a Firefox build, run:

```sh
uv run scripts/verify_firefox_patches.py
```

Two important patch-stack rules:

- Patches are applied in sorted order, except roverfox patches are moved last by
  the helper.
- If a patch modifies a file created by another patch, the modifier must sort
  after the creator. For example, a follow-up patch touching
  `js/src/vm/CamoufoxVMAccessLog.cpp` must sort after
  `vm-access-logging.patch`.

The verifier now allows follow-up patches to touch patch-created files, but the
apply phase still proves whether ordering is correct.

## Current Fingerprint Finding

The first confirmed leak was impossible window geometry.

Before the window-dimension propagation patch, page JS saw values like:

```text
window.outerWidth === window.innerWidth
window.outerHeight === window.innerHeight
```

That is suspicious for a headed desktop browser because browser chrome should
make at least the height differ. The root cause was that the global
`MaskConfig::Profile().getWindow()` fallback was not reliably available in the
content process, while the screen dimensions survived because they were stored
through `RoverfoxStorageManager`.

The fix path is to propagate window dimensions through per-context storage too:

- Add a self-destructing WebIDL setter, `window.setWindowDimensions(...)`.
- Call it from the context init script before page scripts run.
- Have `nsGlobalWindowInner` getters read the per-context values before falling
  back to `MaskConfig`.

After this patch, page JS sees the intended geometry, for example:

```json
{
  "outerHeight": 1080,
  "innerHeight": 1052,
  "outerMinusInnerH": 28,
  "outerWidth": 1920,
  "innerWidth": 1920,
  "screenX": 0,
  "screenY": 0
}
```

Fingerprint still reports `developer_tools: true`, so geometry propagation was a
real leak but not the whole detection signal.

## VM Access Logger

The VM logger is controlled by environment variables:

```sh
CAMOUFOX_VM_ACCESS_LOG=1
CAMOUFOX_VM_ACCESS_FILTER='fingerprint'
CAMOUFOX_VM_ACCESS_OBJECT_FILTER='Window'
CAMOUFOX_VM_ACCESS_SYMBOLS=1
CAMOUFOX_VM_ACCESS_MAX_ARGS=16
CAMOUFOX_VM_ACCESS_MAX_STRING=256
```

Under Playwright, browser stderr is not reliably visible from the Python launch
path. Prefer logging directly to a file:

```sh
CAMOUFOX_VM_ACCESS_LOG=1 \
CAMOUFOX_VM_ACCESS_LOG_FILE=/tmp/camoufox-fp-vm.log \
PYTHONPATH=pythonlib \
.venv/bin/python scripts_or_inline_repro.py
```

Useful filters:

- Use `CAMOUFOX_VM_ACCESS_OBJECT_FILTER=Window` for global/window probes.
- Use `CAMOUFOX_VM_ACCESS_OBJECT_FILTER=Navigator` for navigator probes.
- Use no object filter for a full run, but expect very large logs.
- Script URL filters can be brittle because the Fingerprint script URL changes
  and minified code may be loaded through different bundle URLs.

The logger records:

- Property gets and `in` checks.
- `getOwnPropertyDescriptor`.
- `ownKeys`.
- Native and scripted calls, including callee name, `this` class, and arguments.

## Repro Harness

Use a shared BrowserForge fingerprint for browser launch and context creation.
This avoids creating mismatched launch/context identities:

```python
import os
from pathlib import Path

from camoufox import Camoufox, NewContext
from camoufox.fingerprints import generate_fingerprint

exe = Path(
    "camoufox-150.0.1-beta.25/"
    "obj-aarch64-apple-darwin/dist/Camoufox.app/Contents/MacOS/camoufox"
).resolve()

fp = generate_fingerprint(debug=True)

with Camoufox(
    headless=False,
    executable_path=str(exe),
    fingerprint=fp,
    ff_version=150,
    i_know_what_im_doing=True,
    env=os.environ.copy(),
    config={"showcursor": False},
) as browser:
    context = NewContext(browser, fingerprint=fp, ff_version="150", debug=True)
    page = context.new_page()
    page.goto("https://demo.fingerprint.com/playground", wait_until="domcontentloaded")
    page.wait_for_function(
        "document.body && /developer_tools|Developer Tools/.test(document.body.innerText)"
    )
```

## Noise To Ignore

The playground regularly emits these console errors in our runs:

- `Cookie "__cf_bm" has been rejected for invalid domain.`
- CORS failures to `metric.fingerprinthub.com`.

These happen alongside successful Fingerprint API responses and are not the
primary `developer_tools` signal.

## Next Suspects

After fixing outer/inner propagation, the remaining `developer_tools: true`
signal likely comes from another runtime observable. The next pass should use the
file-backed VM logger to compare the exact Fingerprint script probes against the
values exposed by the rebuilt browser.

High-value areas to inspect:

- Stack formatting and `Error.stack` behavior.
- `mozInnerScreenX/Y` versus `screenX/Y` and realistic browser chrome offsets.
- Any extension/devtool globals or missing globals expected in stock Firefox.
- Canvas/WebGL/audio calls and argument values.
- Descriptor shape of spoofed properties after self-destructing init setters.
