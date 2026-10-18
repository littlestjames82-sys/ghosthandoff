"""Marker scan and verification-report discovery.

Both are pure reads: marker lines are quoted (redacted, truncated),
reports are summarised from what is already on disk. Nothing in the
described project is executed, ever.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from .redact import clean_line

MARKER_RE = re.compile(r"(?<![A-Za-z0-9_])(TODO|FIXME|XXX|HACK)\b[:\s-]*(.*)")
MAX_FILE_BYTES = 512 * 1024

# A marker's context decides whether it counts as an open loop. Only
# unambiguous documentation or fixture locations are "docs": a docs /
# doc / documentation or fixture directory segment, or a documentation
# file extension (.md and kin, wherever the file lives). Everything
# else is "code". The split is deliberately conservative: a marker is
# never down-weighted on a guess, and docs-context markers are still
# listed in the pack with file and line, only subtotalled separately.
DOCS_DIRS = {"docs", "doc", "documentation"}
FIXTURE_DIRS = {"fixtures", "fixture", "testdata", "test_data", "__fixtures__"}
DOCS_EXTS = {".md", ".markdown", ".rst", ".adoc"}


def marker_context(rel: str) -> str:
    """Classify a project-relative path as ``"code"`` or ``"docs"``."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    for seg in parts[:-1]:
        low = seg.lower()
        if low in DOCS_DIRS or low in FIXTURE_DIRS:
            return "docs"
    if parts and os.path.splitext(parts[-1])[1].lower() in DOCS_EXTS:
        return "docs"
    return "code"


def scan_markers(project: str, files: list[str], max_markers: int = 200,
                 max_files: int = 20000) -> dict:
    """Scan ``files`` (relative to project) for TODO/FIXME/XXX/HACK markers."""
    items: list[dict] = []
    total = 0
    by_kind: dict[str, int] = {}
    code_total = 0
    docs_total = 0
    code_by_kind: dict[str, int] = {}
    docs_by_kind: dict[str, int] = {}
    scanned = 0
    for rel in files[:max_files]:
        full = os.path.join(project, rel)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_FILE_BYTES:
                continue
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue  # binary, skip
        scanned += 1
        context = marker_context(rel)
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            m = MARKER_RE.search(line)
            if not m:
                continue
            kind = m.group(1)
            total += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if context == "docs":
                docs_total += 1
                docs_by_kind[kind] = docs_by_kind.get(kind, 0) + 1
            else:
                code_total += 1
                code_by_kind[kind] = code_by_kind.get(kind, 0) + 1
            if len(items) < max_markers:
                items.append({
                    "file": rel,
                    "line": lineno,
                    "kind": kind,
                    "context": context,
                    "text": clean_line(m.group(2) or "", 140),
                })
    return {
        "total": total,
        "by_kind": by_kind,
        "code_total": code_total,
        "docs_total": docs_total,
        "code_by_kind": code_by_kind,
        "docs_by_kind": docs_by_kind,
        "items": items,
        "truncated": total > len(items),
        "files_scanned": scanned,
        "files_considered": len(files),
        "files_limit": max_files,
        "files_truncated": len(files) > max_files,
    }


def _iso_mtime(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
    except OSError:
        return ""


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _first_verdict_line(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if ln.strip():
                    return clean_line(ln, 160)
    except OSError:
        pass
    return ""


def discover_reports(project: str, max_bundles: int = 20) -> list[dict]:
    """Find verification evidence already on disk. Summaries only."""
    reports: list[dict] = []

    def add(kind: str, rel: str, summary: str, extra: dict | None = None):
        entry = {
            "kind": kind,
            "path": rel,
            "modified": _iso_mtime(os.path.join(project, rel)),
            "summary": summary,
        }
        if extra:
            entry.update(extra)
        reports.append(entry)

    # GhostVerify machine verdict
    vr = os.path.join(project, "verify-report.json")
    if os.path.isfile(vr):
        data = _read_json(vr)
        verdict = None
        if isinstance(data, dict):
            for key in ("verdict", "status", "result", "ok"):
                if key in data:
                    verdict = data[key]
                    break
        summary = f"verdict field: {verdict}" if verdict is not None else "present, no verdict field parsed"
        add("ghostverify-report", "verify-report.json", clean_line(summary, 160),
            {"verdict": verdict})

    # GhostVerify human report
    vm = os.path.join(project, "VERIFY.md")
    if os.path.isfile(vm):
        add("ghostverify-md", "VERIFY.md", _first_verdict_line(vm))

    # GhostBench report (any of the common names, root level)
    for name in ("bench-report.json", "BENCH.md", "bench-results.json"):
        p = os.path.join(project, name)
        if os.path.isfile(p):
            if name.endswith(".json"):
                data = _read_json(p)
                keys = sorted(data.keys())[:6] if isinstance(data, dict) else []
                add("ghostbench-report", name,
                    clean_line("keys: " + ", ".join(keys) if keys else "present, unparsed", 160))
            else:
                add("ghostbench-report", name, _first_verdict_line(p))
            break

    # GhostSlice history ledger tail
    ledger = os.path.join(project, ".ghostslice-history.jsonl")
    if os.path.isfile(ledger):
        last = ""
        count = 0
        try:
            with open(ledger, "r", encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if ln.strip():
                        last = ln.strip()
                        count += 1
        except OSError:
            pass
        entry = _read_json_from_str(last)
        keys = sorted(entry.keys())[:6] if isinstance(entry, dict) else []
        add("ghostslice-ledger", ".ghostslice-history.jsonl",
            clean_line(f"{count} entries; last entry keys: " + ", ".join(keys), 160))

    # pytest lastfailed cache: counts only, recorded failures from the last run
    lf = os.path.join(project, ".pytest_cache", "v", "cache", "lastfailed")
    if os.path.isfile(lf):
        data = _read_json(lf)
        n = len(data) if isinstance(data, dict) else 0
        add("pytest-lastfailed", ".pytest_cache/v/cache/lastfailed",
            f"{n} test(s) recorded failing in the last pytest run",
            {"failing_count": n})

    # GhostSlice bundles: folders holding manifest.json, top two levels
    bundles: list[str] = []
    try:
        for name in sorted(os.listdir(project)):
            full = os.path.join(project, name)
            if os.path.isdir(full):
                if os.path.isfile(os.path.join(full, "manifest.json")):
                    bundles.append(name)
                else:
                    try:
                        for sub in sorted(os.listdir(full)):
                            if os.path.isfile(os.path.join(full, sub, "manifest.json")):
                                bundles.append(f"{name}/{sub}")
                    except OSError:
                        pass
    except OSError:
        pass
    for rel in bundles[:max_bundles]:
        data = _read_json(os.path.join(project, rel, "manifest.json"))
        files_n = None
        if isinstance(data, dict):
            files_field = data.get("files")
            if isinstance(files_field, list):
                files_n = len(files_field)
        add("ghostslice-bundle", rel,
            f"GhostSlice bundle manifest ({files_n} files listed)" if files_n is not None
            else "GhostSlice bundle manifest (unparsed)")

    reports.sort(key=lambda r: r["path"])
    return reports


def _read_json_from_str(text: str):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None
