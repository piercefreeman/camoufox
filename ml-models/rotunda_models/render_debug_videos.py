#!/usr/bin/env python3
"""Render validation-set debug videos for cadence models."""

from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont

from . import train
from .constants import (
    BACKSPACE_POS,
    DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS,
    KEY_BACKSPACE,
    KEY_LAYOUT,
    KEY_STOP,
)

REAL_COLOR = (37, 99, 235)
SIM_COLOR = (234, 88, 12)
TEXT_COLOR = (31, 41, 55)
MUTED_COLOR = (107, 114, 128)
BG_COLOR = (248, 250, 252)
GRID_COLOR = (226, 232, 240)
KEY_BG = (255, 255, 255)
KEY_BORDER = (148, 163, 184)


class VideoWriter:
    def __init__(self, path: Path, width: int, height: int, fps: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-vcodec",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, image: Image.Image) -> None:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))
        assert self.proc.stdin is not None
        self.proc.stdin.write(image.tobytes())

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        code = self.proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {code}")


def load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


FONT = load_font(18)
SMALL_FONT = load_font(14)
BIG_FONT = load_font(26)


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fill=TEXT_COLOR, font=FONT) -> None:
    draw.text(xy, text, fill=fill, font=font)


def line_points(rows: list[dict], t_ms: float) -> list[tuple[float, float]]:
    return [(row["x"], row["y"]) for row in rows if row["offsetMs"] <= t_ms]


def current_row(rows: list[dict], t_ms: float) -> dict | None:
    current = None
    for row in rows:
        if row["offsetMs"] <= t_ms:
            current = row
        else:
            break
    return current


def mouse_rows(episode: train.MouseEpisode) -> list[dict]:
    offset = 0.0
    rows = []
    for step in episode.steps:
        offset += step.dt_ms
        rows.append(
            {
                "offsetMs": offset,
                "dtMs": step.dt_ms,
                "x": step.x,
                "y": step.y,
                "action": step.action,
            }
        )
    return rows


def simulate_mouse_rows(
    checkpoint: dict,
    model: train.MouseTrajectoryGRU,
    episode: train.MouseEpisode,
    device: torch.device,
    max_steps: int,
    click_threshold: float,
    min_dt_ms: float,
) -> list[dict]:
    return train.simulate_mouse_click_rows(
        model=model,
        episode=episode,
        coordinate_scale=float(checkpoint["coordinate_scale"]),
        position_frame=checkpoint.get("position_frame", "screen_delta"),
        actions=checkpoint["actions"],
        device=device,
        max_steps=max_steps,
        click_threshold=click_threshold,
        min_dt_ms=min_dt_ms,
    )


def load_mouse_val(checkpoint: dict) -> list[train.MouseEpisode]:
    config = checkpoint["training_config"]
    paths = train.discover_recording_paths(config["inputs"])
    episodes = train.extract_mouse_episodes(
        paths,
        rest_ms=int(config.get("rest_ms", 150)),
        max_duration_ms=int(config.get("max_duration_ms", 2000)),
        min_distance=float(config.get("min_distance", 8.0)),
    )
    _, val = train.split_items(episodes, float(config.get("val_fraction", 0.15)), int(config.get("seed", 13)))
    return val


def select_mouse_examples(episodes: list[train.MouseEpisode], count: int) -> list[train.MouseEpisode]:
    def duration(episode: train.MouseEpisode) -> float:
        return sum(step.dt_ms for step in episode.steps)

    eligible = [episode for episode in episodes if 80 <= duration(episode) <= 2000]
    pool = eligible or episodes
    return sorted(pool, key=lambda episode: math.hypot(episode.dst_x - episode.start_x, episode.dst_y - episode.start_y), reverse=True)[:count]


def transform_points(points: list[tuple[float, float]], rect: tuple[int, int, int, int]):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)
    pad_x = span_x * 0.12
    pad_y = span_y * 0.12
    min_x -= pad_x
    max_x += pad_x
    min_y -= pad_y
    max_y += pad_y
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    def project(point: tuple[float, float]) -> tuple[float, float]:
        x = left + ((point[0] - min_x) / max(1.0, max_x - min_x)) * width
        y = top + ((point[1] - min_y) / max(1.0, max_y - min_y)) * height
        return x, y

    return project


def draw_polyline(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], color: tuple[int, int, int], width: int = 4) -> None:
    if len(points) >= 2:
        draw.line(points, fill=color, width=width, joint="curve")
    for point in points[-1:]:
        x, y = point
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)


def render_mouse_frame(
    episode_index: int,
    total_examples: int,
    t_ms: float,
    real: list[dict],
    sim: list[dict],
    width: int,
    height: int,
) -> Image.Image:
    image = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 76), fill=(241, 245, 249))
    draw_text(draw, (28, 18), f"Mouse validation example {episode_index}/{total_examples}", font=BIG_FONT)
    draw_text(draw, (28, 50), f"t={t_ms:0.0f}ms   real=blue   simulated=orange", fill=MUTED_COLOR, font=SMALL_FONT)

    plot = (64, 108, width - 64, height - 72)
    draw.rectangle(plot, fill=(255, 255, 255), outline=GRID_COLOR, width=2)
    all_points = [(row["x"], row["y"]) for row in real + sim]
    project = transform_points(all_points, plot)
    real_points = [project(point) for point in line_points(real, t_ms)]
    sim_points = [project(point) for point in line_points(sim, t_ms)]
    draw_polyline(draw, real_points, REAL_COLOR)
    draw_polyline(draw, sim_points, SIM_COLOR)

    start = project((real[0]["x"], real[0]["y"]))
    dst = project((real[-1]["x"], real[-1]["y"]))
    draw.ellipse((start[0] - 8, start[1] - 8, start[0] + 8, start[1] + 8), outline=TEXT_COLOR, width=3)
    draw.rectangle((dst[0] - 9, dst[1] - 9, dst[0] + 9, dst[1] + 9), outline=(22, 101, 52), width=3)
    draw_text(draw, (start[0] + 10, start[1] - 8), "start", fill=MUTED_COLOR, font=SMALL_FONT)
    draw_text(draw, (dst[0] + 10, dst[1] - 8), "dst", fill=(22, 101, 52), font=SMALL_FONT)

    real_current = current_row(real, t_ms)
    sim_current = current_row(sim, t_ms)
    if real_current and "click" in real_current["action"]:
        x, y = project((real_current["x"], real_current["y"]))
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), outline=REAL_COLOR, width=4)
    if sim_current and "click" in sim_current["action"]:
        x, y = project((sim_current["x"], sim_current["y"]))
        draw.ellipse((x - 26, y - 26, x + 26, y + 26), outline=SIM_COLOR, width=4)

    real_action = real_current["action"] if real_current else "pending"
    sim_action = sim_current["action"] if sim_current else "pending"
    draw_text(draw, (64, height - 46), f"real action: {real_action}", fill=REAL_COLOR, font=FONT)
    draw_text(draw, (width // 2, height - 46), f"sim action: {sim_action}", fill=SIM_COLOR, font=FONT)
    return image


def render_mouse_video(args: argparse.Namespace) -> Path:
    device = torch.device(args.device)
    checkpoint = train.load_checkpoint(args.click_checkpoint, device)
    model = train.MouseTrajectoryGRU(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    val = load_mouse_val(checkpoint)
    examples = select_mouse_examples(val, args.examples)
    output = args.output_dir / "mouse_val_overlay.mp4"
    writer = VideoWriter(output, args.width, args.height, args.fps)
    try:
        for index, episode in enumerate(examples, 1):
            real = mouse_rows(episode)
            sim = simulate_mouse_rows(
                checkpoint,
                model,
                episode,
                device,
                max_steps=max(12, min(args.click_max_steps, len(real))),
                click_threshold=args.click_threshold,
                min_dt_ms=args.min_dt_ms,
            )
            duration_ms = max(real[-1]["offsetMs"], sim[-1]["offsetMs"], 500.0) + args.end_hold_ms
            frame_count = max(1, math.ceil((duration_ms / 1000.0) * args.fps))
            for frame in range(frame_count):
                t_ms = (frame / args.fps) * 1000.0
                writer.write(render_mouse_frame(index, len(examples), t_ms, real, sim, args.width, args.height))
    finally:
        writer.close()
    return output


def apply_key_action(text: list[str], action: str) -> None:
    if action == KEY_BACKSPACE:
        if text:
            text.pop()
    elif action != KEY_STOP:
        text.append(action)


def keyboard_rows(episode: train.KeyboardEpisode) -> list[dict]:
    offset = 0.0
    text: list[str] = list(episode.initial_string)
    rows = []
    for step in episode.steps:
        offset += step.dt_ms
        apply_key_action(text, step.action)
        rows.append(
            {
                "offsetMs": offset,
                "dtMs": step.dt_ms,
                "action": step.action,
                "textAfter": "".join(text),
            }
        )
    return rows


def simulate_keyboard_rows(
    checkpoint: dict,
    model: train.KeyboardActionGRU,
    initial_string: str,
    final_string: str,
    device: torch.device,
    max_steps: int,
    decode_mode: str,
    sample: bool,
    temperature: float,
    structured_extra_steps: int,
    canonical_bias: float,
    typo_rate: float,
    max_typos: int,
    typo_seed: int,
    typo_mode_weights: str,
    max_typo_chars: int,
    max_backtrack_chars: int,
    typo_min_dt_ms: float,
) -> list[dict]:
    return train.decode_keyboard_rows(
        checkpoint=checkpoint,
        model=model,
        initial_string=initial_string,
        final_string=final_string,
        device=device,
        max_steps=max_steps,
        decode_mode=decode_mode,
        sample=sample,
        temperature=temperature,
        structured_extra_steps=structured_extra_steps,
        canonical_bias=canonical_bias,
        typo_rate=typo_rate,
        max_typos=max_typos,
        typo_seed=typo_seed,
        typo_mode_weights=typo_mode_weights,
        max_typo_chars=max_typo_chars,
        max_backtrack_chars=max_backtrack_chars,
        typo_min_dt_ms=typo_min_dt_ms,
    )


def load_keyboard_val(checkpoint: dict) -> list[train.KeyboardEpisode]:
    config = checkpoint["training_config"]
    paths = train.discover_recording_paths(config["inputs"])
    if config.get("keyboard_source") == "focused_text":
        episodes, _ = train.extract_focused_text_keyboard_episodes(
            paths,
            gap_ms=int(config.get("gap_ms", 1000)),
            accessibility_id=str(config.get("keyboard_accessibility_id", "auto")),
            max_snapshot_edit_actions=int(config.get("keyboard_max_snapshot_edit_actions", 12)),
        )
    else:
        episodes = train.extract_keyboard_episodes(
            paths,
            gap_ms=int(config.get("gap_ms", 1000)),
            synthetic_per_sequence=int(config.get("synthetic_per_sequence", 4)),
            include_repeats=bool(config.get("include_repeats", False)),
            tolerance=float(config.get("geometry_tolerance", 0.05)),
            seed=int(config.get("seed", 13)),
        )
    _, val = train.split_items(episodes, float(config.get("val_fraction", 0.15)), int(config.get("seed", 13)))
    return val


def clean_text(text: str) -> str:
    return text.replace("\n", "<ret>")


def select_keyboard_examples(episodes: list[train.KeyboardEpisode], count: int, max_duration_ms: float) -> list[train.KeyboardEpisode]:
    def duration(episode: train.KeyboardEpisode) -> float:
        return sum(step.dt_ms for step in episode.steps)

    eligible = [
        episode
        for episode in episodes
        if 3 <= len(episode.final_string) <= 18
        and "\n" not in episode.final_string
        and duration(episode) <= max_duration_ms
    ]
    pool = eligible or episodes
    return sorted(pool, key=lambda episode: (len(episode.final_string), sum(step.dt_ms for step in episode.steps)), reverse=True)[:count]


def keyboard_geometry(rect: tuple[int, int, int, int]):
    centers = {key.token: (key.x, key.y) for key in KEY_LAYOUT}
    centers[KEY_BACKSPACE] = BACKSPACE_POS
    min_x = -0.6
    max_x = 14.6
    min_y = -0.6
    max_y = 4.8
    left, top, right, bottom = rect
    scale = min((right - left) / (max_x - min_x), (bottom - top) / (max_y - min_y))
    x_offset = left + ((right - left) - scale * (max_x - min_x)) / 2
    y_offset = top + ((bottom - top) - scale * (max_y - min_y)) / 2

    def project(x: float, y: float) -> tuple[float, float]:
        return x_offset + (x - min_x) * scale, y_offset + (y - min_y) * scale

    return centers, project, scale


def key_label(token: str) -> str:
    if token == " ":
        return "space"
    if token == "\n":
        return "ret"
    if token == KEY_BACKSPACE:
        return "backspace"
    return token


def draw_keyboard(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    real_action: str | None,
    sim_action: str | None,
) -> None:
    centers, project, scale = keyboard_geometry(rect)
    ordered_tokens = [key.token for key in KEY_LAYOUT] + [KEY_BACKSPACE]
    for token in ordered_tokens:
        x, y = centers[token]
        cx, cy = project(x, y)
        key_w = scale * (2.1 if token in {" ", KEY_BACKSPACE} else 0.82)
        key_h = scale * 0.72
        fill = KEY_BG
        outline = KEY_BORDER
        width = 2
        if token == real_action and token == sim_action:
            fill = (220, 252, 231)
            outline = (22, 163, 74)
            width = 4
        elif token == real_action:
            fill = (219, 234, 254)
            outline = REAL_COLOR
            width = 4
        elif token == sim_action:
            fill = (255, 237, 213)
            outline = SIM_COLOR
            width = 4
        draw.rounded_rectangle((cx - key_w / 2, cy - key_h / 2, cx + key_w / 2, cy + key_h / 2), radius=6, fill=fill, outline=outline, width=width)
        label = key_label(token)
        bbox = draw.textbbox((0, 0), label, font=SMALL_FONT)
        draw.text((cx - (bbox[2] - bbox[0]) / 2, cy - (bbox[3] - bbox[1]) / 2), label, fill=TEXT_COLOR, font=SMALL_FONT)


def recent_action(rows: list[dict], t_ms: float, window_ms: float = 140.0) -> str | None:
    row = current_row(rows, t_ms)
    if row and 0 <= t_ms - row["offsetMs"] <= window_ms:
        return row["action"]
    return None


def render_keyboard_frame(
    episode_index: int,
    total_examples: int,
    t_ms: float,
    final_string: str,
    real: list[dict],
    sim: list[dict],
    width: int,
    height: int,
) -> Image.Image:
    image = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 82), fill=(241, 245, 249))
    draw_text(draw, (28, 16), f"Keyboard validation example {episode_index}/{total_examples}", font=BIG_FONT)
    draw_text(draw, (28, 52), f"t={t_ms:0.0f}ms   real=blue   simulated=orange   target=\"{clean_text(final_string)}\"", fill=MUTED_COLOR, font=SMALL_FONT)

    real_current = current_row(real, t_ms)
    sim_current = current_row(sim, t_ms)
    draw_keyboard(
        draw,
        (56, 112, width - 56, height - 190),
        recent_action(real, t_ms),
        recent_action(sim, t_ms),
    )

    real_text = clean_text(real_current["textAfter"]) if real_current else ""
    sim_text = clean_text(sim_current["textAfter"]) if sim_current else ""
    real_action = real_current["action"] if real_current else "pending"
    sim_action = sim_current["action"] if sim_current else "pending"
    sim_kind = sim_current.get("stepKind") if sim_current else None
    sim_label = f"{key_label(sim_action)} ({sim_kind})" if sim_kind and sim_kind not in {"target", "model", "sampled"} else key_label(sim_action)
    draw.rounded_rectangle((56, height - 154, width - 56, height - 100), radius=8, fill=(255, 255, 255), outline=GRID_COLOR, width=2)
    draw.rounded_rectangle((56, height - 84, width - 56, height - 30), radius=8, fill=(255, 255, 255), outline=GRID_COLOR, width=2)
    draw_text(draw, (76, height - 142), f"real action: {key_label(real_action)}", fill=REAL_COLOR, font=FONT)
    draw_text(draw, (330, height - 142), f"text: {real_text[-80:]}", fill=TEXT_COLOR, font=FONT)
    draw_text(draw, (76, height - 72), f"sim action: {sim_label}", fill=SIM_COLOR, font=FONT)
    draw_text(draw, (330, height - 72), f"text: {sim_text[-80:]}", fill=TEXT_COLOR, font=FONT)
    return image


def render_keyboard_video(args: argparse.Namespace) -> Path:
    device = torch.device(args.device)
    checkpoint = train.load_checkpoint(args.keyboard_checkpoint, device)
    model = train.KeyboardActionGRU(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    val = load_keyboard_val(checkpoint)
    examples = select_keyboard_examples(val, args.examples, args.max_keyboard_example_ms)
    output = args.output_dir / "keyboard_val_overlay.mp4"
    writer = VideoWriter(output, args.width, args.height, args.fps)
    try:
        for index, episode in enumerate(examples, 1):
            real = keyboard_rows(episode)
            sim = simulate_keyboard_rows(
                checkpoint,
                model,
                episode.initial_string,
                episode.final_string,
                device,
                max_steps=max(
                    args.keyboard_max_steps,
                    len(episode.steps) + 4,
                    len(train.terminal_edit_actions(episode.initial_string, episode.final_string))
                    + args.keyboard_structured_extra_steps
                    + (2 * args.keyboard_max_typos * max(1, args.keyboard_max_typo_chars, args.keyboard_max_backtrack_chars)),
                ),
                decode_mode=args.keyboard_decode_mode,
                sample=args.keyboard_sample,
                temperature=args.keyboard_temperature,
                structured_extra_steps=args.keyboard_structured_extra_steps,
                canonical_bias=args.keyboard_canonical_bias,
                typo_rate=args.keyboard_typo_rate,
                max_typos=args.keyboard_max_typos,
                typo_seed=args.keyboard_typo_seed + index - 1,
                typo_mode_weights=args.keyboard_typo_mode_weights,
                max_typo_chars=args.keyboard_max_typo_chars,
                max_backtrack_chars=args.keyboard_max_backtrack_chars,
                typo_min_dt_ms=args.keyboard_typo_min_dt_ms,
            )
            duration_ms = max(real[-1]["offsetMs"], sim[-1]["offsetMs"] if sim else 0.0, 500.0) + args.end_hold_ms
            frame_count = max(1, math.ceil((duration_ms / 1000.0) * args.fps))
            for frame in range(frame_count):
                t_ms = (frame / args.fps) * 1000.0
                writer.write(render_keyboard_frame(index, len(examples), t_ms, episode.final_string, real, sim, args.width, args.height))
    finally:
        writer.close()
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--click-checkpoint", type=Path, default=Path("Training/runs/clicks-20260504-123229/model-best.pt"))
    parser.add_argument("--keyboard-checkpoint", type=Path, default=Path("Training/runs/keyboard-20260504-123059/model-best.pt"))
    parser.add_argument("--output-dir", type=Path, default=Path("Training/debug_media"))
    parser.add_argument("--examples", type=int, default=4)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--end-hold-ms", type=float, default=500.0)
    parser.add_argument("--click-max-steps", type=int, default=80)
    parser.add_argument("--click-threshold", type=float, default=0.98)
    parser.add_argument("--min-dt-ms", type=float, default=4.0)
    parser.add_argument("--keyboard-max-steps", type=int, default=80)
    parser.add_argument("--keyboard-decode-mode", choices=["constrained", "canonical", "unconstrained"], default="constrained")
    parser.add_argument("--keyboard-sample", action="store_true")
    parser.add_argument("--keyboard-temperature", type=float, default=1.0)
    parser.add_argument("--keyboard-structured-extra-steps", type=int, default=6)
    parser.add_argument("--keyboard-canonical-bias", type=float, default=1.5)
    parser.add_argument("--keyboard-typo-rate", type=float, default=0.0)
    parser.add_argument("--keyboard-max-typos", type=int, default=2)
    parser.add_argument("--keyboard-typo-seed", type=int, default=13)
    parser.add_argument("--keyboard-typo-mode-weights", default=DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS)
    parser.add_argument("--keyboard-max-typo-chars", type=int, default=3)
    parser.add_argument("--keyboard-max-backtrack-chars", type=int, default=2)
    parser.add_argument("--keyboard-typo-min-dt-ms", type=float, default=20.0)
    parser.add_argument("--max-keyboard-example-ms", type=float, default=3500.0)
    parser.add_argument("--only", choices=["all", "mouse", "keyboard"], default="all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outputs = []
    if args.only in {"all", "mouse"}:
        outputs.append(render_mouse_video(args))
    if args.only in {"all", "keyboard"}:
        outputs.append(render_keyboard_video(args))
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
