"""GhostHandoff CLI: pack | show | mcp.

Exit codes: 0 = done, 2 = could not build or read (bad path, pack exists
without --force, pack missing). 1 is never used for a built pack: a
handoff pack is a report, not a verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .pack import write_pack


def _cmd_pack(args) -> int:
    project = args.project
    if not os.path.isdir(project):
        print(f"ghosthandoff: project path is not a directory: {project}", file=sys.stderr)
        return 2
    out_dir = args.out or os.path.join(os.getcwd(), "handoff-out")
    try:
        data = write_pack(project, out_dir, since=args.since, base=args.base, force=args.force)
    except FileExistsError as exc:
        print(f"ghosthandoff: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ghosthandoff: could not write pack: {exc}", file=sys.stderr)
        return 2
    git = data.get("git") or {}
    summary = {
        "pack_markdown": data["pack"]["markdown"],
        "pack_json": data["pack"]["json"],
        "project": data["project"]["path"],
        "git_available": bool(git.get("available")),
        "commits_in_window": git.get("commit_count", 0) if git.get("available") else 0,
        "files_touched": git.get("files_changed_total", 0) if git.get("available") else 0,
        "markers": (data.get("markers") or {}).get("total", 0),
        "reports_found": len(data.get("reports", [])),
        "open_loops": len(data.get("open_loops", [])),
        "next_steps": len(data.get("next_steps", [])),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Handoff pack written: {summary['pack_markdown']}")
        print(f"Machine copy:         {summary['pack_json']}")
        print(f"Commits in window: {summary['commits_in_window']}, "
              f"files touched: {summary['files_touched']}, "
              f"markers: {summary['markers']}, reports: {summary['reports_found']}, "
              f"open loops: {summary['open_loops']}, next steps: {summary['next_steps']}")
        if not summary["git_available"]:
            print("Note: git section unavailable (not a git work tree). Pack still built.")
    return 0


def _cmd_show(args) -> int:
    md_path = os.path.join(args.pack_dir, "HANDOFF.md")
    if not os.path.isfile(md_path):
        print(f"ghosthandoff: no HANDOFF.md in {args.pack_dir}", file=sys.stderr)
        return 2
    with open(md_path, "r", encoding="utf-8", errors="replace") as fh:
        sys.stdout.write(fh.read())
    return 0


def _cmd_mcp(args) -> int:
    from .mcp_server import serve
    serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghosthandoff",
        description="Build a session handoff pack from repo facts. Propose-only: "
                    "never commits, never sends, never edits the project.",
    )
    parser.add_argument("--version", action="version", version=f"ghosthandoff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="build HANDOFF.md + handoff.json for a project")
    p.add_argument("project", help="project directory to describe")
    p.add_argument("-o", "--out", default=None,
                   help="output directory (default: ./handoff-out under the current directory)")
    p.add_argument("--since", default=None,
                   help="session window: duration (2h, 90m, 3d), ISO date/time, or a git ref")
    p.add_argument("--base", default=None,
                   help="also report diff stats against this ref (base...HEAD)")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing HANDOFF.md / handoff.json in the output directory")
    p.add_argument("--json", action="store_true", help="print the run summary as JSON")
    p.set_defaults(func=_cmd_pack)

    s = sub.add_parser("show", help="print a built pack's HANDOFF.md")
    s.add_argument("pack_dir", help="directory containing HANDOFF.md")
    s.set_defaults(func=_cmd_show)

    m = sub.add_parser("mcp", help="run the stdio MCP server (local only)")
    m.set_defaults(func=_cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
