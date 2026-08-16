#!/usr/bin/env python3
"""Apply the decisions made on the phone.

The phone records INTENTS; nothing there touches a store. This is where they
become real, and it deliberately runs on the desktop through context-keeper's
own lifecycle path, so every write goes through the same code as a decision made
in a session.

    python tools/apply_queue.py --dry-run    # show what would happen
    python tools/apply_queue.py              # apply, then clear the queue

Two kinds of decision:

  link      apply    -> the older entry becomes `superseded`, pointing at the
                        newer one. Exactly what deprecate_entry/record supersedes
                        would write.
            dismiss  -> recorded locally so the survey stops proposing it.

  candidate apply    -> the entry id is added to the law's citation list, so the
                        concept tier stops reporting it as unincorporated.
            dismiss  -> recorded as "not relevant to this law", same effect on
                        the work list, opposite meaning.

Dismissals live in .cambium/decisions.json next to the other derived stores.
They are a record of judgement, not a cache: a dismissed pair stays dismissed
until you say otherwise, which is the whole point of having decided it once.
"""

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = r"C:\Users\jarms\repos"
CAMBIUM = os.path.join(REPOS, "cambium")
DECISIONS = os.path.join(CAMBIUM, ".cambium", "decisions.json")
BASE = "https://xylem-dashboard.jarmstrong158.workers.dev"

sys.path.insert(0, os.path.join(REPOS, "context-keeper"))


def token():
    p = os.path.join(os.path.expanduser("~"), ".xylem-dashboard-token")
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


# An explicit User-Agent, never urllib's default: Cloudflare answers
# `Python-urllib/3.x` with 403 before the Worker ever runs, which reads as an
# auth failure and sends you hunting the token. context-keeper's con-007 records
# the same lesson for its mirror.
UA = "xylem-dashboard-apply/1.0 (+local)"


def _open(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30)


def fetch_queue():
    with _open(f"{BASE}/{token()}/api/queue") as r:
        return json.loads(r.read().decode("utf-8")).get("items", [])


def clear_queue():
    with _open(f"{BASE}/{token()}/api/queue", "DELETE") as r:
        return json.loads(r.read().decode("utf-8"))


def load_decisions():
    if os.path.exists(DECISIONS):
        try:
            with open(DECISIONS, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("dismissed_links", [])
                d.setdefault("law_citations", {})
                d.setdefault("law_dismissed", {})
                return d
        except (OSError, json.JSONDecodeError):
            pass
    return {"dismissed_links": [], "law_citations": {}, "law_dismissed": {}}


def save_decisions(d):
    os.makedirs(os.path.dirname(DECISIONS), exist_ok=True)
    tmp = DECISIONS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DECISIONS)


def apply_link(item, dry):
    """The older entry becomes superseded, pointing at the newer one."""
    import server as ck
    project, older, newer = item["project"], item["older"], item["newer"]
    base_dir = os.path.join(REPOS, project, ".context")
    if not os.path.isdir(base_dir):
        return f"SKIP  {project}: no .context store"
    if dry:
        return f"would supersede {older} -> {newer}  ({project})"
    res = ck.handle_update_entry({
        "id": older, "project_dir": os.path.dirname(base_dir),
        "updates": {"status": "superseded", "superseded_by": newer},
    })
    if res.get("error"):
        return f"FAILED {older}: {res['error']}"
    return f"superseded {older} -> {newer}  ({project})"


def main():
    dry = "--dry-run" in sys.argv
    try:
        items = fetch_queue()
    except Exception as e:
        print("could not reach the queue:", e)
        return 1
    if not items:
        print("queue is empty — nothing decided on the phone since last run.")
        return 0

    dec = load_decisions()
    print("%d queued decision(s)%s\n" % (len(items), " (DRY RUN)" if dry else ""))
    applied = 0
    for it in sorted(items, key=lambda x: x.get("at", "")):
        kind, action = it.get("kind"), it.get("action")
        if kind == "link" and action == "apply":
            print("  " + apply_link(it, dry))
        elif kind == "link" and action == "dismiss":
            key = "%s:%s:%s" % (it.get("project"), it.get("newer"), it.get("older"))
            if not dry and key not in dec["dismissed_links"]:
                dec["dismissed_links"].append(key)
            print("  dismissed link %s -> %s (%s)"
                  % (it.get("newer"), it.get("older"), it.get("project")))
        elif kind == "candidate":
            law, entry = it.get("law"), it.get("older")
            bucket = "law_citations" if action == "apply" else "law_dismissed"
            if not dry:
                dec[bucket].setdefault(law, [])
                if entry not in dec[bucket][law]:
                    dec[bucket][law].append(entry)
            print("  %s %s for %s" % (
                "cite" if action == "apply" else "not relevant:", entry, law))
        else:
            print("  SKIP unknown decision:", it)
            continue
        applied += 1

    if dry:
        print("\nnothing written. Re-run without --dry-run to apply.")
        return 0

    save_decisions(dec)
    cleared = clear_queue()
    print("\napplied %d, queue cleared (%d keys)." % (applied, cleared.get("cleared", 0)))
    print("Run publish.ps1 to rebuild the snapshot so the phone reflects it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
