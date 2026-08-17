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
            eval     -> files a self-contained audit request under
                        ~/.xylem/eval-requests/pending/ and writes NOTHING else.
                        run_evals.py picks it up, and its verdict comes back as
                        a recommendation on the card -- the tap still rules.

  candidate apply    -> the entry id is added to the law's citation list, so the
                        concept tier stops reporting it as unincorporated.
            dismiss  -> recorded as "not relevant to this law", same effect on
                        the work list, opposite meaning.

Dismissals live in .cambium/decisions.json next to the other derived stores.
They are a record of judgement, not a cache: a dismissed pair stays dismissed
until you say otherwise, which is the whole point of having decided it once.

SAFE TO RUN UNATTENDED, which is a stronger claim than "works" and is what the
backup and the journal buy:

  ~/.xylem/queue-backups/<stamp>/<project>/*.json   every affected store, copied
                                                    before the first write
  ~/.xylem/apply-journal.jsonl                      append-only, one line per
                                                    action, never rewritten

Both sit outside every repo on purpose (see BACKUPS). The review gate is still
the tap on the phone -- a human read both entries and ruled on the pair. What
changes when this runs on a timer is only that the token alone now reaches the
stores, with nobody at the keyboard to notice a bad edge. The backup is what
makes that recoverable and the journal is what makes it visible.

EXIT CODES:  0 nothing applied   10 applied (caller should republish)   1 error
"""

import datetime
import glob
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = r"C:\Users\jarms\repos"
CAMBIUM = os.path.join(REPOS, "cambium")
DECISIONS = os.path.join(CAMBIUM, ".cambium", "decisions.json")
BASE = "https://xylem-dashboard.jarmstrong158.workers.dev"

# Backups and the journal live OUTSIDE every repo, deliberately.
#
# A backup is a verbatim copy of some other project's store, and this repo is
# the one that publishes. Writing them under xylem-dashboard/ would put
# cross-project store content on a git path and make the allowlist in
# build_dist.py the only thing standing between it and a deploy. ~/.xylem is
# already the machine's non-repo Xylem state (the session pointer lives there),
# so it keeps that content off every git path at once (con-015-12da).
XYLEM_HOME = os.path.join(os.path.expanduser("~"), ".xylem")
BACKUPS = os.path.join(XYLEM_HOME, "queue-backups")
JOURNAL = os.path.join(XYLEM_HOME, "apply-journal.jsonl")

sys.path.insert(0, os.path.join(REPOS, "context-keeper"))

# Unattended, stdout is a redirected pipe, and on Windows that means cp1252 --
# where a single em-dash in a print raises UnicodeEncodeError and takes the
# whole drain down. It cost nothing to hit interactively, because a console
# that can render it never complained.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


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


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def backup_store(project, stamp):
    """Copy a project's entry files before anything writes to them.

    12 of the 20 stores on this machine are NOT tracked in git, so for most
    projects a bad write has no undo at all. Run by hand that was survivable:
    the output is on screen, and a wrong supersession is obvious and fixable
    while you still remember what you meant. On a timer nobody is watching, and
    the first sign of a bad edge is a rule that quietly stopped being served.

    So the copy is the price of unattending it. It is a few hundred KB and it
    turns every auto-apply back into something reversible."""
    src = os.path.join(REPOS, project, ".context")
    if not os.path.isdir(src):
        return None
    dst = os.path.join(BACKUPS, stamp, project)
    os.makedirs(dst, exist_ok=True)
    n = 0
    for path in glob.glob(os.path.join(src, "*.json")):
        shutil.copy2(path, os.path.join(dst, os.path.basename(path)))
        n += 1
    return {"project": project, "files": n, "path": dst} if n else None


def backup_decisions(stamp):
    """The dismissals file is a record of judgement, not a cache -- losing it
    means every pair you already said no to comes back and asks again."""
    if not os.path.exists(DECISIONS):
        return None
    dst = os.path.join(BACKUPS, stamp, "_cambium")
    os.makedirs(dst, exist_ok=True)
    shutil.copy2(DECISIONS, os.path.join(dst, "decisions.json"))
    return {"project": "_cambium", "files": 1, "path": dst}


def prune_backups(keep=40):
    """Bounded history. A drain on a two-minute timer would otherwise fill the
    disk with snapshots of a store nobody changed."""
    try:
        dirs = sorted(d for d in os.listdir(BACKUPS)
                      if os.path.isdir(os.path.join(BACKUPS, d)))
    except OSError:
        return
    for old in dirs[:-keep]:
        shutil.rmtree(os.path.join(BACKUPS, old), ignore_errors=True)


def journal(rec):
    """Append-only record of what was applied while nobody was looking.

    stdout was enough when a human ran this and read the result. Scheduled, it
    goes to a pipe and vanishes, so the store changes and nothing anywhere says
    what changed it. One JSON object per line, never rewritten -- if a bad edge
    turns up weeks later this is what says when it landed and which backup
    predates it."""
    rec = dict(rec, at=_now())
    os.makedirs(XYLEM_HOME, exist_ok=True)
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print("  (journal write failed: %s)" % e)
    return rec


EVAL_PENDING = os.path.join(XYLEM_HOME, "eval-requests", "pending")


def _entry_text(project, entry_id):
    """The whole entry, straight out of the store.

    The audit prompt carries the entries VERBATIM rather than pointing an agent
    at the store, so the eval run needs no tools, no MCP and no filesystem
    reach. That is not a convenience: an auditor that can open the store is an
    auditor that can change it, and this one is supposed to read and report."""
    base = os.path.join(REPOS, project, ".context")
    for fname in ("decisions.json", "constraints.json", "pipelines.json"):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for e in json.load(f):
                    if e.get("id") == entry_id:
                        return e
        except (OSError, ValueError):
            continue
    return None


def _find_entry_anywhere(entry_id):
    """(project, entry) for an id, searched across every store.

    A law candidate is queued with its project attached, but an intent queued
    before that field existed has none, and guessing wrong files a request
    describing the wrong entry."""
    for name in sorted(os.listdir(REPOS)):
        if not os.path.isdir(os.path.join(REPOS, name, ".context")):
            continue
        e = _entry_text(name, entry_id)
        if e is not None:
            return name, e
    return None, None


def _law_text(law_id):
    """The law as the dashboard last published it.

    Read from snapshot.json rather than cambium's scoped stores because that is
    the artifact whose law text the reviewer is actually looking at on the
    phone. It can trail the store by one publish; the entry it is weighed
    against is read live, and the request records both so a stale pairing is
    visible rather than silent."""
    path = os.path.join(ROOT, "snapshot.json")
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None
    for law in ((snap.get("lessons") or {}).get("laws") or []):
        if law.get("id") == law_id:
            return {k: law.get(k) for k in
                    ("id", "scope", "law", "topics", "cites", "evidence",
                     "evidence_projects", "recalls")}
    return None


def file_eval(item, dry):
    """Write a self-contained audit request. Touches no store.

    Two shapes, because the question differs. A LINK asks whether the newer
    entry replaced the older. A CANDIDATE asks whether a law should account for
    an entry it does not cite, and what would change if it did."""
    os.makedirs(EVAL_PENDING, exist_ok=True) if not dry else None

    if item.get("kind") == "candidate":
        law_id, entry_id = item.get("law"), item.get("older")
        law = _law_text(law_id)
        if law is None:
            return f"SKIP  eval {law_id}: law not in snapshot.json", "skipped"
        project = item.get("project")
        entry = _entry_text(project, entry_id) if project else None
        if entry is None:
            project, entry = _find_entry_anywhere(entry_id)
        if entry is None:
            return f"SKIP  eval {law_id}/{entry_id}: entry not found", "skipped"
        if dry:
            return f"would file eval {entry_id} -> law {law_id}", "dry-run"
        key = "%s:%s" % (law_id, entry_id)
        payload = {"key": key, "eval_kind": "candidate", "law_id": law_id,
                   "law": law, "project": project, "entry_id": entry_id,
                   "entry": entry, "requested_at": _now()}
        label = f"filed for eval {entry_id} -> law {law_id}  ({project})"
    else:
        project, older, newer = item.get("project"), item.get("older"), item.get("newer")
        a, b = _entry_text(project, newer), _entry_text(project, older)
        if a is None or b is None:
            missing = ", ".join(x for x, e in ((newer, a), (older, b)) if e is None)
            return f"SKIP  eval {newer}->{older}: entry not found ({missing})", "skipped"
        if dry:
            return f"would file eval {newer} -> {older}  ({project})", "dry-run"
        key = "%s:%s:%s" % (project, newer, older)
        payload = {"key": key, "eval_kind": "link", "project": project,
                   "older": older, "newer": newer, "requested_at": _now(),
                   "newer_entry": a, "older_entry": b}
        label = f"filed for eval {newer} -> {older}  ({project})"

    name = key.replace(":", "_") + ".json"
    tmp = os.path.join(EVAL_PENDING, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(EVAL_PENDING, name))
    return label, "ok"


def _cambium_env():
    """The environment cambium's config reads.

    Mirrors publish.ps1's map deliberately, including its rule: a store travels
    because it is NAMED here, never because nothing excluded it."""
    projects = {n: os.path.join(REPOS, n) for n in sorted(os.listdir(REPOS))
                if os.path.isfile(os.path.join(REPOS, n, ".context",
                                               "decisions.json"))}
    return {
        "CAMBIUM_PROJECTS": json.dumps(projects),
        "CAMBIUM_REPO": CAMBIUM,
        "CAMBIUM_AGENT_ID": "jonny-desktop",
        "CAMBIUM_ORG_REPO": os.path.join(REPOS, "knowledge"),
        "CAMBIUM_CONTEXT_KEEPER": os.path.join(REPOS, "context-keeper", "server.py"),
    }


def recompile_stale(item, dry):
    """Rebuild every stale page. Deterministic, local, and free.

    A page is a build artifact: its body is regenerated from the entries it
    cites, so "stale" means the sources moved, not that anyone must decide
    anything. There is no agent in this path and there must not be one -- asking
    a model to reproduce what a compiler produces is slower, costs money, and
    can disagree with the compiler.

    Idempotent, so a repeated intent is harmless: recompiling an unchanged store
    leaves body and source fingerprints identical and only moves compiled_at."""
    if dry:
        return "would recompile every stale page", "dry-run"
    os.environ.update(_cambium_env())
    sys.path.insert(0, CAMBIUM)
    try:
        import cambium_server as cb
    except ImportError as e:
        return f"FAILED recompile: cannot import cambium_server ({e})", "failed"
    try:
        res = json.loads(cb.recompile(all_stale=True))
    except Exception as e:                      # noqa: BLE001 - report, never crash the drain
        return f"FAILED recompile: {e}", "failed:" + str(e)[:120]
    if res.get("error"):
        return f"FAILED recompile: {res['error']}", "failed:" + str(res["error"])[:120]
    rows = res.get("results") or res.get("pages") or []
    changed = sum(1 for p in rows if p.get("changed"))
    return ("recompiled %d stale page(s), %d changed" % (len(rows), changed)), "ok"


def apply_link(item, dry):
    """The older entry becomes superseded, pointing at the newer one."""
    import server as ck
    project, older, newer = item["project"], item["older"], item["newer"]
    base_dir = os.path.join(REPOS, project, ".context")
    if not os.path.isdir(base_dir):
        return f"SKIP  {project}: no .context store", "skipped"
    if dry:
        return f"would supersede {older} -> {newer}  ({project})", "dry-run"
    res = ck.handle_update_entry({
        "id": older, "project_dir": os.path.dirname(base_dir),
        "updates": {"status": "superseded", "superseded_by": newer},
    })
    if res.get("error"):
        return f"FAILED {older}: {res['error']}", "failed:" + str(res["error"])[:120]
    return f"superseded {older} -> {newer}  ({project})", "ok"


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
    items = sorted(items, key=lambda x: x.get("at", ""))
    print("%d queued decision(s)%s\n" % (len(items), " (DRY RUN)" if dry else ""))

    # Back up BEFORE the first write, and back up every affected store at once.
    # Per-item backups would leave a run that dies halfway recoverable only to
    # some midpoint nobody chose; this restores to exactly where the drain
    # started.
    stamp = _stamp()
    if not dry:
        targets = {it.get("project") for it in items
                   if it.get("kind") == "link" and it.get("action") == "apply"}
        backed = [b for b in (backup_store(p, stamp)
                              for p in sorted(t for t in targets if t)) if b]
        d = backup_decisions(stamp)
        if d:
            backed.append(d)
        if backed:
            print("  snapshot: %s (%d store(s))\n"
                  % (os.path.join(BACKUPS, stamp), len(backed)))
            journal({"event": "backup", "stamp": stamp,
                     "stores": [b["project"] for b in backed]})

    applied = 0
    for it in items:
        kind, action = it.get("kind"), it.get("action")
        rec = {"event": "apply", "kind": kind, "action": action,
               "subject": it.get("subject"), "stamp": stamp,
               "queued_at": it.get("at")}
        if kind == "link" and action == "apply":
            msg, outcome = apply_link(it, dry)
            print("  " + msg)
            rec.update(project=it.get("project"), older=it.get("older"),
                       newer=it.get("newer"), outcome=outcome)
        elif kind == "pages":
            msg, outcome = recompile_stale(it, dry)
            print("  " + msg)
            rec.update(outcome=outcome)
        elif action == "eval":
            # Both kinds route here. Must stay ABOVE the candidate branch below,
            # which handles only apply/dismiss.
            msg, outcome = file_eval(it, dry)
            print("  " + msg)
            rec.update(project=it.get("project"), older=it.get("older"),
                       newer=it.get("newer"), law=it.get("law"), outcome=outcome)
        elif kind == "link" and action == "dismiss":
            key = "%s:%s:%s" % (it.get("project"), it.get("newer"), it.get("older"))
            if not dry and key not in dec["dismissed_links"]:
                dec["dismissed_links"].append(key)
            print("  dismissed link %s -> %s (%s)"
                  % (it.get("newer"), it.get("older"), it.get("project")))
            rec.update(project=it.get("project"), older=it.get("older"),
                       newer=it.get("newer"), outcome="dry-run" if dry else "ok")
        elif kind == "candidate":
            law, entry = it.get("law"), it.get("older")
            bucket = "law_citations" if action == "apply" else "law_dismissed"
            if not dry:
                dec[bucket].setdefault(law, [])
                if entry not in dec[bucket][law]:
                    dec[bucket][law].append(entry)
            print("  %s %s for %s" % (
                "cite" if action == "apply" else "not relevant:", entry, law))
            rec.update(law=law, entry=entry, bucket=bucket,
                       outcome="dry-run" if dry else "ok")
        else:
            print("  SKIP unknown decision:", it)
            journal(dict(rec, outcome="skipped-unknown"))
            continue
        if not dry:
            journal(rec)
        applied += 1

    if dry:
        print("\nnothing written. Re-run without --dry-run to apply.")
        return 0

    save_decisions(dec)
    cleared = clear_queue()
    prune_backups()
    print("\napplied %d, queue cleared (%d keys)." % (applied, cleared.get("cleared", 0)))
    print("journal:  %s" % JOURNAL)
    print("restore:  copy %s\\<project>\\*.json back over that project's .context\\"
          % os.path.join(BACKUPS, stamp))
    journal({"event": "drain", "stamp": stamp, "applied": applied,
             "cleared": cleared.get("cleared", 0)})
    # 10, not 0: the caller republishes only when something actually changed.
    # wrangler deploy plus the gate check is ~45s, and a drain on a two-minute
    # timer is empty almost every time it runs.
    return 10 if applied else 0


if __name__ == "__main__":
    sys.exit(main())
