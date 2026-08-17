#!/usr/bin/env python3
"""Read pending eval requests, and record verdicts on them.

    python tools/evals.py list                     what is waiting, in full
    python tools/evals.py record <key> <verdict> <confidence> "<reasoning>"

THE AGENT IS THE SESSION. There is no runner here and there must never be one.
Sending a pair "for eval" from the phone files a request; the next Claude Code
session reads it with `list`, judges it, and writes the verdict with `record`.
That costs nothing extra, because the reasoning happens in a conversation that
is already open and already paid for.

An earlier version shelled out to `claude -p` on a five-minute timer -- a
metered call per request, billed, unattended. That was deleted (con-006-1f03).
The mistake underneath it was reaching for a model to call while being the
model: everything these requests contain is already in the agent's context.
Nothing in this file opens a socket or spawns a process, and nothing should.

verdict     supersedes | related | unrelated | unsure
confidence  low | medium | high

Prefer `related` over `supersedes` when unsure. A wrong supersession silently
retires a rule that is still in force, and nobody notices until it was needed.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

REPOS = r"C:\Users\jarms\repos"
DECISIONS = os.path.join(REPOS, "cambium", ".cambium", "decisions.json")
XYLEM_HOME = os.path.join(os.path.expanduser("~"), ".xylem")
PENDING = os.path.join(XYLEM_HOME, "eval-requests", "pending")
DONE = os.path.join(XYLEM_HOME, "eval-requests", "done")
JOURNAL = os.path.join(XYLEM_HOME, "apply-journal.jsonl")

VERDICTS = ("supersedes", "related", "unrelated", "unsure")
CONFIDENCE = ("low", "medium", "high")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _fields(entry):
    keep = ("id", "kind", "status", "summary", "rule", "name", "problem",
            "why_chosen", "reason", "purpose", "what_we_tried", "tradeoffs",
            "scope", "hardness", "tags", "created_at")
    out = []
    for k in keep:
        v = entry.get(k)
        if not v:
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        out.append("  %-13s %s" % (k + ":", v))
    return "\n".join(out)


def load_decisions():
    base = {"dismissed_links": [], "law_citations": {}, "law_dismissed": {},
            "link_evals": {}}
    if os.path.exists(DECISIONS):
        try:
            with open(DECISIONS, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for k, v in base.items():
                    d.setdefault(k, v)
                return d
        except (OSError, ValueError):
            pass
    return base


def save_decisions(d):
    os.makedirs(os.path.dirname(DECISIONS), exist_ok=True)
    tmp = DECISIONS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DECISIONS)


def journal(rec):
    rec = dict(rec, at=_now())
    os.makedirs(XYLEM_HOME, exist_ok=True)
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def cmd_list(_args):
    if not os.path.isdir(PENDING):
        print("no eval requests pending.")
        return 0
    files = sorted(f for f in os.listdir(PENDING) if f.endswith(".json"))
    if not files:
        print("no eval requests pending.")
        return 0
    print("%d pending\n" % len(files))
    for fname in files:
        try:
            with open(os.path.join(PENDING, fname), encoding="utf-8") as f:
                req = json.load(f)
        except (OSError, ValueError) as e:
            print("  UNREADABLE %s (%s)\n" % (fname, e))
            continue
        print("=" * 72)
        print("key      %s" % req["key"])
        print("proposal %s may supersede %s   (project %s)"
              % (req["newer"], req["older"], req["project"]))
        print("\n--- NEWER: %s" % req["newer"])
        print(_fields(req["newer_entry"]))
        print("\n--- OLDER: %s" % req["older"])
        print(_fields(req["older_entry"]))
        print()
    print("=" * 72)
    print('record with:  python tools/evals.py record "<key>" <verdict> '
          '<confidence> "<reasoning>"')
    return 0


def cmd_record(args):
    if args.verdict not in VERDICTS:
        print("verdict must be one of: %s" % ", ".join(VERDICTS))
        return 1
    if args.confidence not in CONFIDENCE:
        print("confidence must be one of: %s" % ", ".join(CONFIDENCE))
        return 1
    if len(args.reasoning.strip()) < 40:
        # The verdict word is the cheap part. The reasoning is what a future
        # reader -- or a future you -- actually weighs, and a one-liner is
        # indistinguishable from not having read the entries.
        print("reasoning is too thin; cite the wording that decided it.")
        return 1

    dec = load_decisions()
    dec["link_evals"][args.key] = {
        "verdict": args.verdict,
        "confidence": args.confidence,
        "reasoning": args.reasoning.strip(),
        "model": args.by,
        "at": _now(),
    }
    save_decisions(dec)
    journal({"event": "eval", "key": args.key, "outcome": "ok",
             "verdict": args.verdict, "confidence": args.confidence,
             "by": args.by})

    # Retire the request if one was filed. Recording a verdict on a pair nobody
    # asked about is fine too -- the proposal is on the board either way.
    moved = False
    if os.path.isdir(PENDING):
        want = args.key.replace(":", "_") + ".json"
        src = os.path.join(PENDING, want)
        if os.path.exists(src):
            os.makedirs(DONE, exist_ok=True)
            shutil.move(src, os.path.join(DONE, want))
            moved = True

    print("recorded %s (%s) for %s%s"
          % (args.verdict, args.confidence, args.key,
             "" if moved else "  [no filed request; verdict stands anyway]"))
    print("run publish.ps1 (or wait for the 5-minute drain) to put it on the phone.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="print every pending request in full")
    r = sub.add_parser("record", help="record a verdict")
    r.add_argument("key", help="project:newer:older")
    r.add_argument("verdict", choices=VERDICTS)
    r.add_argument("confidence", choices=CONFIDENCE)
    r.add_argument("reasoning")
    r.add_argument("--by", default="claude-code session",
                   help="who judged it; shown on the card")
    args = ap.parse_args()
    return cmd_list(args) if args.cmd == "list" else cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
