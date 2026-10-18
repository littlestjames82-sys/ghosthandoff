"""Pack assembly: facts -> open loops -> next steps -> HANDOFF.md + handoff.json.

Every sentence in HANDOFF.md is a fixed template filled from a measured
fact in handoff.json. The two files are rendered from the same dict, so
their numbers cannot disagree.
"""
from __future__ import annotations

import os
from datetime import datetime

from . import __version__, TOOL
from .gitfacts import collect_git, list_project_files, resolve_window
from .scan import discover_reports, scan_markers

PASSING_VERDICTS = {"pass", "passed", "ok", "sufficient", "success", "true"}


def _verdict_is_failing(verdict) -> bool:
    if verdict is True:
        return False
    if verdict is False:
        return True
    if isinstance(verdict, str):
        return verdict.strip().lower() not in PASSING_VERDICTS
    return False


def derive_open_loops(data: dict) -> list[dict]:
    loops: list[dict] = []
    git = data.get("git") or {}
    if git.get("available"):
        st = git["status"]
        if st["staged_count"] or st["unstaged_count"]:
            loops.append({
                "kind": "uncommitted-changes",
                "detail": f"{st['staged_count']} staged and {st['unstaged_count']} unstaged "
                          f"file(s) are not committed",
                "source": "git status",
            })
        if st["untracked_count"]:
            loops.append({
                "kind": "untracked-files",
                "detail": f"{st['untracked_count']} untracked file(s) in the working tree",
                "source": "git status",
            })
        if git.get("ahead"):
            loops.append({
                "kind": "unpushed-commits",
                "detail": f"{git['ahead']} commit(s) on this branch are not on the upstream",
                "source": "git log @{upstream}..HEAD",
            })
        if git.get("behind"):
            loops.append({
                "kind": "behind-upstream",
                "detail": f"this branch is {git['behind']} commit(s) behind its upstream",
                "source": "git log HEAD..@{upstream}",
            })
        if git.get("stash_count"):
            loops.append({
                "kind": "stash-entries",
                "detail": f"{git['stash_count']} stash entr"
                          f"{'y' if git['stash_count'] == 1 else 'ies'} parked",
                "source": "git stash list",
            })
    for rep in data.get("reports", []):
        if rep["kind"] == "ghostverify-report" and _verdict_is_failing(rep.get("verdict")):
            loops.append({
                "kind": "failing-verification",
                "detail": f"latest recorded GhostVerify verdict is {rep.get('verdict')!r} "
                          f"(report modified {rep.get('modified', 'unknown')})",
                "source": "verify-report.json",
            })
        if rep["kind"] == "pytest-lastfailed" and rep.get("failing_count"):
            loops.append({
                "kind": "recorded-test-failures",
                "detail": f"{rep['failing_count']} test(s) recorded failing in the last pytest run",
                "source": ".pytest_cache/v/cache/lastfailed",
            })
    markers = data.get("markers") or {}
    # Only code-context markers count as an open loop. Markers in
    # documentation or fixture files are listed in the Markers section
    # and subtotalled there, but documentation quoting a marker (a style
    # guide showing TODO syntax, a fixture exercising a scanner) is not
    # unfinished work, so it must not manufacture a loop or a next step.
    code_total = markers.get("code_total", markers.get("total", 0))
    if code_total:
        by = markers.get("code_by_kind", markers.get("by_kind", {}))
        parts = ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
        detail = f"{code_total} open marker(s) in code ({parts})"
        docs_total = markers.get("docs_total", 0)
        if docs_total:
            detail += (f"; {docs_total} more marker(s) sit in documentation "
                       "or fixture files: listed in the Markers section, "
                       "not counted as open loops")
        loops.append({
            "kind": "open-markers",
            "detail": detail,
            "source": "marker scan of project files",
        })
    return loops


def derive_next_steps(data: dict) -> list[dict]:
    """Templated drafts from the open loops, fixed priority order."""
    steps: list[dict] = []
    loops = {lp["kind"]: lp for lp in data.get("open_loops", [])}
    git = data.get("git") or {}
    markers = data.get("markers") or {}
    items = markers.get("items", [])

    # Marker steps use code-context markers only, matching the loop:
    # counts come from code_by_kind and the cited first marker is the
    # first code one, never a documentation or fixture mention.
    code_by_kind = markers.get("code_by_kind", markers.get("by_kind", {}))

    def first_marker(kind: str):
        for it in items:
            if it["kind"] == kind and it.get("context", "code") == "code":
                return it
        return None

    if "failing-verification" in loops:
        steps.append({
            "text": "Re-check verification: the latest recorded GhostVerify verdict is not "
                    "passing. Handoff quoted it with its age and did not re-run anything; "
                    "re-running is GhostVerify's job.",
            "source": "verify-report.json",
        })
    if "recorded-test-failures" in loops:
        steps.append({
            "text": f"Look at the {loops['recorded-test-failures']['detail'].split(' ')[0]} "
                    "test(s) the last pytest run recorded as failing.",
            "source": ".pytest_cache/v/cache/lastfailed",
        })
    fx = first_marker("FIXME")
    if fx:
        steps.append({
            "text": f"Address FIXME markers first ({code_by_kind.get('FIXME', 0)} open); "
                    f"the first listed is at {fx['file']}:{fx['line']}.",
            "source": "marker scan",
        })
    td = first_marker("TODO")
    if td:
        steps.append({
            "text": f"Work through the TODO markers ({code_by_kind.get('TODO', 0)} open); "
                    f"the first listed is at {td['file']}:{td['line']}.",
            "source": "marker scan",
        })
    other = [k for k in code_by_kind if k not in ("FIXME", "TODO")]
    if other:
        steps.append({
            "text": "Review the remaining markers: "
                    + ", ".join(f"{k} {code_by_kind[k]}" for k in sorted(other)) + ".",
            "source": "marker scan",
        })
    if "uncommitted-changes" in loops:
        st = git["status"]
        steps.append({
            "text": f"Decide on the uncommitted work: {st['staged_count']} staged and "
                    f"{st['unstaged_count']} unstaged file(s). Commit, keep working, or "
                    "discard; Handoff never commits, that call is yours.",
            "source": "git status",
        })
    if "untracked-files" in loops:
        steps.append({
            "text": f"Decide whether the {git['status']['untracked_count']} untracked file(s) "
                    "belong in the repo or in .gitignore.",
            "source": "git status",
        })
    if "unpushed-commits" in loops:
        steps.append({
            "text": f"Push the {git['ahead']} unpushed commit(s) when ready. "
                    "Handoff never pushes.",
            "source": "git log @{upstream}..HEAD",
        })
    if "behind-upstream" in loops:
        steps.append({
            "text": f"Pull or rebase: this branch is {git['behind']} commit(s) behind "
                    "its upstream.",
            "source": "git log HEAD..@{upstream}",
        })
    if "stash-entries" in loops:
        steps.append({
            "text": f"Review the {git['stash_count']} stash "
                    f"entr{'y' if git['stash_count'] == 1 else 'ies'}: apply, drop, or "
                    "leave parked on purpose.",
            "source": "git stash list",
        })
    return steps


def build_pack_data(project: str, since: str | None = None, base: str | None = None,
                    now: datetime | None = None) -> dict:
    """Collect every fact and derive loops and steps. Pure reads."""
    project = os.path.abspath(project)
    now = now or datetime.now().astimezone()
    window = resolve_window(project, since, now)
    git = collect_git(project, window, base)
    files, files_source = list_project_files(project, git)
    markers = scan_markers(project, files)
    reports = discover_reports(project)
    data = {
        "tool": TOOL,
        "version": __version__,
        "generated_at": now.isoformat(timespec="seconds"),
        "project": {"path": project, "name": os.path.basename(project.rstrip("/")) or project},
        "session_window": window["description"],
        "git": git,
        "markers": {**markers, "files_source": files_source},
        "reports": reports,
        "limits": [
            "Session window is a heuristic: git records no session boundary.",
            "Verification status is quoted from report files on disk, with their "
            "modification times. Nothing was re-run.",
            "Marker scan covers text files up to 512 KB; binary files are skipped. "
            "Markers in documentation and fixture files are listed and "
            "subtotalled, but only markers in code files count as open loops.",
            "Report discovery uses known Ghost tool file names and shapes only.",
            "Quoted lines are truncated and passed through a secret-shape redaction pass.",
        ],
    }
    data["open_loops"] = derive_open_loops(data)
    data["next_steps"] = derive_next_steps(data)
    return data


def render_markdown(data: dict) -> str:
    git = data.get("git") or {}
    markers = data.get("markers") or {}
    lines: list[str] = []
    lines.append(f"# Handoff: {data['project']['name']}")
    lines.append("")
    lines.append(
        f"Drafted by GhostHandoff {data['version']} from repo facts at {data['generated_at']}. "
        "Propose-only: nothing was committed, sent, or changed in the project. "
        "Every fact names its source. Anything not found is stated as not found."
    )
    lines.append("")
    lines.append("## State now")
    lines.append(f"- Project: {data['project']['path']}")
    if git.get("available"):
        head = git.get("head_short") or "unknown"
        branch = git.get("branch") or "unknown"
        lines.append(f"- Branch: {branch} (HEAD {head})")
        if git.get("upstream"):
            ahead = git.get("ahead")
            behind = git.get("behind")
            lines.append(
                f"- Upstream: {git['upstream']}, "
                f"{ahead if ahead is not None else 'unknown'} ahead, "
                f"{behind if behind is not None else 'unknown'} behind"
            )
        else:
            lines.append("- Upstream: none recorded")
        st = git["status"]
        lines.append(
            f"- Working tree: {st['staged_count']} staged, {st['unstaged_count']} unstaged, "
            f"{st['untracked_count']} untracked"
        )
        lines.append(f"- Stash: {git.get('stash_count', 0)} entr"
                     f"{'y' if git.get('stash_count') == 1 else 'ies'}")
    else:
        lines.append(f"- Git: unavailable ({git.get('reason', 'unknown reason')})")
    lines.append("")
    lines.append("## Changed this session")
    lines.append(f"Window: {data['session_window']}")
    if git.get("available"):
        lines.append(f"- Commits in window: {git.get('commit_count', 0)}"
                     + (" (list capped)" if git.get("commits_truncated") else ""))
        for c in git.get("commits", []):
            lines.append(f"  - {c['short']} {c['subject']} ({c['author']}, {c['time']})")
        lines.append(f"- Files touched this session: {git.get('files_changed_total', 0)}"
                     + (" (list capped)" if git.get("files_changed_truncated") else ""))
        for p in git.get("files_changed", []):
            lines.append(f"  - {p}")
        du = git.get("diff_unstaged", {})
        ds = git.get("diff_staged", {})
        lines.append(f"- Unstaged diff: {du.get('files_changed', 0)} file(s), "
                     f"+{du.get('insertions', 0)} -{du.get('deletions', 0)}")
        lines.append(f"- Staged diff: {ds.get('files_changed', 0)} file(s), "
                     f"+{ds.get('insertions', 0)} -{ds.get('deletions', 0)}")
        if git.get("diff_base"):
            db = git["diff_base"]
            lines.append(f"- Diff vs {db['base']}: {db['files_changed']} file(s), "
                         f"+{db['insertions']} -{db['deletions']}")
    else:
        lines.append("- Git unavailable, so session changes could not be measured.")
    lines.append("")
    lines.append("## Verification status (as recorded on disk, not re-run)")
    if data.get("reports"):
        for rep in data["reports"]:
            lines.append(f"- {rep['path']} [{rep['kind']}] modified {rep.get('modified', 'unknown')}: "
                         f"{rep.get('summary', '')}")
    else:
        lines.append("- No verification reports found on disk (looked for GhostVerify, "
                     "GhostBench, GhostSlice ledger and bundle, and pytest cache files).")
    lines.append("")
    lines.append("## Open loops")
    if data.get("open_loops"):
        for lp in data["open_loops"]:
            lines.append(f"- {lp['detail']} (source: {lp['source']})")
    else:
        lines.append("- None found in the repo facts.")
    lines.append("")
    lines.append("## Next steps (drafted from the open loops, confirm before acting)")
    if data.get("next_steps"):
        for i, step in enumerate(data["next_steps"], 1):
            lines.append(f"{i}. {step['text']} (source: {step['source']})")
    else:
        lines.append("No next steps were derivable from repo facts.")
    lines.append("")
    lines.append("## Markers")
    by = markers.get("by_kind", {})
    parts = ", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "none"
    lines.append(f"Open markers: {markers.get('total', 0)} total ({parts}), from scanning "
                 f"{markers.get('files_scanned', 0)} text files (source: {markers.get('files_source', '')}).")
    if markers.get("docs_total"):
        lines.append(f"Of these, {markers.get('code_total', 0)} are in code files and "
                     f"{markers['docs_total']} are in documentation or fixture files. "
                     "Only the code ones are counted as open loops above; the others "
                     "are listed here so nothing is hidden.")
    for it in markers.get("items", []):
        text = f": {it['text']}" if it.get("text") else ""
        where = " (documentation/fixture)" if it.get("context") == "docs" else ""
        lines.append(f"- {it['file']}:{it['line']} [{it['kind']}]{where}{text}")
    if markers.get("truncated"):
        lines.append(f"- List capped at {len(markers.get('items', []))} of {markers.get('total', 0)} markers.")
    if markers.get("files_truncated"):
        lines.append(f"- File list capped: {markers.get('files_considered', 0)} project files, "
                     f"only the first {markers.get('files_limit', 0)} were scanned for markers; "
                     "files past the cap were not scanned.")
    lines.append("")
    lines.append("## Coverage and limits")
    for lim in data.get("limits", []):
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)


def write_pack(project: str, out_dir: str, since: str | None = None,
               base: str | None = None, force: bool = False) -> dict:
    """Build the data, write HANDOFF.md + handoff.json into ``out_dir`` only."""
    import json

    data = build_pack_data(project, since=since, base=base)
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "HANDOFF.md")
    json_path = os.path.join(out_dir, "handoff.json")
    if not force and (os.path.exists(md_path) or os.path.exists(json_path)):
        raise FileExistsError(
            f"pack files already exist in {out_dir}; pass --force to overwrite the two pack files"
        )
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(data))
    data["pack"] = {"dir": os.path.abspath(out_dir), "markdown": md_path, "json": json_path}
    return data
