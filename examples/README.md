# GhostHandoff examples: the fixture repo walkthrough

This walkthrough builds a small git repository in a known
mid-session state, packs a handoff from it, and shows what the pack
says. Everything is local; nothing leaves your machine.

## 1. Build the demo repo

```sh
python3 make_fixture_repo.py ./demo-project
```

The script creates a repo with:

- branch `feature/handoff-fixture`
- an old commit dated 2026-10-11 (outside the default window),
  plus two fresh commits (inside it)
- one staged change (CHANGELOG.md), one unstaged change
  (README.md), one untracked file (scratch.py)
- one stash entry
- three markers: a TODO in pricing.py, a FIXME in app.py, a TODO
  in scratch.py
- a `verify-report.json` and `VERIFY.md` recording a failing
  GhostVerify verdict

## 2. Pack the handoff

```sh
ghosthandoff pack ./demo-project -o ./pack-out
```

Output from a real run:

```text
Handoff pack written: ./pack-out/HANDOFF.md
Machine copy:         ./pack-out/handoff.json
Commits in window: 2, files touched: 7, markers: 3, reports: 2, open loops: 5, next steps: 6
```

Two files land in `./pack-out`, and nowhere else. The demo repo is
byte-identical afterwards; the test suite hashes the whole tree,
`.git` included, to prove it.

## 3. Read the pack

```sh
ghosthandoff show ./pack-out
```

The top of HANDOFF.md from the same run:

```text
# Handoff: demo-project

Drafted by GhostHandoff 0.1.0 from repo facts ... Propose-only:
nothing was committed, sent, or changed in the project. Every fact
names its source. Anything not found is stated as not found.

## State now
- Branch: feature/handoff-fixture (HEAD 832f9d8)
- Upstream: none recorded
- Working tree: 1 staged, 1 unstaged, 3 untracked
- Stash: 1 entry

## Changed this session
Window: last 12 hours (default) plus all uncommitted changes
- Commits in window: 2
  - 832f9d8 Wire pricing into the app entry point (Fixture Dev, ...)
  - 178cefa Add pricing module (Fixture Dev, ...)
```

(Commit hashes and timestamps differ per run; the shape does not.)

What to check against the repo you just built:

- The two in-window commits are listed; the 2026-10-11 commit is
  not. Run `git log --oneline` in demo-project and compare.
- The verification section quotes the failing verdict from
  verify-report.json with the file's modification time. Nothing
  was re-run to get it.
- Open loops counts five: uncommitted work, untracked files, the
  stash entry, the open markers, the failing verdict. Each names
  its source.
- Next steps are drafted from those loops, in a fixed order, each
  citing the fact it came from. They are proposals for the next
  session to confirm, not instructions the tool carried out.

## 4. Widen the window

```sh
ghosthandoff pack ./demo-project -o ./pack-wide --since 4d
```

Now the 2026-10-11 commit is inside the window and appears in the
session commits. `--since` also accepts an ISO date or a git ref
(then the session is `ref..HEAD`).

## 5. A folder that is not a repo

```sh
mkdir plain && printf 'notes\nTODO: water the plants\n' > plain/notes.txt
ghosthandoff pack ./plain -o ./pack-plain
```

Still exit 0. The git section reads "unavailable", and the marker
in notes.txt is still found and listed.
