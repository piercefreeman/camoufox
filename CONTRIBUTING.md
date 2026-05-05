# Contributing to Rotunda

Thanks for your interest in contributing! Here's how to get started.

## Ways to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected behavior, and actual behavior.
- **Feature requests** — Open an issue describing the use case and why it's useful.
- **Code contributions** — Fork the repo, make your changes, and open a pull request.
- **Documentation** — Fixes and improvements to docs are always welcome.

## Development Setup

See README.md for general setup. For iterative development with frequent rebuilds, install [ccache](https://ccache.dev/) to cache compiled objects:

```bash
# macOS
brew install ccache

# Linux
sudo apt install ccache   # Debian/Ubuntu
sudo dnf install ccache   # Fedora
```

ccache is already enabled in the build config. A cold build takes the usual ~40 minutes, but subsequent rebuilds drop to ~5 minutes for small changes.

## Pull Request Rules

1. Each pull request must be associated with a Github issue
2. Keep commits focused — one logical change per commit.
3. Open a PR with a clear description of what you changed and why.
4. All pull requests must pass both the **build-tester** and **service-tester** test suites before merging.

## Testing Requirements

**Both test suites are required for every PR.** They test different layers of the stack and catch different classes of bugs — passing one does not substitute for the other.

### build-tester

Tests the **raw binary** in isolation, bypassing the Python package entirely. Fingerprints are injected manually via `generate_context_fingerprint` + `addInitScript` (per-context mode) and via the `ROTUNDA_CONFIG` environment variable (global mode). It also validates that injected values actually appear in the page via match result checks.

**Run this when you change:** browser patches, Firefox source modifications, WebGL/canvas/audio spoofing, WebRTC IP handling, or anything in the C++/JS browser layer.

```bash
export ROTUNDA_EXECUTABLE_PATH=/path/to/rotunda-binary
uv run --group dev --group playwright-tests --locked pytest \
  --integration \
  __tests__/build-tester/
```

See [`__tests__/build-tester/README.md`](__tests__/build-tester/README.md) for full details.

---

### service-tester

Tests the **full stack** — the binary and the Python package together — using only the public `AsyncNewContext` API. Fingerprints are generated entirely by rotunda/browserforge with no manual injection. Real proxies are required; the WebRTC IP and timezone are auto-derived from each proxy's exit IP. This is a black-box trust test: if it fails, the fix belongs in the Python package, not in the test.

**Run this when you change:** `pythonlib/` (fingerprint generation, `AsyncNewContext`, `NewContext`), proxy handling, or any behaviour that affects how the Python package interacts with the binary.

```bash
# Add proxies (one per line, format: user:pass@domain:port)
$EDITOR __tests__/service-tester/proxies.txt

# Run the pytest-gated integration wrapper
uv run --group dev --group playwright-tests --locked pytest \
  --integration \
  __tests__/service-tester/
```

See [`__tests__/service-tester/README.md`](__tests__/service-tester/README.md) for full details.

---

### Key differences

| | build-tester | service-tester |
|---|---|---|
| Entry point | Raw binary path | `pip install rotunda` |
| Fingerprint injection | Manual | Via `AsyncNewContext` API |
| Global mode (`ROTUNDA_CONFIG`) | ✓ | ✗ |
| Match result validation | ✓ | ✗ |
| Proxy required | ✗ | ✓ |
| Profiles | 8 (6 per-context + 2 global) | 6 (per-context) |
| Fix target on failure | Browser source | Python package |

## Reporting Issues

Please search existing issues before opening a new one. Include:
- Rotunda version
- OS and Python version
- A minimal reproducible example

## Questions

For usage questions, check the [documentation](https://rotunda.com) first. For anything else, open an issue.
