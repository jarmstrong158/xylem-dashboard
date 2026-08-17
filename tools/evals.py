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

Two kinds of request, because two different questions get sent here:

  link       key project:newer:older   did the newer entry REPLACE the older?
             verdicts: supersedes | related | unrelated | unsure
             Prefer `related` when unsure. A wrong supersession silently retires
             a rule that is still in force, and nobody notices until it was
             needed.

  candidate  key law:entry             should this LAW account for this entry?
             verdicts: cite | incidental | unsure
             `cite` means the law is genuinely behind the corpus and the entry
             belongs in it; say in the reasoning WHAT the law should absorb, not
             just that it should. `incidental` means they share topic tags and
             nothing else, which is the common case -- the work list is built
             from a two-tag overlap, which is a hint, not a finding.

confidence   low | medium | high
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

# A link asks "did this replace that". A law candidate asks "should this law
# account for this entry". Different questions, so different words -- one shared
# vocabulary would force both into vague verdicts that fit neither.
LINK_VERDICTS = ("supersedes", "related", "unrelated", "unsure")
CANDIDATE_VERDICTS = ("cite", "incidental", "unsure")
VERDICTS = tuple(sorted(set(LINK_VERDICTS + CANDIDATE_VERDICTS)))
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
            "link_evals": {}, "law_evals": {}, "eval_pending": []}
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
    """Delegate to apply_queue's merging writer.

    A second blind writer on the same file reintroduces exactly the bug that
    destroyed 24 proposals: whoever saves last wins the whole file, so a verdict
    recorded here would erase proposals written seconds earlier by something
    else."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_aq_save", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "apply_queue.py"))
    aq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aq)
    aq.save_decisions(d)


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
        if req.get("eval_kind") == "quality":
            print("question repair the flagged entries in %s" % req["project"])
            print("         %d flagged%s" % (req["flagged"],
                  (", showing %d" % len(req["entries"])) if req.get("capped") else ""))
            print("         fix with context-keeper update_entry, then:")
            print('         python tools/evals.py done "%s" "<what you changed>"' % req["key"])
            counts = {}
            for e in req["entries"]:
                for i in e.get("issues", []):
                    counts[i.get("type")] = counts.get(i.get("type"), 0) + 1
            print("         issue mix: %s" % ", ".join(
                "%s=%d" % kv for kv in sorted(counts.items(), key=lambda x: -x[1])))
            for e in req["entries"]:
                print("\n  --- %s (%s)" % (e.get("id"), e.get("type")))
                print("      %s" % (e.get("summary") or "")[:200])
                for i in e.get("issues", []):
                    print("      [%s] %s" % (i.get("type"), (i.get("detail") or "")[:300]))
        elif req.get("eval_kind") == "candidate":
            law = req["law"]
            print("question does law %s need to account for %s?  (project %s)"
                  % (law.get("id"), req["entry_id"], req.get("project")))
            print("verdicts %s" % " | ".join(CANDIDATE_VERDICTS))
            print("\n--- LAW %s [%s]  recalls=%s"
                  % (law.get("id"), law.get("scope"), law.get("recalls")))
            print("  topics:  %s" % ", ".join(law.get("topics") or []))
            print("  cites:   %s" % ", ".join(law.get("cites") or []) or "(none)")
            print("  law:\n%s" % "\n".join(
                "      " + ln for ln in (law.get("law") or "").splitlines()))
            if law.get("evidence"):
                print("  why:\n%s" % "\n".join(
                    "      " + ln for ln in law["evidence"].splitlines()))
            print("\n--- CANDIDATE ENTRY: %s" % req["entry_id"])
            print(_fields(req["entry"]))
        else:
            print("question did %s replace %s?   (project %s)"
                  % (req["newer"], req["older"], req["project"]))
            print("verdicts %s" % " | ".join(LINK_VERDICTS))
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
    # A candidate key is law:entry (one colon); a link key is project:newer:older
    # (two). The shape picks the bucket, so a verdict cannot land where the
    # renderer will not look for it.
    is_candidate = args.key.count(":") == 1
    allowed = CANDIDATE_VERDICTS if is_candidate else LINK_VERDICTS
    if args.verdict not in allowed:
        print("%s key takes one of: %s"
              % ("candidate (law:entry)" if is_candidate else "link (project:newer:older)",
                 ", ".join(allowed)))
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
    # The verdict IS the answer, so the request stops being outstanding.
    if args.key in dec.get("eval_pending", []):
        dec["eval_pending"].remove(args.key)
        dec.setdefault("__removed__", []).append(("eval_pending", args.key))
    bucket = "law_evals" if is_candidate else "link_evals"
    dec.setdefault(bucket, {})
    dec[bucket][args.key] = {
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


def cmd_done(args):
    """Retire a repair request once the entries have actually been fixed.

    A quality repair has no verdict -- the proof is the gap count dropping on
    the next publish, which is a better signal than any word recorded here. All
    this does is close the request and leave a note saying what was changed, so
    the same 40 entries are not read again next session."""
    dec = load_decisions()
    if args.key in dec.get("eval_pending", []):
        dec["eval_pending"].remove(args.key)
        dec.setdefault("__removed__", []).append(("eval_pending", args.key))
        save_decisions(dec)
    name = args.key.replace(":", "_") + ".json"
    src = os.path.join(PENDING, name)
    if not os.path.exists(src):
        print("no pending request with key %s" % args.key)
        return 1
    os.makedirs(DONE, exist_ok=True)
    shutil.move(src, os.path.join(DONE, name))
    journal({"event": "repair", "key": args.key, "outcome": "done",
             "note": args.note.strip(), "by": args.by})
    print("closed %s" % args.key)
    print("run publish.ps1 to see the gap count move.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="print every pending request in full")
    dn = sub.add_parser("done", help="close a repair request after fixing it")
    dn.add_argument("key")
    dn.add_argument("note")
    dn.add_argument("--by", default="claude-code session")
    r = sub.add_parser("record", help="record a verdict")
    r.add_argument("key", help="project:newer:older")
    r.add_argument("verdict", choices=VERDICTS)
    r.add_argument("confidence", choices=CONFIDENCE)
    r.add_argument("reasoning")
    r.add_argument("--by", default="claude-code session",
                   help="who judged it; shown on the card")
    args = ap.parse_args()
    return {"list": cmd_list, "done": cmd_done, "record": cmd_record}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
