# Camoufox Tests

Ensures that Playwright functionality is not broken.

---

This directory is based on the original Playwright-Python [tests](https://github.com/microsoft/playwright-python/tree/main/tests).

It has been modified to skip tests that use the following features:

- Injecting JavaScript into the page or writing to DOM. Camoufox's `page.evaluate` only supports reading values, not executing within the page context.
- Overriding the User-Agent.
- Any tests specific to Chromium or Webkit.

---

# Usage

### Setting up the environment

`cd` to this directory and sync the local `uv` environment:

```bash
uv sync --locked
uv run python -m playwright install firefox
```

### Running the tests

Run the Playwright async suite directly through `uv`:

```bash
CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin uv run --locked pytest --integration --headless async/
```

For a headful run:

```bash
CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin uv run --locked pytest --integration async/
```

Or through the repo `Makefile`:

```bash
make tests headful=true
```

---
