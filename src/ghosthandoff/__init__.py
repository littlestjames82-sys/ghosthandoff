"""GhostHandoff: session handoff packs drafted from repo facts only.

Propose-only. Builds HANDOFF.md + handoff.json describing a project's
state at stop time (git state, session changes, verification status,
open loops, next steps). Never commits, never sends, never edits the
project it describes, never runs project code. Stdlib only.
"""

__version__ = "0.1.0"
TOOL = "ghosthandoff"
