import base64
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import orjson
from playwright._impl._driver import compute_driver_executable

from rotunda.assets import get_asset_by_name
from rotunda.utils import launch_options

LAUNCH_SCRIPT: Path = get_asset_by_name("launchServer.js")


def camel_case(snake_str: str) -> str:
    """
    Convert a string to camelCase
    """
    if len(snake_str) < 2:
        return snake_str
    camel_case_str = ''.join(x.capitalize() for x in snake_str.lower().split('_'))
    return camel_case_str[0].lower() + camel_case_str[1:]


def to_camel_case_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a dictionary to camelCase
    """
    return {camel_case(key): value for key, value in data.items()}


def get_nodejs() -> str:
    """
    Get the bundled Node.js executable
    """
    # Note: Older versions of Playwright return a string rather than a tuple.
    _nodejs: str | tuple[str, ...] = compute_driver_executable()[0]
    if isinstance(_nodejs, tuple):
        return _nodejs[0]
    return _nodejs


def launch_server(**kwargs) -> NoReturn:
    """
    Launch a Playwright server. Takes the same arguments as `Rotunda()`.
    Prints the websocket endpoint to the console.
    """
    config = launch_options(**kwargs)
    nodejs = get_nodejs()

    data = orjson.dumps(to_camel_case_dict(config))

    process = subprocess.Popen(  # nosec
        [
            nodejs,
            str(LAUNCH_SCRIPT),
        ],
        cwd=Path(nodejs).parent / "package",
        stdin=subprocess.PIPE,
        text=True,
    )
    # Write data to stdin and close the stream
    if process.stdin:
        process.stdin.write(base64.b64encode(data).decode())
        process.stdin.close()

    # Wait forever
    process.wait()

    # Add an explicit return statement to satisfy the NoReturn type hint
    raise RuntimeError("Server process terminated unexpectedly")
