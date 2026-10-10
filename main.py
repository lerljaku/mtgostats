"""MTGO match statistics - web UI.

Usage:
    python main.py                       # auto-detect MTGO logs under %LOCALAPPDATA%\\Apps\\2.0
    python main.py --logs D:\\backup\\mtgo  # extra/alternate folders (searched recursively)
    python main.py --player konviczka    # force whose perspective to use
"""
import argparse
import webbrowser

from mtgostats import logparser
from mtgostats.app import create_app


def main():
    parser = argparse.ArgumentParser(description="MTGO match history statistics")
    parser.add_argument("--logs", action="append", default=[],
                        help="folder containing Match_GameLog_*.dat files (repeatable)")
    parser.add_argument("--no-default-logs", action="store_true",
                        help="don't scan the default MTGO install folder")
    parser.add_argument("--player", help="your MTGO username (default: most frequent player)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    roots = args.logs + ([] if args.no_default_logs else logparser.default_log_roots())
    app = create_app(roots, args.player)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Serving MTGO stats at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
