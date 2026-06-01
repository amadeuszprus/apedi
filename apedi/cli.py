"""CLI entrypoint — handles fast-path options before pulling in GTK."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv
    rest = args[1:]
    if "--version" in rest or "-V" in rest:
        from . import __version__
        print(f"apedi {__version__}")
        return 0
    from .app import main as app_main
    return app_main(args)


if __name__ == "__main__":
    sys.exit(main())
