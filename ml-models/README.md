# Rotunda Model Training

This package contains the raw pipeline to train models that simulate user actions: mouse movements and keyboard clicks.

## Install

The model code ships as its own `rotunda_models` Python package so PyTorch,
Pillow, and optional W&B dependencies stay out of the main `rotunda` package.

Run commands through `uv` without a manual install:

```bash
cd ml-models
uv run rotunda-models --help
```

From the repository root, point `uv` at the subpackage:

```bash
uv run --project ml-models rotunda-models --help
```

The exposed console scripts are:

- `rotunda-models`
- `rotunda-models-sweep`
- `rotunda-models-render-debug-videos`

```bash
python3 -m pip install -e ".[wandb]"
```

## What The Models Learn

Mouse clicks:

- Input: current pointer coordinate and destination click coordinate.
- Output: a variable-length sequence of `offsetMs`, `dtMs`, `x`, `y`, and action
  labels. The terminal action is a click.
- Training data: "motivated" click episodes that start after pointer rest and
  reach a click within two seconds.

Keyboard actions:

- Input: optional initial string plus final string.
- Output: a variable-length sequence of `offsetMs`, `dtMs`, and key actions.
- Training data: focused accessibility text snapshots when available. Training
  selects one focused element identity, derives edit actions from that element's
  value changes, and avoids mixing text from multiple accessibility IDs. If a
  recording has no focused text values, the trainer falls back to synthetic
  final strings sampled from recorded physical-key deltas.

## Commands

Inspect available training data:

```bash
rotunda-models inspect recordings
```

Train the click model:

```bash
rotunda-models train-clicks recordings --epochs 25
```

Train the keyboard model:

```bash
rotunda-models train-keyboard recordings --epochs 25
```

Train with validation-based early stopping:

```bash
rotunda-models train-clicks recordings \
  --epochs 150 --early-stopping-patience 12

rotunda-models train-keyboard recordings \
  --epochs 100 --early-stopping-patience 6 \
  --synthetic-per-sequence 16 --hidden-size 128
```

Each run writes:

- `Training/runs/<kind>-<timestamp>/model.pt`
- `Training/runs/<kind>-<timestamp>/model-best.pt`
- `Training/runs/<kind>-<timestamp>/metrics.jsonl`

The console logs show the main training stages: loading recordings, building
episodes, splitting data, initializing the model, training epochs, and saving
the checkpoint.

## Weights & Biases Tracking

W&B is an optional dependency. Install and log in before using it:

```bash
python3 -m pip install -e ".[wandb]"
wandb login
```

Log a single training run to W&B:

```bash
rotunda-models train-clicks recordings \
  --epochs 25 --wandb --wandb-project cadence-models

rotunda-models train-keyboard recordings \
  --epochs 25 --wandb --wandb-project cadence-models
```

Runs still write local checkpoints and `metrics.jsonl`. W&B also logs training
metrics, optional model artifacts, and rollout diagnostics when validation data
is available.

Keep W&B logs local:

```bash
rotunda-models train-clicks recordings \
  --epochs 25 --wandb --wandb-mode offline
```

Skip model artifact uploads:

```bash
rotunda-models train-keyboard recordings \
  --epochs 25 --wandb --no-wandb-log-artifacts
```

Disable rollout diagnostics:

```bash
rotunda-models train-clicks recordings \
  --epochs 25 --wandb --wandb-click-rollout-examples 0

rotunda-models train-keyboard recordings \
  --epochs 25 --wandb --wandb-keyboard-rollout-examples 0
```

Filter out very short keyboard examples for timing-focused training:

```bash
rotunda-models train-keyboard recordings \
  --epochs 25 --keyboard-min-final-length 2 --keyboard-min-duration-ms 1
```

## Generation

Generate a click trajectory:

```bash
rotunda-models generate-click \
  --checkpoint Training/runs/clicks-YYYYMMDD-HHMMSS/model.pt \
  --current-x 200 --current-y 400 \
  --dst-x 800 --dst-y 500
```

Click generation uses endpoint guidance by default because the destination is a
known input. The GRU predicts timing and movement increments while the decoder
keeps progress monotonic toward the destination and emits the final click at the
target. Pass `--no-endpoint-guidance` to inspect the raw free-running decoder.

Generate keyboard actions:

```bash
rotunda-models generate-keyboard \
  --checkpoint Training/runs/keyboard-YYYYMMDD-HHMMSS/model.pt \
  --final-string "hello"
```

By default, generated keyboard output reaches the requested final string.

Use the shortest valid edit path:

```bash
rotunda-models generate-keyboard \
  --checkpoint Training/runs/keyboard-YYYYMMDD-HHMMSS/model.pt \
  --final-string "hello" \
  --decode-mode canonical
```

Add bounded typo and correction events:

```bash
rotunda-models generate-keyboard \
  --checkpoint Training/runs/keyboard-YYYYMMDD-HHMMSS/model.pt \
  --final-string "hello" \
  --keyboard-typo-rate 0.08 --keyboard-max-typos 2
```

Inspect unconstrained model output:

```bash
rotunda-models generate-keyboard \
  --checkpoint Training/runs/keyboard-YYYYMMDD-HHMMSS/model.pt \
  --final-string "hello" \
  --decode-mode unconstrained
```

Generated rows are JSON objects with `offsetMs`, `dtMs`, the emitted action, and
a `stepKind` label.

## Debug Videos

Render validation examples with real and simulated actions overlaid:

```bash
rotunda-models-render-debug-videos
```

Outputs:

- `Training/debug_media/mouse_val_overlay.mp4`
- `Training/debug_media/keyboard_val_overlay.mp4`

## W&B Sweeps

Run a W&B random sweep over architecture, learning rate, filtering, and
loss-weight parameters:

```bash
rotunda-models-sweep recordings \
  --task all --trials 8 --epochs 20 --wandb-project cadence-models
```

Run just one model family:

```bash
rotunda-models-sweep recordings \
  --task keyboard --trials 12 --epochs 25 --wandb-project cadence-models
rotunda-models-sweep recordings \
  --task clicks --trials 12 --epochs 40 --wandb-project cadence-models
```

Create the sweep in W&B without launching a local agent:

```bash
rotunda-models-sweep recordings \
  --task keyboard --trials 12 --epochs 25 \
  --wandb-project cadence-models --create-only
```

Preview W&B sweep configs without contacting W&B:

```bash
rotunda-models-sweep recordings --task keyboard --trials 3 --dry-run
```

Each sweep writes:

- `Training/sweeps/wandb-sweep-<timestamp>/meta.json`
- `Training/sweeps/wandb-sweep-<timestamp>/<task>-sweep.json`
- `Training/sweeps/wandb-sweep-<timestamp>/input_snapshot/`
- Per-run local checkpoints under `Training/sweeps/wandb-sweep-<timestamp>/<task>/runs/`

Sweep run metrics, best-run comparisons, and artifacts are tracked in W&B. The
default sweep objective is `score/loss` with `minimize`.

Inputs are snapshotted by default so every trial sees the same data even if the
recorder is still appending to `recordings`. Pass `--no-snapshot-inputs` to train
directly from the provided paths.

To override the default search ranges, pass `--space custom-space.json`. The
JSON can contain `clicks` and/or `keyboard` objects keyed by CLI parameter name:

```json
{
  "keyboard": {
    "dt_loss_weight": {"type": "loguniform", "min": 4.0, "max": 32.0},
    "synthetic_per_sequence": {"values": [8, 16, 32]}
  }
}
```
