from importlib import import_module
import sys


# Preserve the historical `tests.*` import paths after moving the suite under
# `__tests__/playwright`.
sys.modules.setdefault("tests", sys.modules[__name__])
for _module_name in ("conftest", "server", "utils"):
    sys.modules.setdefault(
        f"tests.{_module_name}",
        import_module(f"{__name__}.{_module_name}"),
    )
