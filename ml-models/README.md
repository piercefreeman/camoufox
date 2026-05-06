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

The training script logs config, data counts, per-epoch `train/*`, `val/*`, and
`score/loss` metrics. `score/loss` is validation loss when a validation split
exists, otherwise training loss. Local `metrics.jsonl` and checkpoints are still
written; by default W&B also receives a model artifact containing `model.pt`,
`model-best.pt`, and `metrics.jsonl`. Use `--no-wandb-log-artifacts` to skip
artifact uploads, or `--wandb-mode offline` for local W&B logging.

Click runs also log post-training rollout diagnostics for validation examples:
real duration, simulated duration, sim/real duration ratio, duration error,
step counts, path lengths, and endpoint error. W&B receives a table plus
duration scatter and histogram charts under `click_rollout/*`. Use
`--wandb-click-rollout-examples 0` to disable this diagnostic. Use
`--click-duration-loss-weight` to add an explicit episode-duration loss when
click rollouts are spatially good but too fast or too slow.

Keyboard runs include an episode-duration loss and log validation rollout
diagnostics under `keyboard_rollout/*`: exact-match fraction, real/sim duration,
duration ratio, duration error, and step counts. With the default
`--keyboard-sequence-mode auto`, focused-text recordings train on raw derived
edits, while synthetic physical-key recordings train on the constrained
final-string path. For timing-focused training,
`--keyboard-min-final-length 2 --keyboard-min-duration-ms 1` removes single-key
zero-duration episodes that otherwise dominate the timing loss.

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

Keyboard generation uses constrained decoding by default: the model predicts
timing and action logits, while the decoder masks those logits to actions that
can still produce the requested final string. This keeps `textAfter` equal to
`--final-string` while allowing learned corrections/backspaces within
`--keyboard-structured-extra-steps`. `--keyboard-canonical-bias` controls how
strongly the decoder prefers the shortest valid edit path over a learned edit.
Use `--decode-mode canonical` for the older shortest-path behavior. To force
extra correction events while keeping the same guarantee, pass a typo rate such
as `--keyboard-typo-rate 0.08 --keyboard-max-typos 2`. The decoder samples
bounded correction events from
`--keyboard-typo-mode-weights replace=0.55,forward=0.30,backtrack=0.15`: replace
types a wrong key then repairs it, forward types one correct key plus bounded
extra wrong keys then backs up, and backtrack deletes bounded already-correct
text before retyping it. `--keyboard-typo-min-dt-ms` keeps correction actions
from collapsing into same-timestamp bursts. Pass `--decode-mode unconstrained`
to inspect the raw action logits. The generated rows are JSON objects with
cumulative `offsetMs`, per-step `dtMs`, the emitted action, and a `stepKind`
label for that timestep.

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
