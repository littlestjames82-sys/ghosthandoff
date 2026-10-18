# GhostHandoff

A session handoff pack for GhostSlice projects. When a working
session stops, GhostHandoff writes one small pack that says where
things stand: what branch, what changed, what is still open, and
what the next session should probably do first. The next agent or
person starts from the pack instead of re-reading the whole repo.

The pack is drafted from repo facts only. Every fact in it names
its source. Nothing in it is guessed, summarised by a model, or
carried out for you: the tool is propose-only, and it never commits,
pushes, sends, or edits anything in the project it describes.

## Quick start

```sh
ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>]
ghosthandoff show <pack-dir>
ghosthandoff mcp
```

- `pack` builds the pack and writes two files into the output
  directory: `HANDOFF.md` (for people and agents) and `handoff.json`
  (the same facts, machine readable). Default output is
  `./handoff-out` under your current directory, never inside the
  project unless you point `-o` there yourself.
- `show` prints a pack's HANDOFF.md.
- `mcp` serves two tools over stdio for MCP clients: `build_handoff`
  and `read_handoff`, with capped summary payloads.

Exit codes: 0 means the pack was built (a section can be degraded
and labelled, for example a project that is not a git repo still
gets a pack), 2 means the pack could not be built (the project path
is missing or unreadable).

## What is in the pack

- **State now.** Branch (or detached HEAD), short HEAD hash,
  upstream with ahead and behind counts, staged / unstaged /
  untracked file lists from git status, stash entries.
- **Changed this session.** Commits inside the session window,
  with hash, subject, author, and time, plus the files they
  touched, and working-tree diff stats for staged and unstaged
  changes separately. The window is printed on the pack. The
  default is the last 12 hours plus all uncommitted changes,
  because uncommitted work is part of the handoff no matter how
  old it is. `--since` accepts a duration (`2h`, `90m`, `3d`), an
  ISO date or datetime, or a git ref (then the session is
  `ref..HEAD`).
- **Verification status.** Report files the tool recognises
  (GhostVerify, GhostBench, GhostSlice ledger and bundles, pytest
  cache), each with its kind, path, modification time, and a short
  extract from the file itself: a verdict field, a first line, a
  failure count. A three-day-old report reads as three days old.
  Nothing is re-run to refresh it.
- **Open loops.** Only from the facts above: uncommitted files,
  unpushed commits, stash entries, TODO / FIXME / XXX / HACK
  markers in code files, a non-passing latest verdict, recorded
  test failures. Each loop names its source. (Markers found in
  documentation or fixture files are listed in the pack's Markers
  section, not counted as loops; see Honest limits.)
- **Next steps.** Short drafts generated from the open loops in a
  fixed priority order, each citing the fact it came from. If
  there are no loops, the pack says no next steps were derivable
  from repo facts. It never invents work.

## Safety, in plain words

- **Read-only on your project.** Git is driven with read-only
  subcommands and optional locks disabled, so git itself writes
  nothing back. The test suite hashes the described project's
  whole tree, `.git` included, before and after a pack run and
  requires the hashes to match exactly.
- **Propose-only.** There is no commit, push, send, or edit path
  anywhere in the tool. It writes the two pack files, only in the
  output directory.
- **It never runs your code.** No tests, no builds, no scripts
  from the described project. Git read-only commands and file
  reads are the whole surface.
- **Secrets stay out.** Marker lines and report excerpts are
  quoted truncated, and pass through a secret-shape redaction pass
  before they are written.
- **Local only.** Python standard library only, no network, no
  accounts, no telemetry.

## Honest limits

- "This session" is a heuristic. Git does not record session
  boundaries, so the window is a stated approximation, never an
  exact measurement.
- Marker scans have false positives. A TODO inside docs or
  fixtures matches too, so the pack splits markers by context:
  markers in documentation or fixture files are listed with file
  and line and subtotalled, but only markers in code files count
  as open loops or generate next steps. The split is conservative
  (a docs directory, a fixture directory, or a documentation file
  extension), and every marker is still listed so a reader can
  judge. Lists are capped, and the pack says when a cap was hit,
  including when the scan's file list itself was capped.
- Report discovery works by known file names and shapes. A
  verification result stored anywhere else will be missed, and
  the pack's coverage note says so.
- A pack is a snapshot from the moment it was built. It carries
  its build time on its face and goes stale right after; use
  GhostWatch if you need live staleness tracking.
- GhostHandoff captures one session at stop time. It does not
  learn across sessions (that is GhostReplay) and it is not a
  first-session orientation pack (that is GhostPrimer).

## Development

Zero-dependency Python (stdlib only), Python 3.10+.

```sh
PYTHONPATH=src python3 -m ghosthandoff pack <project>
python3 -m pytest tests -q
```

See `examples/` for a walkthrough that builds a fixture repo in a
known mid-session state and packs it. See `PLAN.md` for the full
design and the verification bar the test suite pins.
