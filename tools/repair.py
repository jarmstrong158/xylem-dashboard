#!/usr/bin/env python3
"""The repair pipeline: filed request -> plan -> authored fix -> proposal.

The workflow this completes:

  1. phone      tap "Send N for repair"            -> intent in the queue
  2. drain      apply_queue.py                     -> mechanical fixes applied
                                                      NOW, remainder filed
  3. session    repair.py plan <project>           -> a work file listing every
                                                      entry that needs authored
                                                      text, with its current
                                                      values and what is missing
  4. session    agent fills in the plan's blanks   -> judgement happens here,
                                                      inside a session that is
                                                      already paid for
  5. session    repair.py propose <plan>           -> writes repair_proposals
  6. phone      Apply / Not this on each card      -> the ruling
  7. drain      apply_queue.py                     -> writes the approved field

Stages 1, 2, 6 and 7 already existed. This file is 3 and 5 -- the part that was
being improvised with a throwaway script every time, which is why the same 273
gaps kept looking stuck.

    python tools/repair.py plan <project> [--limit N] [--only unused,legacy]
    python tools/repair.py propose <planfile> [--force]
    python tools/repair.py status

WHAT THIS WILL NOT DO. It never invents rationale. `plan` shows the text the
entry already carries so a fix can be written FROM it; an entry with nothing to
work from is listed as needing a human, not filled with plausible prose. And it
refuses outright to touch any entry carrying code_drift (con-018-f4f2): a write
there stamps verified_at and clears the drift flag without anyone re-reading the
code, which silences the warning by touching it.
"""

import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = r"C:\Users\jarms\repos"
DECISIONS = os.path.join(REPOS, "cambium", ".cambium", "decisions.json")
XYLEM_HOME = os.path.join(os.path.expanduser("~"), ".xylem")
PLANS = os.path.join(XYLEM_HOME, "repair-plans")
PENDING = os.path.join(XYLEM_HOME, "eval-requests", "pending")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# What an authored fix must supply, per issue type. Anything not listed here is
# either already handled mechanically in the drain, or needs a human decision
# this pipeline deliberately does not make (deprecate / re-scope / re-read code).
AUTHORS = {
    "unused":      ("retrieval_hints", "2-4 phrasings someone would search BEFORE knowing this entry's name"),
    "legacy":      ("problem|why_chosen", "split the preserved freeform rationale into what forced the decision and why this option won"),
    "thin_reason": ("purpose|why_chosen|reason", "state what the entry accomplishes that ad-hoc steps could not"),
    "no_tags":     ("tags", "2-4 lowercase hyphenated tags drawn from the entry's own words"),
    "enforcement_missing": ("enforced_by", "name the test or command that actually checks this rule"),
}
SOURCE_FIELDS = ("summary", "rule", "name", "problem", "why_chosen", "reason",
                 "purpose", "rationale", "what_we_tried", "tradeoffs",
                 "triggering_incident", "scope", "tags", "steps")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_decisions():
    base = {"repair_proposals": {}, "repair_dismissed": []}
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


def _entries(project):
    out = {}
    base = os.path.join(REPOS, project, ".context")
    for fn in ("decisions.json", "constraints.json", "pipelines.json"):
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for e in json.load(f):
                    out[e["id"]] = e
        except (OSError, ValueError):
            pass
    return out


def _gaps(project):
    """Flagged entries from the published snapshot -- the same list the app shows,
    so a plan can never disagree with the card that produced it."""
    try:
        with open(os.path.join(ROOT, "snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None
    for p in snap.get("projects", []):
        if p.get("name") == project:
            q = p.get("quality") or {}
            return (q.get("gaps") or []) if q.get("checked") else None
    return None


def cmd_plan(args):
    gaps = _gaps(args.project)
    if gaps is None:
        print("no quality data for %r in snapshot.json" % args.project)
        return 1
    only = set(args.only.split(",")) if args.only else set(AUTHORS)
    entries = _entries(args.project)

    rows, skipped_drift, needs_human = [], 0, []
    for g in gaps:
        types = {i["type"] for i in g.get("issues", [])}
        if "code_drift" in types:
            skipped_drift += 1
            continue
        want = sorted((types & set(AUTHORS)) & only)
        if not want:
            continue
        e = entries.get(g["id"])
        if not e:
            continue
        source = {k: e[k] for k in SOURCE_FIELDS if e.get(k)}
        if not source:
            needs_human.append(g["id"])
            continue
        rows.append({
            "id": g["id"],
            "issues": want,
            "asks": {AUTHORS[t][0]: AUTHORS[t][1] for t in want},
            "source": source,
            "authored": {},          # <- the agent fills this in
        })
        if len(rows) >= args.limit:
            break

    os.makedirs(PLANS, exist_ok=True)
    path = os.path.join(PLANS, "%s.json" % args.project.replace(" ", "_"))
    plan = {"project": args.project, "created_at": _now(), "entries": rows,
            "skipped_code_drift": skipped_drift, "needs_human": needs_human}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    print("plan: %s" % path)
    print("  %d entr(ies) to author, %d skipped for code_drift, %d with no source text"
          % (len(rows), skipped_drift, len(needs_human)))
    for r in rows:
        print("\n  --- %s  [%s]" % (r["id"], ", ".join(r["issues"])))
        for field, ask in r["asks"].items():
            print("      needs %-16s %s" % (field, ask))
        for k, v in list(r["source"].items())[:4]:
            print("      %-14s %s" % (k + ":", str(v).replace("\n", " ")[:150]))
    print("\nFill each entry's \"authored\" map, then:  python tools/repair.py propose %s"
          % path)
    return 0


def cmd_propose(args):
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    project = plan["project"]
    entries = _entries(project)
    dec = load_decisions()
    dec.setdefault("repair_proposals", {})

    wrote, skipped = 0, []
    for r in plan["entries"]:
        authored = r.get("authored") or {}
        if not authored:
            skipped.append((r["id"], "nothing authored"))
            continue
        e = entries.get(r["id"])
        if not e:
            skipped.append((r["id"], "entry no longer exists"))
            continue
        for field, value in authored.items():
            if value in (None, "", [], {}):
                skipped.append((r["id"], "%s is empty" % field))
                continue
            if e.get(field) == value and not args.force:
                skipped.append((r["id"], "%s unchanged" % field))
                continue
            key = "repair:%s:%s:%s" % (project, r["id"], field)
            dec["repair_proposals"][key] = {
                "project": project, "entry_id": r["id"], "field": field,
                "proposed": value, "at": _now(), "by": "claude-code session",
                "why": r.get("why") or ("Authored from the entry's own recorded text to "
                                        "clear: %s." % ", ".join(r["issues"])),
            }
            wrote += 1
    save_decisions(dec)
    print("proposed %d edit(s) for %s" % (wrote, project))
    for eid, why in skipped:
        print("  skipped %-18s %s" % (eid, why))
    print("\nThey appear on the project's quality card after the next publish.")
    return 0


def cmd_status(_args):
    filed = [f for f in os.listdir(PENDING) if f.endswith(".json")] \
        if os.path.isdir(PENDING) else []
    plans = [f for f in os.listdir(PLANS) if f.endswith(".json")] \
        if os.path.isdir(PLANS) else []
    dec = load_decisions()
    props = dec.get("repair_proposals") or {}
    open_plans = 0
    for p in plans:
        try:
            with open(os.path.join(PLANS, p), encoding="utf-8") as f:
                d = json.load(f)
            open_plans += sum(1 for e in d["entries"] if not e.get("authored"))
        except (OSError, ValueError):
            pass
    print("repair pipeline")
    print("  1-2 filed requests waiting          : %d" % len(filed))
    print("  3-4 plans open, entries unauthored  : %d across %d plan(s)"
          % (open_plans, len(plans)))
    print("  5-6 proposals awaiting your ruling  : %d" % len(props))
    print("  7   applied                         : see ~/.xylem/apply-journal.jsonl")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="build a work file for one project")
    pl.add_argument("project")
    pl.add_argument("--limit", type=int, default=40)
    pl.add_argument("--only", default="", help="comma list: %s" % ",".join(sorted(AUTHORS)))
    pr = sub.add_parser("propose", help="turn an authored plan into proposals")
    pr.add_argument("plan")
    pr.add_argument("--force", action="store_true")
    sub.add_parser("status", help="where every gap currently sits in the pipeline")
    args = ap.parse_args()
    return {"plan": cmd_plan, "propose": cmd_propose, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
