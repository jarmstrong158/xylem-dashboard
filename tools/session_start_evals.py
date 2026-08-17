#!/usr/bin/env python3
"""SessionStart hook: surface eval requests sent from the phone.

This is what makes "send for eval" automatic without spending anything.

The tension it resolves: work that runs with NO session open has to spawn
something, and spawning something is a billed call (con-006-1f03). Work that
runs INSIDE an open session is free, but somebody has to notice there is work.
So the noticing is what gets automated: the moment any Claude Code session
starts, anywhere, the pending requests are put in front of the agent. The user
never has to ask, and no separate agent is ever launched.

Prints NOTHING when the queue is empty, so it costs an empty session nothing but
a stat call. Never raises -- a hook that breaks session start is worse than a
hook that silently does not fire.
"""

import json
import os
import sys

PENDING = os.path.join(os.path.expanduser("~"), ".xylem",
                       "eval-requests", "pending")
SHOW = 8


def main():
    try:
        names = [f for f in sorted(os.listdir(PENDING)) if f.endswith(".json")]
    except OSError:
        return 0
    if not names:
        return 0

    rows = []
    for name in names[:SHOW]:
        try:
            with open(os.path.join(PENDING, name), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if r.get("eval_kind") == "candidate":
            rows.append("  %s  should law %s account for %s?"
                        % (r["key"], r["law"].get("id"), r["entry_id"]))
        else:
            rows.append("  %s  did %s replace %s?"
                        % (r["key"], r.get("newer"), r.get("older")))

    out = [
        "[Xylem workbench] %d eval request(s) sent from the phone are waiting "
        "on a verdict." % len(names),
        "",
        "These were queued by the user tapping 'Send for eval'. Each carries "
        "both entries IN FULL, so no lookup and no tool is needed -- read and "
        "judge them yourself, in this session. Do NOT spawn an agent or call "
        "any model to do it (cambium con-006-1f03).",
        "",
    ] + rows
    if len(names) > SHOW:
        out.append("  ... and %d more" % (len(names) - SHOW))
    out += [
        "",
        "  python tools/evals.py list      (full text of every request)",
        '  python tools/evals.py record "<key>" <verdict> <confidence> "<why>"',
        "",
        "  link verdicts:      supersedes | related | unrelated | unsure",
        "  candidate verdicts: cite | incidental | unsure",
        "",
        "Prefer 'related' over 'supersedes', and 'incidental' over 'cite', when "
        "unsure: a wrong supersession silently retires a rule that is still in "
        "force. Then run publish.ps1 so the phone sees the verdicts.",
    ]
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                    # noqa: BLE001 - never break session start
        sys.exit(0)
