# Camoufox

This repository is a fork of the original [daijro/camoufox](https://github.com/daijro/camoufox).

The upstream project has the broader product docs and Python usage docs. This fork is focused on local browser development: patching Firefox, rebuilding quickly, and packaging local macOS builds.

- Original project: [github.com/daijro/camoufox](https://github.com/daijro/camoufox)
- Upstream docs: [camoufox.com](https://camoufox.com)
- Python package code in this repo: [pythonlib/README.md](pythonlib/README.md)

## Getting Started on macOS

This is the shortest path from a fresh clone to a local macOS build.

> [!IMPORTANT]
> On macOS, use `make mozbootstrap`.
> `make bootstrap` is the Linux helper target and will try `apt`, `dnf`, or `pacman`.
> On a fresh checkout, start with `make setup`.
> Apple Silicon is the default target in this repo: if `BUILD_TARGET` is unset, [`scripts/patch.py`](scripts/patch.py) falls back to `macos,arm64`.

### 1. Install the small amount you need up front

`make setup` needs `aria2c`, and incremental builds are much better with `ccache`.

```bash
xcode-select --install
brew install aria2 python ccache
```

Notes:

- `ccache` is optional, but [`assets/base.mozconfig`](assets/base.mozconfig) is already configured to use it if installed.
- `make mozbootstrap` handles the heavier Mozilla toolchain setup in `~/.mozbuild`.

### 2. Clone the fork

```bash
git clone https://github.com/piercefreeman/camoufox.git
cd camoufox
```

### 3. Pick your target architecture

Apple Silicon defaults to `macos,arm64`, so you can skip this unless you need Intel.

```bash
export BUILD_TARGET=macos,x86_64
```

If you switch targets later, rerun:

```bash
make set-target
```

### 4. Download and prepare the Firefox source tree

```bash
make setup
```

Use this before your first `make mozbootstrap` or `make build`.

This does four things:

1. Downloads the Firefox source tarball for the version declared in [`upstream.sh`](upstream.sh).
2. Extracts it into `camoufox-<version>-<release>/`.
3. Copies this repo's `additions/` and `settings/` into that tree.
4. Initializes the extracted source as a local git repo tagged at `unpatched`.

### 5. Bootstrap the Mozilla build environment

```bash
make mozbootstrap
```

This runs `./mach bootstrap` inside the generated `camoufox-*` source tree and sets up the Mozilla toolchain under `~/.mozbuild`.

### 6. Build Camoufox

```bash
make build
```

On the first run, this will:

- apply the repo's patches from `patches/`
- generate the active `mozconfig`
- add the required Rust target with `rustup`
- compile the browser

Cold builds are slow. With `ccache` installed, rebuilds are much faster.

### 7. Run the result

```bash
make run
```

Useful output locations:

- Apple Silicon build: `camoufox-*/obj-aarch64-apple-darwin/dist/Camoufox.app`
- Intel build: `camoufox-*/obj-x86_64-apple-darwin/dist/Camoufox.app`

## When You Need To Rebuild

You only need `make build` when you change browser-side code or bundled browser data.

Rebuild required:

- `patches/`
- `additions/`
- `settings/`
- anything under the extracted `camoufox-*/` Firefox source tree that affects the browser binary or bundled resources

Rebuild not required:

- `pythonlib/camoufox/fingerprints.py`
- `pythonlib/camoufox/utils.py`
- `pythonlib/camoufox/sync_api.py`
- `pythonlib/camoufox/async_api.py`
- other Python-only wrapper code

Those Python files run at launch time on the client machine. If you only changed fingerprint generation logic, rerun your Python entrypoint against an existing Camoufox binary.

If you changed both sides, the split is simple:

- rebuild the browser so binary-side changes are present
- rerun the Python code so the new launcher/context logic is used

## Launching The Python Fingerprint Flow

The easiest local-dev path is:

1. Build the browser once with `make build`.
2. Point the Python package at that local executable.
3. Launch through `NewContext()`, which is where the per-context fingerprint is generated.

From the repo root:

```bash
uv sync --project pythonlib --group dev
source upstream.sh
export CAMOUFOX_EXECUTABLE_PATH="$PWD/camoufox-$version-$release/obj-aarch64-apple-darwin/dist/Camoufox.app/Contents/MacOS/camoufox"
uv run --project pythonlib --group dev python -m camoufox test
```

On Intel macOS, replace `obj-aarch64-apple-darwin` with `obj-x86_64-apple-darwin`.

If startup looks stuck, rerun with `--debug` to print browser-launch and fingerprint-generation logs:

```bash
uv run --project pythonlib --group dev python -m camoufox test --debug
```

`camoufox test` now opens a controllable Playwright inspector session using the active fingerprint flow:

- BrowserForge generates the Firefox skeleton
- Camoufox constrains it to the real macOS host
- `NewContext()` applies the per-context overrides

If you want the Python CLI and default launcher path to pick up your local build without passing `executable_path`, package and install it into the local Camoufox cache:

```bash
make package-macos arch=arm64
./scripts/install-local-build.sh
uv run --project pythonlib --group dev python -m camoufox test
```

That is only needed if you want the Python package to resolve the browser through its normal installed-browser lookup. For fast iteration on `pythonlib/`, pointing `CAMOUFOX_EXECUTABLE_PATH` at the repo build is simpler.

## Persona Stability Check

If you want to verify that saved persona files fully capture the browser identity over time, run the persona consistency script from the repo root:

```bash
uv sync --project pythonlib --group dev
source upstream.sh
export CAMOUFOX_EXECUTABLE_PATH="$PWD/camoufox-$version-$release/obj-aarch64-apple-darwin/dist/Camoufox.app/Contents/MacOS/camoufox"
uv run --project pythonlib --group dev python example/persona_consistency.py
```

What it does:

- generates 5 persona JSON files under `.tmp/personas/`
- launches each persona against CreepJS and extracts its `FP ID`
- closes all browsers, relaunches from the saved persona files only, and checks the IDs again
- exits non-zero if any persona drifts between runs

If you want to watch the browsers during the check:

```bash
uv run --project pythonlib --group dev python example/persona_consistency.py --headful
```

## Fast Path

If you just want the commands without the explanation:

```bash
xcode-select --install
brew install aria2 python ccache
git clone https://github.com/piercefreeman/camoufox.git
cd camoufox
make setup
make mozbootstrap
make build
make run
```

For an Intel Mac, add this before `make setup`:

```bash
export BUILD_TARGET=macos,x86_64
```

## Packaging a macOS Artifact

If you want a distributable zip after the build:

```bash
make package-macos arch=arm64
```

For Intel:

```bash
make package-macos arch=x86_64
```

That writes a file like `camoufox-<version>-<release>-mac.<arch>.zip` in the repo root.

If you prefer the wrapper that builds and moves artifacts into `dist/`, use:

```bash
python3 multibuild.py --target macos --arch arm64
```

After that, [`scripts/install-local-build.sh`](scripts/install-local-build.sh) can install the latest zip from `dist/` into the local Camoufox cache.

## Docker Fallback

If native building on your M1 turns out to be flaky or too slow, this repo already has a containerized build path.

That path is not a separate implementation: it follows the same cross-build model used in [`.github/workflows/build.yml`](.github/workflows/build.yml), where macOS artifacts are built on Ubuntu.

Build the image:

```bash
docker build -t camoufox-builder .
```

Build a macOS Apple Silicon artifact into `dist/`:

```bash
mkdir -p dist
docker run --rm \
  -v "$(pwd)/dist:/app/dist" \
  camoufox-builder \
  --target macos \
  --arch arm64
```

If you want the container to reuse an existing Mozilla toolchain cache:

```bash
docker run --rm \
  -v "$HOME/.mozbuild:/root/.mozbuild" \
  -v "$(pwd)/dist:/app/dist" \
  camoufox-builder \
  --target macos \
  --arch arm64
```

Notes:

- Docker is a fallback, not the only supported path.
- The artifact will be written to `dist/` as `camoufox-<version>-<release>-mac.arm64.zip`.
- If you want to mirror CI more closely, inspect [`.github/workflows/build.yml`](.github/workflows/build.yml).

## How This Repo Is Organized

- `patches/` contains the Firefox patch stack applied by [`scripts/patch.py`](scripts/patch.py).
- `additions/` contains files copied directly into the extracted Firefox source tree before patching.
- `settings/` contains runtime defaults bundled into the build.
- `camoufox-<version>-<release>/` is generated by `make setup` and is disposable local build state, not the source of truth for long-term changes.

If you edit files under `camoufox-*`, expect them to be overwritten by `make dir`, `make clean`, or `make distclean` unless you turn those edits back into a patch.

## Testing

Two test suites live in this repo:

- [`build-tester/README.md`](build-tester/README.md) for raw browser binary validation
- [`service-tester/README.md`](service-tester/README.md) for end-to-end Python package validation

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the expectations for when to run each one.
