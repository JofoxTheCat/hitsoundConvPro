"""Entry point of the packaged app: without arguments it opens the GUI, otherwise it is the normal CLI.

Double-clicking an .exe means the console window disappears with the error, so a crash is printed,
written next to the executable and the window is kept open until a key is pressed.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _report_crash(error: BaseException) -> None:
    text = "".join(traceback.format_exception(error))
    print(text, file=sys.stderr)
    try:
        log = Path(sys.executable).resolve().parent / "crash.log" if getattr(sys, "frozen", False) else Path("crash.log")
        log.write_text(text, encoding="utf-8")
        print(f"Written to {log}", file=sys.stderr)
    except OSError:
        pass


def _wait() -> None:
    """Keep a double-clicked window readable."""
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close ...")
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> int:
    from hitsoundconv.cli import main as cli

    try:
        return cli(sys.argv[1:] or ["gui"])
    except SystemExit as e:  # argparse and friends
        code = e.code if isinstance(e.code, int) else 0
        if code:
            _wait()
        return code
    except KeyboardInterrupt:
        return 0
    except BaseException as e:
        _report_crash(e)
        _wait()
        return 1


if __name__ == "__main__":
    sys.exit(main())
