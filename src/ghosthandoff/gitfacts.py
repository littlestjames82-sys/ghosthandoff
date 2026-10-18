"""Git facts for the handoff pack.

Read-only by construction: the only subcommands used are rev-parse,
status, log, diff (stat/name-only), ls-files, and stash list, and every
invocation passes ``--no-optional-locks`` (plus GIT_OPTIONAL_LOCKS=0)
so git itself does not write back to the index while reporting.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta

GIT_TIMEOUT = 30

_READ_ONLY = ("rev-parse", "status", "log", "diff", "ls-files", "stash")


def run_git(project: str, args: list[str]) -> tuple[int, str]:
    """Run one read-only git command in ``project``. Returns (rc, stdout)."""
    if not args or args[0] not in _READ_ONLY:
        raise ValueError(f"git subcommand not on the read-only list: {args[:1]}")
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, NotADirectoryError):
        return 127, ""
    return proc.returncode, proc.stdout or ""


_DURATION_RE = re.compile(r"^(\d+)\s*([mhd])$")


def resolve_window(project: str, since: str | None, now: datetime) -> dict:
    """Resolve the session window.

    Returns a dict with ``kind`` ("since" or "ref"), ``description`` and
    either ``git_since`` (a git --since argument) or ``ref``.
    The default is the last 12 hours; uncommitted changes are always in
    the session regardless of the window.
    """
    if since is None:
        start = now - timedelta(hours=12)
        return {
            "kind": "since",
            "description": "last 12 hours (default) plus all uncommitted changes",
            "git_since": start.strftime("%Y-%m-%d %H:%M:%S"),
            "ref": None,
        }
    m = _DURATION_RE.match(since.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        start = now - delta
        return {
            "kind": "since",
            "description": f"last {n}{unit} (from --since {since}) plus all uncommitted changes",
            "git_since": start.strftime("%Y-%m-%d %H:%M:%S"),
            "ref": None,
        }
    parsed = None
    try:
        parsed = datetime.fromisoformat(since.strip())
    except ValueError:
        parsed = None
    if parsed is not None:
        return {
            "kind": "since",
            "description": f"since {since} (from --since) plus all uncommitted changes",
            "git_since": since.strip(),
            "ref": None,
        }
    rc, _ = run_git(project, ["rev-parse", "--verify", "--quiet", f"{since}^{{commit}}"])
    if rc == 0:
        return {
            "kind": "ref",
            "description": f"commits in {since}..HEAD (from --since) plus all uncommitted changes",
            "git_since": None,
            "ref": since,
        }
    # Unrecognised value: hand it to git as a --since argument and let the
    # log call report emptiness; description stays honest about the source.
    return {
        "kind": "since",
        "description": f"since {since} (from --since, unparsed) plus all uncommitted changes",
        "git_since": since,
        "ref": None,
    }


def _parse_shortstat(text: str) -> dict:
    out = {"files_changed": 0, "insertions": 0, "deletions": 0}
    m = re.search(r"(\d+) files? changed", text)
    if m:
        out["files_changed"] = int(m.group(1))
    m = re.search(r"(\d+) insertions?\(\+\)", text)
    if m:
        out["insertions"] = int(m.group(1))
    m = re.search(r"(\d+) deletions?\(-\)", text)
    if m:
        out["deletions"] = int(m.group(1))
    return out


def _log_args(window: dict, extra: list[str]) -> list[str]:
    args = ["log"]
    if window["kind"] == "ref":
        args.append(f"{window['ref']}..HEAD")
    args.extend(extra)
    if window["kind"] == "since":
        args.append(f"--since={window['git_since']}")
    return args


def collect_git(project: str, window: dict, base: str | None,
                max_commits: int = 100, max_files: int = 200) -> dict:
    """Collect every git fact the pack uses. Never writes to the project."""
    rc, _ = run_git(project, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return {"available": False, "reason": "not a git work tree (or git not on PATH)"}

    facts: dict = {"available": True}

    rc, out = run_git(project, ["rev-parse", "HEAD"])
    facts["head"] = out.strip() if rc == 0 else ""
    rc, out = run_git(project, ["rev-parse", "--short", "HEAD"])
    facts["head_short"] = out.strip() if rc == 0 else ""

    # --- status (porcelain v1, -z) -------------------------------------
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    branch = ""
    upstream = None
    detached = False
    rc, out = run_git(project, ["status", "--porcelain=v1", "-z", "--branch"])
    if rc == 0 and out:
        records = out.split("\0")
        i = 0
        while i < len(records):
            rec = records[i]
            i += 1
            if not rec:
                continue
            if rec.startswith("## "):
                head_line = rec[3:]
                if head_line.startswith("HEAD"):
                    detached = True
                    branch = "HEAD (detached)"
                else:
                    branch = head_line.split("...")[0].strip()
                    if "..." in head_line:
                        upstream = head_line.split("...")[1].split(" ")[0].strip()
                continue
            if len(rec) < 4:
                continue
            x, y = rec[0], rec[1]
            path = rec[3:]
            if x in "RC" or y in "RC":
                # -z mode: the source path follows as its own record.
                if i < len(records):
                    i += 1
            if x == "?" and y == "?":
                untracked.append(path)
                continue
            if x not in " !":
                staged.append(path)
            if y not in " !":
                unstaged.append(path)
    facts["branch"] = branch
    facts["detached"] = detached
    facts["upstream"] = upstream
    facts["status"] = {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "staged_count": len(staged),
        "unstaged_count": len(unstaged),
        "untracked_count": len(untracked),
    }

    # --- ahead / behind -------------------------------------------------
    facts["ahead"] = None
    facts["behind"] = None
    if upstream:
        # Counted with log ranges so every git call stays on the small
        # read-only subcommand allowlist in run_git.
        rc, out = run_git(project, ["log", "--format=%H", "@{upstream}..HEAD"])
        if rc == 0:
            facts["ahead"] = len([ln for ln in out.splitlines() if ln.strip()])
        rc, out = run_git(project, ["log", "--format=%H", "HEAD..@{upstream}"])
        if rc == 0:
            facts["behind"] = len([ln for ln in out.splitlines() if ln.strip()])

    # --- commits in the session window ---------------------------------
    fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%aI%x1e"
    rc, out = run_git(project, _log_args(window, [f"--format={fmt}", f"-n{max_commits + 1}"]))
    commits = []
    if rc == 0 and out:
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x1f")
            if len(parts) != 5:
                continue
            from .redact import clean_line
            commits.append({
                "hash": parts[0],
                "short": parts[1],
                "subject": clean_line(parts[2], 200),
                "author": parts[3],
                "time": parts[4],
            })
    facts["commits_truncated"] = len(commits) > max_commits
    facts["commits"] = commits[:max_commits]
    facts["commit_count"] = len(facts["commits"])

    # files touched by those commits
    commit_files: list[str] = []
    if facts["commit_count"]:
        rc, out = run_git(project, _log_args(window, ["--name-only", "--format=%x1e%H"]))
        if rc == 0 and out:
            seen: set[str] = set()
            for block in out.split("\x1e"):
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                # first line of each block is the commit hash from the format
                for ln in lines[1:]:
                    if ln not in seen:
                        seen.add(ln)
                        commit_files.append(ln)
    facts["commit_files"] = commit_files

    # --- diff stats ------------------------------------------------------
    rc, out = run_git(project, ["diff", "--shortstat"])
    facts["diff_unstaged"] = _parse_shortstat(out if rc == 0 else "")
    rc, out = run_git(project, ["diff", "--cached", "--shortstat"])
    facts["diff_staged"] = _parse_shortstat(out if rc == 0 else "")

    facts["diff_base"] = None
    if base:
        rc, out = run_git(project, ["diff", "--shortstat", f"{base}...HEAD"])
        if rc == 0:
            facts["diff_base"] = {"base": base, **_parse_shortstat(out)}

    # union of session-touched files
    union: list[str] = []
    seen = set()
    for src in (commit_files, staged, unstaged, untracked):
        for p in src:
            if p not in seen:
                seen.add(p)
                union.append(p)
    facts["files_changed"] = union[:max_files]
    facts["files_changed_total"] = len(union)
    facts["files_changed_truncated"] = len(union) > max_files

    # --- stash ------------------------------------------------------------
    rc, out = run_git(project, ["stash", "list", "--format=%gd%x1f%gs%x1f%cI"])
    stash = []
    if rc == 0 and out:
        from .redact import clean_line
        for ln in out.splitlines():
            if not ln.strip():
                continue
            parts = ln.split("\x1f")
            if len(parts) == 3:
                stash.append({"ref": parts[0], "message": clean_line(parts[1], 160), "time": parts[2]})
    facts["stash"] = stash
    facts["stash_count"] = len(stash)
    return facts


def list_project_files(project: str, git_facts: dict) -> tuple[list[str], str]:
    """File universe for the marker scan.

    Git projects: tracked plus untracked-but-not-ignored (ls-files).
    Other folders: a bounded walk skipping obvious junk directories.
    Returns (relative paths, source description).
    """
    if git_facts.get("available"):
        rc, out = run_git(project, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        if rc == 0:
            files = [p for p in out.split("\0") if p]
            return files, "git ls-files (tracked + untracked, not ignored)"
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
            "build", ".tox", ".mypy_cache", ".pytest_cache", "target"}
    files: list[str] = []
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in names:
            full = os.path.join(root, name)
            files.append(os.path.relpath(full, project))
        if len(files) > 50000:
            break
    return files, "directory walk (junk directories skipped)"
