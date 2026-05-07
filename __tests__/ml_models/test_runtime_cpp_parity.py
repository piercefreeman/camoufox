from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
import torch
from rotunda_models.constants import (
    CHAR_EOS,
    CHAR_PAD,
    CHAR_SEP,
    CHAR_UNK,
    KEY_BACKSPACE,
    KEY_STOP,
    MOUSE_ACTIONS,
)
from rotunda_models.keyboard_logic import (
    constrained_keyboard_action,
    keyboard_next_char,
)
from rotunda_models.models.keyboard import KeyboardActionGRU
from rotunda_models.models.mouse import MouseTrajectoryGRU
from rotunda_models.runtime_export import export_runtime_checkpoint
from rotunda_models.utils import log_to_dt, screen_position_from_goal_relative

APPROX = {"rel": 1e-4, "abs": 1e-5}


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def runtime_probe(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("No C++ compiler is available for runtime parity probe.")

    binary = tmp_path_factory.mktemp("runtime-probe") / "runtime_probe"
    runtime_dir = repo_root / "additions" / "rotundacfg"
    fixture_dir = repo_root / "__tests__" / "fixtures" / "cpp"
    command = [
        compiler,
        "-std=c++17",
        "-O0",
        "-I",
        str(fixture_dir),
        "-I",
        str(runtime_dir),
        str(runtime_dir / "RuntimeWeights.cpp"),
        str(runtime_dir / "MouseRuntime.cpp"),
        str(runtime_dir / "KeyboardRuntime.cpp"),
        str(fixture_dir / "runtime_probe.cpp"),
        "-o",
        str(binary),
    ]
    subprocess.run(command, cwd=repo_root, check=True, text=True, capture_output=True)
    return binary


def _copy_deterministic_weights(model: torch.nn.Module, *, seed_offset: float = 0.0) -> None:
    with torch.no_grad():
        for index, parameter in enumerate(model.parameters()):
            values = torch.linspace(
                -0.07 + seed_offset,
                0.09 + seed_offset,
                parameter.numel(),
                dtype=parameter.dtype,
            ).reshape(parameter.shape)
            parameter.copy_(values + (index * 0.003))


def _export_mouse_checkpoint(tmp_path: Path) -> tuple[Path, MouseTrajectoryGRU]:
    model_config = {
        "condition_dim": 7,
        "previous_dim": 3 + len(MOUSE_ACTIONS) + 1,
        "hidden_size": 6,
        "action_count": len(MOUSE_ACTIONS),
        "layers": 1,
        "dropout": 0.0,
    }
    model = MouseTrajectoryGRU(**model_config)
    _copy_deterministic_weights(model)
    with torch.no_grad():
        model.pos_head.weight.zero_()
        model.pos_head.bias.copy_(torch.tensor([0.24, 0.015]))
        model.action_head.weight.zero_()
        model.action_head.bias.copy_(torch.tensor([4.0, -4.0, -4.0, -4.0, -4.0]))
    model.eval()

    checkpoint_path = tmp_path / "mouse.pt"
    runtime_path = tmp_path / "mouse.safetensors"
    torch.save(
        {
            "kind": "mouse_click_gru",
            "model_config": model_config,
            "actions": MOUSE_ACTIONS,
            "coordinate_scale": 100.0,
            "position_frame": "goal_relative_delta",
            "model_state": model.state_dict(),
        },
        checkpoint_path,
    )
    export_runtime_checkpoint(checkpoint_path, runtime_path)
    return runtime_path, model


def _export_keyboard_checkpoint(tmp_path: Path) -> tuple[Path, KeyboardActionGRU, dict[str, int], dict[str, int]]:
    char_to_id = {
        CHAR_PAD: 0,
        CHAR_UNK: 1,
        CHAR_EOS: 2,
        CHAR_SEP: 3,
        "a": 4,
        "b": 5,
    }
    action_to_id = {"a": 0, "b": 1, KEY_BACKSPACE: 2, KEY_STOP: 3}
    id_to_action = {index: action for action, index in action_to_id.items()}
    model_config = {
        "char_vocab_size": len(char_to_id),
        "action_vocab_size": len(action_to_id),
        "hidden_size": 5,
        "char_embed_size": 4,
        "action_embed_size": 3,
        "layers": 1,
        "dropout": 0.0,
    }
    model = KeyboardActionGRU(**model_config)
    _copy_deterministic_weights(model, seed_offset=0.01)
    model.eval()

    checkpoint_path = tmp_path / "keyboard.pt"
    runtime_path = tmp_path / "keyboard.safetensors"
    torch.save(
        {
            "kind": "keyboard_action_gru",
            "model_config": model_config,
            "char_to_id": char_to_id,
            "action_to_id": action_to_id,
            "id_to_action": id_to_action,
            "sequence_mode": "constrained",
            "model_state": model.state_dict(),
        },
        checkpoint_path,
    )
    export_runtime_checkpoint(checkpoint_path, runtime_path)
    return runtime_path, model, char_to_id, action_to_id


def _run_probe(binary: Path, *args: object) -> dict:
    result = subprocess.run(
        [str(binary), *[str(arg) for arg in args]],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def _vector(tensor: torch.Tensor) -> list[float]:
    return [float(value) for value in tensor.detach().cpu().reshape(-1).tolist()]


def _assert_vector(actual: list[float], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    assert actual == pytest.approx(expected, **APPROX)


def _mouse_python_trace(
    model: MouseTrajectoryGRU,
    *,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    click_at_end: bool,
    max_steps: int,
    click_threshold: float,
    min_dt_ms: float,
    coordinate_scale: float,
) -> dict:
    action_count = len(MOUSE_ACTIONS)
    scale = max(1.0, coordinate_scale)
    dx = to_x - from_x
    dy = to_y - from_y
    distance = math.hypot(dx, dy)
    condition_values = [
        from_x / scale,
        from_y / scale,
        to_x / scale,
        to_y / scale,
        dx / scale,
        dy / scale,
        distance / scale,
    ]
    condition = torch.tensor([condition_values], dtype=torch.float32)
    rows: list[dict] = []
    steps: list[dict] = []
    previous = torch.zeros(3 + action_count + 1, dtype=torch.float32)
    previous[3 + action_count] = 1.0
    offset = 0.0
    state_along = 0.0
    state_perp = 0.0

    with torch.no_grad():
        embedding = model.condition(condition)[0]
        hidden = embedding.view(1, 1, -1).expand(model.layers, 1, -1).contiguous()
        for step_index in range(max_steps):
            decoder_input = torch.cat([embedding, previous], dim=0)
            output, hidden = model.gru(decoder_input.view(1, 1, -1), hidden)
            current = output[0, 0]
            dt_head = model.dt_head(current).view(-1)
            pos_head = model.pos_head(current).view(-1)
            action_head = model.action_head(current).view(-1)

            raw_action = int(torch.argmax(action_head).item())
            action_id = raw_action
            dt_ms = log_to_dt(float(dt_head[0]))
            if rows:
                dt_ms = max(dt_ms, min_dt_ms)
            offset += dt_ms

            remaining_steps = max(1, max_steps - step_index)
            min_delta = (1.0 - state_along) / remaining_steps
            state_along = min(1.0, state_along + max(float(pos_head[0]), min_delta, 0.0))
            guided_perp = state_perp + float(pos_head[1])
            envelope = max(0.0, 0.35 * math.sin(math.pi * max(0.0, min(1.0, state_along))))
            state_perp = max(
                -envelope,
                min(envelope, guided_perp * (1.0 - 0.25 * state_along)),
            )

            terminal = action_id != 0 or state_along >= click_threshold
            if terminal:
                action_id = 1 if click_at_end else 0
                state_along = 1.0
                state_perp = 0.0

            x, y = screen_position_from_goal_relative(
                from_x,
                from_y,
                to_x,
                to_y,
                state_along,
                state_perp,
            )
            if terminal:
                x = to_x
                y = to_y

            steps.append(
                {
                    "step": step_index,
                    "previous": _vector(previous),
                    "decoderInput": _vector(decoder_input),
                    "hidden": _vector(current),
                    "dtHead": _vector(dt_head),
                    "posHead": _vector(pos_head),
                    "actionHead": _vector(action_head),
                    "stateAlong": state_along,
                    "statePerp": state_perp,
                    "x": x,
                    "y": y,
                    "dtMs": dt_ms,
                    "rawAction": raw_action,
                    "action": action_id,
                    "terminal": terminal,
                }
            )
            rows.append({"x": x, "y": y, "dtMs": dt_ms, "action": action_id})
            if terminal:
                break

            previous = torch.zeros_like(previous)
            previous[0] = dt_head[0]
            previous[1] = state_along
            previous[2] = state_perp
            previous[3 + max(0, min(action_id, action_count - 1))] = 1.0

    if not rows or rows[-1]["x"] != to_x or rows[-1]["y"] != to_y:
        rows.append({"x": to_x, "y": to_y, "dtMs": min_dt_ms, "action": 1 if click_at_end else 0})

    return {
        "condition": condition_values,
        "embedding": _vector(embedding),
        "steps": steps,
        "plan": rows,
    }


def _char_id(token: str, char_to_id: dict[str, int]) -> int:
    return char_to_id.get(token, char_to_id[CHAR_UNK])


def _keyboard_condition_ids(initial: str, final: str, char_to_id: dict[str, int]) -> list[int]:
    ids = [_char_id(token, char_to_id) for token in initial]
    ids.append(_char_id(CHAR_SEP, char_to_id))
    ids.extend(_char_id(token, char_to_id) for token in final)
    ids.append(_char_id(CHAR_EOS, char_to_id))
    return ids


def _apply_action_copy(text: str, action: str) -> str:
    if action == KEY_BACKSPACE:
        return text[:-1]
    if action == KEY_STOP:
        return text
    return text + action


def _keyboard_python_trace(
    model: KeyboardActionGRU,
    *,
    initial: str,
    final: str,
    max_steps: int,
    decode_mode: str,
    structured_extra_steps: int,
    canonical_bias: float,
    char_to_id: dict[str, int],
    action_to_id: dict[str, int],
) -> dict:
    del structured_extra_steps, canonical_bias
    condition_ids = _keyboard_condition_ids(initial, final, char_to_id)
    condition_tensor = torch.tensor([condition_ids], dtype=torch.long)
    condition_lengths = torch.tensor([len(condition_ids)], dtype=torch.long)
    previous_action_id = len(action_to_id)
    previous_dt = 0.0
    offset = 0.0
    text = initial
    rows: list[dict] = []
    steps: list[dict] = []

    with torch.no_grad():
        condition = model.encode(condition_tensor, condition_lengths)[0]
        hidden = condition.view(1, 1, -1).expand(model.layers, 1, -1).contiguous()
        for step_index in range(max_steps):
            next_char = keyboard_next_char(final, list(text))
            action_embedding = model.action_embed(torch.tensor([previous_action_id], dtype=torch.long))[0]
            next_char_embedding = model.char_embed(torch.tensor([_char_id(next_char, char_to_id)], dtype=torch.long))[0]
            previous_dt_tensor = torch.tensor([previous_dt], dtype=torch.float32)
            decoder_input = torch.cat([condition, action_embedding, next_char_embedding, previous_dt_tensor], dim=0)
            output, hidden = model.decoder(decoder_input.view(1, 1, -1), hidden)
            current = output[0, 0]
            dt_head = model.dt_head(current).view(-1)
            action_head = model.action_head(current).view(-1)

            if decode_mode == "canonical":
                action = constrained_keyboard_action(final, list(text))
                selected_action_id = action_to_id[action]
                preferred_action_id = selected_action_id
                step_kind = "repair" if action == KEY_BACKSPACE else "target"
                valid_action_ids: list[int] = []
            else:
                raise AssertionError("This parity trace currently exercises canonical decoding.")

            dt_ms = log_to_dt(float(dt_head[0]))
            offset += dt_ms
            terminal = action == KEY_STOP
            text_after = text if terminal else _apply_action_copy(text, action)
            steps.append(
                {
                    "step": step_index,
                    "textBefore": text,
                    "nextChar": next_char,
                    "actionEmbedding": _vector(action_embedding),
                    "nextCharEmbedding": _vector(next_char_embedding),
                    "decoderInput": _vector(decoder_input),
                    "hidden": _vector(current),
                    "dtHead": _vector(dt_head),
                    "actionHead": _vector(action_head),
                    "validActionIds": valid_action_ids,
                    "previousActionId": previous_action_id,
                    "selectedActionId": selected_action_id,
                    "preferredActionId": preferred_action_id,
                    "previousDt": previous_dt,
                    "offsetMs": offset,
                    "dtMs": dt_ms,
                    "action": action,
                    "textAfter": text_after,
                    "stepKind": step_kind,
                    "terminal": terminal,
                }
            )
            if terminal:
                break

            text = text_after
            rows.append(
                {
                    "offsetMs": offset,
                    "dtMs": dt_ms,
                    "action": action,
                    "textAfter": text,
                    "stepKind": step_kind,
                }
            )
            previous_action_id = selected_action_id
            previous_dt = float(dt_head[0])

    if text != final:
        rows = []
    return {
        "conditionIds": condition_ids,
        "condition": _vector(condition),
        "steps": steps,
        "rows": rows,
    }


def test_mouse_cpp_runtime_trace_matches_python_rollout(runtime_probe: Path, tmp_path: Path) -> None:
    runtime_path, model = _export_mouse_checkpoint(tmp_path)
    args = {
        "from_x": 12.5,
        "from_y": 18.0,
        "to_x": 88.25,
        "to_y": 63.5,
        "click_at_end": True,
        "max_steps": 7,
        "click_threshold": 0.72,
        "min_dt_ms": 4.0,
        "coordinate_scale": 100.0,
    }

    cpp = _run_probe(
        runtime_probe,
        "mouse",
        runtime_path,
        args["from_x"],
        args["from_y"],
        args["to_x"],
        args["to_y"],
        1,
        args["max_steps"],
        args["click_threshold"],
        args["min_dt_ms"],
    )
    py = _mouse_python_trace(model, **args)

    assert cpp["usedFallback"] is False
    _assert_vector(cpp["condition"], py["condition"])
    _assert_vector(cpp["embedding"], py["embedding"])
    assert len(cpp["steps"]) == len(py["steps"])
    for actual, expected in zip(cpp["steps"], py["steps"], strict=True):
        for key in ["previous", "decoderInput", "hidden", "dtHead", "posHead", "actionHead"]:
            _assert_vector(actual[key], expected[key])
        for key in ["stateAlong", "statePerp", "x", "y", "dtMs"]:
            assert actual[key] == pytest.approx(expected[key], **APPROX)
        for key in ["step", "rawAction", "action", "terminal"]:
            assert actual[key] == expected[key]

    assert len(cpp["plan"]) == len(py["plan"])
    for actual, expected in zip(cpp["plan"], py["plan"], strict=True):
        for key in ["x", "y", "dtMs"]:
            assert actual[key] == pytest.approx(expected[key], **APPROX)
        assert actual["action"] == expected["action"]


def test_keyboard_cpp_runtime_trace_matches_python_rollout(runtime_probe: Path, tmp_path: Path) -> None:
    runtime_path, model, char_to_id, action_to_id = _export_keyboard_checkpoint(tmp_path)
    args = {
        "initial": "a",
        "final": "ab",
        "max_steps": 4,
        "decode_mode": "canonical",
        "structured_extra_steps": 6,
        "canonical_bias": 1.5,
        "char_to_id": char_to_id,
        "action_to_id": action_to_id,
    }

    cpp = _run_probe(
        runtime_probe,
        "keyboard",
        runtime_path,
        args["initial"],
        args["final"],
        args["max_steps"],
        args["decode_mode"],
        args["structured_extra_steps"],
        args["canonical_bias"],
    )
    py = _keyboard_python_trace(model, **args)

    assert cpp["conditionIds"] == py["conditionIds"]
    _assert_vector(cpp["condition"], py["condition"])
    assert len(cpp["steps"]) == len(py["steps"])
    for actual, expected in zip(cpp["steps"], py["steps"], strict=True):
        for key in ["actionEmbedding", "nextCharEmbedding", "decoderInput", "hidden", "dtHead", "actionHead"]:
            _assert_vector(actual[key], expected[key])
        for key in ["previousDt", "offsetMs", "dtMs"]:
            assert actual[key] == pytest.approx(expected[key], **APPROX)
        for key in [
            "step",
            "textBefore",
            "nextChar",
            "validActionIds",
            "previousActionId",
            "selectedActionId",
            "preferredActionId",
            "action",
            "textAfter",
            "stepKind",
            "terminal",
        ]:
            assert actual[key] == expected[key]

    assert len(cpp["rows"]) == len(py["rows"])
    for actual, expected in zip(cpp["rows"], py["rows"], strict=True):
        for key in ["offsetMs", "dtMs"]:
            assert actual[key] == pytest.approx(expected[key], **APPROX)
        for key in ["action", "textAfter", "stepKind"]:
            assert actual[key] == expected[key]
