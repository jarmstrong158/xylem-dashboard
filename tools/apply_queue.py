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
def _base():
    """The deployed Worker's origin, read from disk beside the token.

    Not hard-coded, because this repo is public. The token is what actually
    gates the data and it has never been committed -- but publishing the
    address too means an attacker needs one secret instead of two, and the
    address costs nothing to keep out of the source. Set it with:

        echo https://<name>.<subdomain>.workers.dev > ~/.xylem-dashboard-base
    """
    p = os.path.join(os.path.expanduser("~"), ".xylem-dashboard-base")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip().rstrip("/")
    except OSError:
        raise SystemExit(
            "no Worker origin configured. Write it to %s (one line, "
            "https://...workers.dev)" % p)

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
    with _open(f"{_base()}/{token()}/api/queue") as r:
        return json.loads(r.read().decode("utf-8")).get("items", [])


def clear_queue():
    with _open(f"{_base()}/{token()}/api/queue", "DELETE") as r:
        return json.loads(r.read().decode("utf-8"))


# One place for the shape. `eval_pending` is what makes a filed-but-unjudged
# request visible on the card; everything else is a recorded ruling.
_EMPTY_DECISIONS = {"dismissed_links": [], "law_citations": {}, "law_dismissed": {},
                    "link_evals": {}, "law_evals": {}, "eval_pending": [],
                    "repair_proposals": {}, "repair_dismissed": []}


def load_decisions():
    if os.path.exists(DECISIONS):
        try:
            with open(DECISIONS, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for k, v in _EMPTY_DECISIONS.items():
                    d.setdefault(k, json.loads(json.dumps(v)))
                return d
        except (OSError, json.JSONDecodeError):
            pass
    return json.loads(json.dumps(_EMPTY_DECISIONS))


# Deletions travel as data, not as absence. save_decisions() applies these
# against fresh disk state.
_REMOVED = "__removed__"


def forget(dec, collection, item):
    """Record an intentional removal so a merge honours it."""
    dec.setdefault(_REMOVED, []).append((collection, item))


def save_decisions(d):
    """Write MERGED against whatever is on disk now, never blind.

    This file has several writers: a drain run that holds it open for its whole
    run, a session recording proposals, evals.py recording a verdict. A blind
    overwrite means last-write-wins on the WHOLE FILE, so a writer that loaded
    thirty seconds ago silently erases everything anyone else added meanwhile.

    That is not theoretical -- 24 repair proposals were written, then destroyed
    by a drain that had loaded before them and saved after, and the symptom was
    "I sent them for eval, where are they". Merging per collection keeps
    concurrent additions of DIFFERENT keys, which is the only conflict that
    actually occurs here.
    """
    os.makedirs(os.path.dirname(DECISIONS), exist_ok=True)
    disk = load_decisions()
    removals = d.pop(_REMOVED, [])
    merged = dict(disk)
    for key, ours in d.items():
        theirs = disk.get(key)
        if isinstance(ours, dict) and isinstance(theirs, dict):
            m = dict(theirs)
            m.update(ours)                 # add and overwrite, NEVER delete
            merged[key] = m
        elif isinstance(ours, list) and isinstance(theirs, list):
            keep = list(ours)
            for x in theirs:
                if x not in keep:
                    keep.append(x)         # union, never subtract
            merged[key] = keep
        else:
            merged[key] = ours
    # Deletions have to be stated, because absence cannot mean "remove": a
    # writer that loaded ten seconds ago is missing everything added since, and
    # treating that as intent to delete is precisely how 24 proposals vanished.
    for coll, item in removals:
        target = merged.get(coll)
        if isinstance(target, dict):
            target.pop(item, None)
        elif isinstance(target, list) and item in target:
            target.remove(item)
    tmp = DECISIONS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DECISIONS)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# An issue nothing can act on. `unused` is usage telemetry -- injected often,
# never retrieved -- and no edit clears it, so its presence must not hold a
# request open forever.
_UNACTIONABLE = frozenset(("unused",))


def sweep_finished_requests(dec):
    """Close every filed request whose work is done. Mechanical, so automatic.

    A request is finished when every entry in it either has a proposal waiting
    on a ruling, or carries only issues nothing can act on. Deciding that needs
    no judgement -- it is a set comparison -- so it belongs here rather than in
    a question to the user. Leaving it undone made finished work keep reading as
    outstanding, which is indistinguishable from the system having stalled."""
    if not os.path.isdir(EVAL_PENDING):
        return []
    answered = {(v.get("project"), v.get("entry_id"))
                for v in (dec.get("repair_proposals") or {}).values()}
    verdicts = set(dec.get("link_evals") or {}) | set(dec.get("law_evals") or {})
    closed = []
    for fname in sorted(os.listdir(EVAL_PENDING)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(EVAL_PENDING, fname)
        try:
            with open(path, encoding="utf-8") as f:
                req = json.load(f)
        except (OSError, ValueError):
            continue
        key = req.get("key")
        entries = req.get("entries")
        if entries:
            proj = req.get("project")
            # The live gap list is the truth, not the proposal ledger. A
            # proposal that was APPROVED is deleted when it applies, so judging
            # by proposals alone marks finished work as still outstanding --
            # exactly the state that made the app look stalled. An entry counts
            # as handled when it no longer carries an actionable issue, or has a
            # proposal waiting on a ruling.
            still = {}
            for g in (_quality_gaps_for(proj) or []):
                t = {i.get("type") for i in g.get("issues", [])} - _UNACTIONABLE
                if t:
                    still[g.get("id")] = t
            done = all(
                e.get("id") not in still or (proj, e.get("id")) in answered
                for e in entries)
        else:
            # a link or candidate request: finished once a verdict exists
            done = key in verdicts
        if not done:
            continue
        os.makedirs(EVAL_DONE, exist_ok=True)
        try:
            shutil.move(path, os.path.join(EVAL_DONE, fname))
        except OSError:
            continue
        if key in dec.get("eval_pending", []):
            dec["eval_pending"].remove(key)
            forget(dec, "eval_pending", key)
        closed.append(key)
    return closed


def resolve_eval(dec, key):
    """A ruling ends the question, so retire any eval request for it.

    Deciding a pair directly -- or acting on a verdict already given -- leaves
    its filed request outstanding otherwise, and the next reader spends real
    effort judging something that is already settled. The queue subject and the
    eval key are the same string for both kinds, which is what makes this a
    lookup rather than a reconstruction."""
    changed = False
    if key and key in dec.get("eval_pending", []):
        dec["eval_pending"].remove(key)
        forget(dec, "eval_pending", key)
        changed = True
    path = os.path.join(EVAL_PENDING, (key or "").replace(":", "_") + ".json")
    if key and os.path.exists(path):
        os.makedirs(EVAL_DONE, exist_ok=True)
        try:
            shutil.move(path, os.path.join(EVAL_DONE, os.path.basename(path)))
        except OSError:
            pass
        changed = True
    return changed


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
EVAL_DONE = os.path.join(XYLEM_HOME, "eval-requests", "done")


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


# One request per project rather than per entry: 325 flagged entries would be
# 325 taps and 325 files, and the repairs share context anyway -- the same tag
# vocabulary, the same scope paths, the same reason an entry went unused.
QUALITY_CAP = 40


def _quality_gaps_for(project):
    """A project's flagged entries, straight out of the published snapshot.

    verify_quality already did the analysis and, for the two mechanical classes,
    already names the fix -- `isolated` lists the exact ids to link and
    `global_scope` names the path it should carry. Re-deriving that here would
    be a second implementation that drifts from the one the dashboard shows."""
    try:
        with open(os.path.join(ROOT, "snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None
    for p in snap.get("projects", []):
        if p.get("name") != project:
            continue
        q = p.get("quality") or {}
        if not q.get("checked"):
            return None
        return q.get("gaps") or []
    return None


def _known_ids(project):
    ids = set()
    base = os.path.join(REPOS, project, ".context")
    for fn in ("decisions.json", "constraints.json", "pipelines.json"):
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                ids |= {e["id"] for e in json.load(f)}
        except (OSError, ValueError):
            pass
    return ids


def _mechanical_links(project, entry, known):
    """The related_to ids this entry can be repaired with, or None if it cannot.

    `isolated` is the one issue class that arrives with its fix computed, and
    related_to is additive -- it retires nothing, so writing it cannot silently
    demote a live rule the way a supersession edge could.

    Returns None when the entry must be READ instead: it has no isolated issue,
    it also carries code_drift (con-018-f4f2 -- update_entry stamps verified_at
    unconditionally, so writing here would clear a drift flag nobody checked),
    or none of the suggested ids resolve."""
    types = {i.get("type") for i in entry.get("issues", [])}
    if "isolated" not in types or "code_drift" in types:
        return None
    detail = next((i["detail"] for i in entry.get("issues", [])
                   if i.get("type") == "isolated"), "")
    if "[" not in detail:
        return None
    try:
        ids = json.loads(detail[detail.index("["):].replace("'", '"'))
    except ValueError:
        return None
    ids = [x for x in ids if x in known and x != entry.get("id")]
    return ids or None


def _derive_hints(entry):
    """Retrieval hints built from the entry's OWN words. Nothing invented.

    `unused` means the entry is injected into context repeatedly and never
    returned by a targeted query -- it is effectively unreachable by any phrasing
    except the one already in its summary. Three hints derived from its own text:
    the subject line, the identifiers it names, and its tags as a phrase. Every
    one is recoverable from the entry, so this cannot fabricate a claim the entry
    does not make, and mediocre hints beat none."""
    import re
    text = (entry.get("summary") or entry.get("rule") or entry.get("name") or "").strip()
    if not text:
        return None
    first = re.split(r"(?<=[.!?])\s", text)[0][:110].strip().rstrip(".")
    hints = [first.lower()] if first else []
    idents = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+"      # dotted.calls
        r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"                   # snake_case
        r"|[A-Za-z0-9_-]+/[A-Za-z0-9_./-]+", text)          # paths/like/this
    seen, keep = set(), []
    for i in idents:
        if len(i) < 4 or i.lower() in seen:
            continue
        seen.add(i.lower())
        keep.append(i)
    if keep:
        hints.append("how does %s work" % " ".join(keep[:3]))
    tags = [str(t) for t in (entry.get("tags") or []) if t]
    if len(tags) >= 2:
        hints.append(" ".join(tags[:4]).replace("-", " "))
    out = [h for h in hints if h and len(h) > 8][:4]
    return out or None


def _migrate_legacy(entry):
    """Move a pre-v0.4 entry's preserved freeform rationale into why_chosen.

    A verbatim copy, not a rewrite. The text already exists and already says why;
    it was simply sitting in a field nothing reads, which is the entire content
    of the `legacy` flag. Returns None when there is nothing to move, rather than
    inventing a rationale."""
    r = (entry.get("rationale") or "").strip()
    if not r or (entry.get("why_chosen") or "").strip():
        return None
    return r


def _repair_mechanical(project, gaps):
    """Apply every mechanical fix now. Returns (linked, entries still needing a read).

    An entry that had ONLY an isolated issue is fully repaired and drops off the
    list; one that had isolated plus something else stays, because the something
    else still needs prose."""
    import server as ck
    known = _known_ids(project)
    pdir = os.path.join(REPOS, project)
    linked, remaining = 0, []
    live = {}
    for fn in ("decisions.json", "constraints.json", "pipelines.json"):
        fp = os.path.join(pdir, ".context", fn)
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                for x in json.load(f):
                    live[x["id"]] = x
        except (OSError, ValueError):
            pass

    for e in gaps:
        types = {i.get("type") for i in e.get("issues", [])}
        # con-018-f4f2: any write stamps verified_at and clears the drift flag
        # without anyone re-reading the code. Never touch a drifted entry.
        if "code_drift" in types:
            remaining.append(e)
            continue
        entry = live.get(e.get("id")) or {}
        updates, cleared = {}, set()

        ids = _mechanical_links(project, e, known)
        if ids is not None:
            updates["related_to"] = ids
            cleared.add("isolated")

        if "unused" in types and not (entry.get("retrieval_hints") or []):
            hints = _derive_hints(entry)
            if hints:
                updates["retrieval_hints"] = hints
                cleared.add("unused")

        if "legacy" in types:
            why = _migrate_legacy(entry)
            if why:
                updates["why_chosen"] = why
                cleared.add("legacy")

        if not updates:
            remaining.append(e)
            continue
        res = ck.handle_update_entry({"id": e.get("id"), "project_dir": pdir,
                                      "updates": updates})
        if res.get("error"):
            remaining.append(e)
            continue
        linked += 1
        others = [i for i in e.get("issues", []) if i.get("type") not in cleared]
        if others:
            remaining.append(dict(e, issues=others))
    return linked, remaining


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


# Which issue types belong to which actionability bucket. Mirrors cambium's
# _classify_gap deliberately: the button counts what the drain will act on, so a
# card promising work the drain then declines is impossible by construction.
CLASS_TYPES = {
    "auto":    {"isolated", "unused", "legacy", "no_tags"},
    "review":  {"thin_reason", "global_scope", "enforcement_missing",
                "orphaned_scope", "mojibake"},
    "blocked": {"code_drift"},
}


def _all_projects_with_gaps():
    try:
        with open(os.path.join(ROOT, "snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for p in snap.get("projects", []):
        q = p.get("quality") or {}
        if q.get("checked") and (q.get("gaps") or []):
            out.append(p["name"])
    return out


def _quality_all(item, dec, dry):
    """Act on one actionability bucket across the whole mesh, from one tap.

    auto     applied here and now -- no judgement, so nothing waits on a person
    review   filed per project, narrowed to the issue types that need authored
             text; the next session picks them up from the SessionStart hook
    blocked  same, but the work is re-reading code against the entry, which is
             the one thing that must never be automated (con-018-f4f2)

    No model is called from this path and none may be (con-006-1f03). The two
    filing buckets prepare work; a session that is already open does it."""
    cls = (item.get("cls") or "").strip()
    if cls not in CLASS_TYPES:
        return "SKIP  unknown bucket %r" % cls, "skipped"
    projects = _all_projects_with_gaps()
    if not projects:
        return "SKIP  nothing flagged anywhere", "skipped"

    if cls == "auto":
        if dry:
            return "would repair %d project(s) mechanically" % len(projects), "dry-run"
        fixed, left = 0, 0
        for name in projects:
            gaps = _quality_gaps_for(name) or []
            n, rest = _repair_mechanical(name, gaps)
            fixed += n
            left += len(rest)
        return ("repaired %d entr(ies) across %d project(s), %d still need a person"
                % (fixed, len(projects), left)), "ok"

    wanted = CLASS_TYPES[cls]
    if dry:
        return "would file %s work for %d project(s)" % (cls, len(projects)), "dry-run"
    os.makedirs(EVAL_PENDING, exist_ok=True)
    # Mutate the caller's dict. Loading a second copy here and saving it meant
    # main()'s older copy overwrote it at the end of the run: the request files
    # landed on disk while eval_pending was wiped, so the app could never show
    # anything as sent. Two writers, last-write-wins, and the wrong one won.
    dec.setdefault("eval_pending", [])
    filed = 0
    for name in projects:
        gaps = [g for g in (_quality_gaps_for(name) or [])
                if {i.get("type") for i in g.get("issues", [])} & wanted]
        if not gaps:
            continue
        key = "quality-%s:%s" % (cls, name)
        payload = {"key": key, "eval_kind": "quality", "quality_class": cls,
                   "project": name, "flagged": len(gaps),
                   "entries": gaps[:QUALITY_CAP],
                   "capped": max(0, len(gaps) - QUALITY_CAP),
                   "requested_at": _now()}
        tmp = os.path.join(EVAL_PENDING, key.replace(":", "_") + ".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, os.path.join(EVAL_PENDING, key.replace(":", "_") + ".json"))
        if key not in dec["eval_pending"]:
            dec["eval_pending"].append(key)
        filed += 1
    return ("filed %s work for %d project(s); the next session picks it up"
            % (cls, filed)), "ok"


def file_eval(item, dec, dry):
    """Write a self-contained audit request. Touches no store.

    Two shapes, because the question differs. A LINK asks whether the newer
    entry replaced the older. A CANDIDATE asks whether a law should account for
    an entry it does not cite, and what would change if it did."""
    os.makedirs(EVAL_PENDING, exist_ok=True) if not dry else None

    if item.get("kind") == "quality" and (item.get("subject") or "").startswith("quality-all:"):
        return _quality_all(item, dec, dry)

    if item.get("kind") == "quality":
        project = item.get("project")
        gaps = _quality_gaps_for(project)
        if gaps is None:
            return f"SKIP  repair {project}: no quality data in snapshot.json", "skipped"
        if not gaps:
            return f"SKIP  repair {project}: nothing flagged", "skipped"
        if dry:
            # Real id set, not an empty one -- passing {} would resolve nothing
            # and report every entry as needing a read.
            known = _known_ids(project)
            mech = sum(1 for e in gaps
                       if _mechanical_links(project, e, known) is not None)
            return (f"would repair {project}: {mech} mechanical now, "
                    f"{len(gaps) - mech} filed for reading"), "dry-run"

        # Do the mechanical half HERE, not in a filed request. Applying the ids
        # verify_quality already computed is arithmetic, and arithmetic must not
        # wait on a person to open a session -- that was the whole complaint.
        # Only what genuinely needs an entry READ gets filed.
        linked, remaining = _repair_mechanical(project, gaps)
        if not remaining:
            return ("repaired %s: %d linked, nothing left to read"
                    % (project, linked)), "ok"
        key = "quality:%s" % project
        payload = {"key": key, "eval_kind": "quality", "project": project,
                   "flagged": len(remaining), "entries": remaining[:QUALITY_CAP],
                   "capped": max(0, len(remaining) - QUALITY_CAP),
                   "auto_linked": linked, "requested_at": _now()}
        label = ("repaired %s: %d linked automatically, %d filed for reading"
                 % (project, linked, len(remaining)))
    elif item.get("kind") == "candidate":
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

    # Record that it is AWAITING a verdict, or the request becomes invisible.
    # The queue is cleared the moment it drains, so without this the card reverts
    # to offering "Send for eval" again and the tap looks like it did nothing --
    # which is exactly how it read after 36 of them were filed successfully.
    # Same shared dict, same reason (see _quality_all).
    dec.setdefault("eval_pending", [])
    if key not in dec["eval_pending"]:
        dec["eval_pending"].append(key)
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


def apply_repair(item, dec, dry):
    """Apply one proposed edit to one entry, after a human approved it.

    The proposal carries the exact field and the exact new value, written when
    an agent read the entry. Nothing is recomputed here -- the tap approved a
    specific text, so a different text must not be what lands."""
    key = item.get("subject") or ""
    prop = (dec.get("repair_proposals") or {}).get(key)
    if not prop:
        return f"SKIP  repair {key}: no such proposal", "skipped"
    project, eid = prop.get("project"), prop.get("entry_id")
    field, value = prop.get("field"), prop.get("proposed")
    if dry:
        return f"would set {field} on {eid} ({project})", "dry-run"
    import server as ck
    # __reverify is the resolution for code_drift: an agent read the entry
    # against the code that moved and found it still accurate. update_entry
    # stamps verified_at and verified_sha on any write, so an empty update is
    # exactly "re-verified, nothing changed" -- and it only ever happens after a
    # human approves the reasoning on the card, which is what makes it a ruling
    # rather than the silent flag-clear con-018-f4f2 forbids.
    updates = {} if field == "__reverify" else {field: value}
    res = ck.handle_update_entry({"id": eid,
                                  "project_dir": os.path.join(REPOS, project),
                                  "updates": updates})
    if res.get("error"):
        return f"FAILED {eid}: {res['error']}", "failed:" + str(res["error"])[:120]
    dec["repair_proposals"].pop(key, None)
    forget(dec, "repair_proposals", key)
    return f"repaired {eid}.{field}  ({project})", "ok"


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
    except Exception as e:                       # noqa: BLE001 - report, never crash
        # The queue is remote; the sweep is not. A DNS blip or a dropped link
        # should not also stop finished requests being retired, or local work
        # sits looking outstanding until the network happens to come back.
        print("could not reach the queue:", e)
        try:
            dec = load_decisions()
            swept = sweep_finished_requests(dec)
            if swept:
                save_decisions(dec)
                print("  (offline) closed %d finished request(s)" % len(swept))
        except Exception as inner:               # noqa: BLE001
            print("  sweep also failed:", inner)
        return 1
    if not items:
        # Still sweep. Requests are answered BETWEEN drains -- a session writes
        # proposals while the queue is empty -- so gating the sweep on inbound
        # taps means finished work waits for unrelated activity to retire it.
        dec = load_decisions()
        swept = sweep_finished_requests(dec)
        if swept:
            save_decisions(dec)
            print("closed %d finished request(s): %s"
                  % (len(swept), ", ".join(swept[:4])
                     + ("..." if len(swept) > 4 else "")))
            journal({"event": "sweep", "closed": swept})
            return 10                    # republish so the app reflects it
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
        key_ = it.get("subject") or ""
        rec = {"event": "apply", "kind": kind, "action": action,
               "subject": it.get("subject"), "stamp": stamp,
               "queued_at": it.get("at")}
        if kind == "link" and action == "apply":
            msg, outcome = apply_link(it, dry)
            print("  " + msg)
            rec.update(project=it.get("project"), older=it.get("older"),
                       newer=it.get("newer"), outcome=outcome)
        elif kind == "repair":
            if action == "dismiss":
                if not dry and key_ not in dec["repair_dismissed"]:
                    dec["repair_dismissed"].append(key_)
                    dec["repair_proposals"].pop(key_, None)
                    forget(dec, "repair_proposals", key_)
                msg, outcome = f"declined repair {key_}", "ok"
            else:
                msg, outcome = apply_repair(it, dec, dry)
            print("  " + msg)
            rec.update(outcome=outcome, subject=key_)
        elif kind == "pages":
            msg, outcome = recompile_stale(it, dry)
            print("  " + msg)
            rec.update(outcome=outcome)
        elif action == "eval":
            # Both kinds route here. Must stay ABOVE the candidate branch below,
            # which handles only apply/dismiss.
            msg, outcome = file_eval(it, dec, dry)
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
            # A ruling settles the question; retire any eval request still open
            # on it. Not for action == "eval", which is what CREATES one.
            if action in ("apply", "dismiss"):
                resolve_eval(dec, it.get("subject"))
            journal(rec)
        applied += 1

    if dry:
        print("\nnothing written. Re-run without --dry-run to apply.")
        return 0

    # Retire requests whose work is finished, every run. Nobody should have to
    # ask for this: it is a set comparison, and skipping it left completed work
    # reading as outstanding.
    swept = sweep_finished_requests(dec)
    if swept:
        print("  closed %d finished request(s): %s"
              % (len(swept), ", ".join(swept[:4])
                 + ("..." if len(swept) > 4 else "")))
        journal({"event": "sweep", "closed": swept, "stamp": stamp})
        applied += len(swept)

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
