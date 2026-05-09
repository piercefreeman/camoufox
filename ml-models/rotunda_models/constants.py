"""Constants and keyboard geometry for cadence models."""

from __future__ import annotations

from .types import KeyDef

MOUSE_ACTIONS = ["move", "left_click", "right_click", "center_click", "other_click"]

KEY_BACKSPACE = "<BACKSPACE>"
KEY_STOP = "<STOP>"
KEY_UNKNOWN_ACTION = "¤"
KEY_BOS = "<BOS>"
CHAR_PAD = "<PAD>"
CHAR_UNK = "<UNK>"
CHAR_EOS = "<EOS>"
CHAR_SEP = "<SEP>"
PRINTABLE_ASCII = tuple(chr(code) for code in range(32, 127))


KEY_LAYOUT = [
    KeyDef("`", 0.0, 0.0),
    KeyDef("1", 1.0, 0.0),
    KeyDef("2", 2.0, 0.0),
    KeyDef("3", 3.0, 0.0),
    KeyDef("4", 4.0, 0.0),
    KeyDef("5", 5.0, 0.0),
    KeyDef("6", 6.0, 0.0),
    KeyDef("7", 7.0, 0.0),
    KeyDef("8", 8.0, 0.0),
    KeyDef("9", 9.0, 0.0),
    KeyDef("0", 10.0, 0.0),
    KeyDef("-", 11.0, 0.0),
    KeyDef("=", 12.0, 0.0),
    KeyDef("q", 1.5, 1.0),
    KeyDef("w", 2.5, 1.0),
    KeyDef("e", 3.5, 1.0),
    KeyDef("r", 4.5, 1.0),
    KeyDef("t", 5.5, 1.0),
    KeyDef("y", 6.5, 1.0),
    KeyDef("u", 7.5, 1.0),
    KeyDef("i", 8.5, 1.0),
    KeyDef("o", 9.5, 1.0),
    KeyDef("p", 10.5, 1.0),
    KeyDef("[", 11.5, 1.0),
    KeyDef("]", 12.5, 1.0),
    KeyDef("\\", 13.75, 1.0),
    KeyDef("a", 1.75, 2.0),
    KeyDef("s", 2.75, 2.0),
    KeyDef("d", 3.75, 2.0),
    KeyDef("f", 4.75, 2.0),
    KeyDef("g", 5.75, 2.0),
    KeyDef("h", 6.75, 2.0),
    KeyDef("j", 7.75, 2.0),
    KeyDef("k", 8.75, 2.0),
    KeyDef("l", 9.75, 2.0),
    KeyDef(";", 10.75, 2.0),
    KeyDef("'", 11.75, 2.0),
    KeyDef("\n", 13.25, 2.0),
    KeyDef("z", 2.25, 3.0),
    KeyDef("x", 3.25, 3.0),
    KeyDef("c", 4.25, 3.0),
    KeyDef("v", 5.25, 3.0),
    KeyDef("b", 6.25, 3.0),
    KeyDef("n", 7.25, 3.0),
    KeyDef("m", 8.25, 3.0),
    KeyDef(",", 9.25, 3.0),
    KeyDef(".", 10.25, 3.0),
    KeyDef("/", 11.25, 3.0),
    KeyDef(" ", 6.5, 4.0),
]
BACKSPACE_POS = (13.5, 0.0)
