# The Xylem workbench — everything, for an agent picking this up cold

This is a **private, phone-accessible review surface** for the memory the Xylem
suite accumulates. Its job is not to display data. Its job is to put the small
number of judgement calls that actually need a human in front of that human,
wherever they are, and then make the resulting decisions take effect on the PC.

Read this before changing anything here. The invariants at the bottom are not
style preferences; each one is a bug that already happened.

---

## 1. Where it sits

Three repos, three jobs:

| repo | role |
|---|---|
| **context-keeper** | The primitive. Typed entries — decision / constraint / pipeline — in each project's `.context/*.json`. One store per project. |
| **cambium** | The composer. Reads every named store, compiles derived tiers, and exports one JSON snapshot. Also holds the knowledge/law tier. |
| **xylem-dashboard** | This repo. A static site + a Cloudflare Worker + local tooling. Reads the snapshot, writes back intents. |

The dashboard **never talks to a store directly from the browser.** It reads a
committed JSON file and posts intents to a queue. Everything that touches a
store happens on the PC.

## 2. The tiers

Three levels, each computed from the one below:

1. **Entries** — source of truth. Hand-written, hand-editable, per project.
2. **Pages** — build artifacts. A page compiles from a set of entries and
   records the exact entry ids it used, a `compiled_at`, and each source's
   status and content hash at compile time. Pages are **deletable and fully
   regenerable**, and are never returned by any trust-tier read.
3. **Laws** (the concept tier) — written by *judgement*, not compiled. A law is
   a cross-project lesson living in cambium's knowledge store at local / team /
   org scope. Org-scope laws recall from every project and from mobile.

**Staleness is computed, never guessed.** A page is stale if any source entry is
superseded, deprecated, or has changed since `compiled_at`. The comparison is on
`(status, updated_at, content_hash)` with **the hash authoritative**, because the
stores are hand-editable and a backfill can move a timestamp on an entry whose
text never changed. The page reports *which* entry caused it.

A law's equivalent is **`unincorporated`**: entries carrying two or more of the
law's topic tags that the law does not cite. Non-empty means the corpus has
moved past the page. Two-tag overlap is a *hint*, not a finding — measured
precision on that class of signal is low, which is why every one of them is a
proposal a human rules on.

## 3. Data flow

```
.context/*.json (20 projects)
        │  cambium reads every NAMED project
        ▼
cambium_server.py  ──►  snapshot.json      (one file, committed)
        │                    │
        │                    ▼
        │            tools/build_dist.py   (ALLOWLIST → dist/)
        │                    │
        │                    ▼
        │            wrangler deploy → Cloudflare Worker
        │                                   │
        │                          token-gated URL  ──► phone
        │                                   │
        │                            taps a button
        │                                   ▼
        │                            KV queue (intents only)
        │                                   │
        └───────  tools/apply_queue.py  ◄────┘   (5-min Conductor worker)
                        │
                        └──► writes stores via context-keeper's own lifecycle path
```

The snapshot is **data**, so it is gitignored, as is `vault/` and `dist/`. The
site in this directory is code and is safe to publish; the snapshot is not.

## 4. The six views

`const VIEWS = ["lessons", "projects", "chains", "pages", "links", "quality"]`

- **lessons** — "what we've learned". The law tier. Each law shows its text, the
  projects it was seen in, what it cites, and its **candidate list** (topic
  matches it does not yet cite) with per-candidate actions. Only laws with
  candidates show buttons; look for the amber "N to review" chip. On a phone the
  candidate list stacks *below* the law body.
- **projects** — per-project entry counts by kind and status.
- **chains** — supersession edges as a graph. Dangling edges are drawn as such,
  because a store reaches that state on its own.
- **pages** — stale pages as cards (with the causing entry), everything else
  collapsed to one row per project. 427 pages would otherwise be 427 identical
  cards.
- **links** — proposed supersessions awaiting a ruling.
- **quality** — `verify_quality` gaps per project.

## 5. The workbench loop

This is the part that makes it a workbench rather than a dashboard.

**Every button queues an INTENT. Nothing in the browser writes anything.**

    tap → POST /api/queue → KV (keyed by subject, so deciding twice replaces)
        → apply_queue.py drains it on the PC
        → writes via context-keeper's own tools
        → publish.ps1 rebuilds + redeploys
        → phone reflects it

Four actions exist:

| action | meaning |
|---|---|
| `apply` | Make it so — supersede the entry, or cite the candidate in the law. |
| `dismiss` | No. Recorded permanently, so the proposal stops coming back. |
| `eval` | Have an agent read it properly and report back. Writes nothing. |
| `recompile` | Rebuild every stale page. Deterministic; no judgement involved. |

Kinds: `link` (a supersession pair), `candidate` (a law + an entry), `pages`
(the whole stale set). The Worker validates both kind and action — **adding a
kind without its action returns `bad action`**, which the 400 body states
plainly.

### Dismissals are judgement, not cache

`.cambium/decisions.json` holds `dismissed_links`, `law_citations`,
`law_dismissed`, `link_evals`, `law_evals`. A dismissed proposal stays dismissed
until explicitly reversed. A review surface that re-proposes what you already
rejected trains you to stop reading it.

## 6. The eval loop — and the mistake in it

**Send for eval** files a self-contained request under
`~/.xylem/eval-requests/pending/` carrying *both* entries (or the law and the
candidate) **in full**. Then:

```bash
python tools/evals.py list
```

prints every pending request completely, and

```bash
python tools/evals.py record "<key>" <verdict> <confidence> "<reasoning>"
```

records the ruling. The verdict lands on the card, and the button it implies is
**filled and tagged "recommended"**.

Verdicts differ by kind, because the question differs:

- link → `supersedes` | `related` | `unrelated` | `unsure`
- candidate → `cite` | `incidental` | `unsure`

`unsure` gets no Implement button and no recommendation. The honest response to
"I could not tell" is that a person must look.

> **THE AGENT IS THE SESSION.** There is no runner and there must never be one.
> The first version shelled out to a billed `claude -p` from a five-minute
> timer — a metered call per request, unattended. It was deleted, not disabled,
> because a flag that can be flipped is not a guarantee. The second attempt was
> to wire a local Ollama model, which was the same mistake in different clothes:
> everything an eval request contains is already in the agent's context. Read it
> and write the verdict. `tools/evals.py` opens no socket and spawns no process.
> See cambium `con-006-1f03` and the org-scope law it was promoted to.

Recompiling pages is the counter-example worth understanding: it is
**deterministic**, so it gets no agent at all. Asking a model to reproduce what a
compiler produces is slower, costs money, and can disagree with the compiler.

## 7. Security model

The dashboard carries every project's memory, including private repos and
local-only ones. Four independent gates:

1. **Path-token auth.** The site is served only under `/<token>/...`. Same model
   as the suite's other Workers.
2. **`run_worker_first = true`** in `wrangler.toml`. **Without this the gate does
   not exist** — Cloudflare serves static assets *before* the Worker, and the
   first deploy of this Worker served the full snapshot to the open internet for
   about four minutes. Never deploy data before the gate has been proven on a
   data-free build.
3. **Allowlist build.** `tools/build_dist.py` copies named files into `dist/`.
   Nothing travels because nothing excluded it.
4. **Gate verification on every publish.** `publish.ps1` fetches `/snapshot.json`,
   `/app.js` and `/` *without* the token and **throws** if any returns 200. A
   deploy that silently loses `run_worker_first` must fail loudly.

Also: `.cambium/` and `.context/` are gitignored here. Never track either in any
repo — they aggregate knowledge across every project on the machine.

## 8. Automation

A **Conductor worker ("Xylem Queue Drain", every 5 min)** runs
`tools/watch_queue.bat` → `watch_queue.ps1`, which:

- drains the queue (`apply_queue.py`)
- republishes **only** if something was applied (exit code **10**), because
  `publish.ps1` is a deploy plus a 15-second gate check and the queue is empty
  almost every tick
- holds a **lockfile**, because Conductor has no concurrent-run protection and
  two drains would back up a store the first had already rewritten

Everything on that timer is local and free. **Nothing there may call a billed
API.**

### Unattended safety

Before the **first** write of a run (not per item, so a run that dies halfway
restores to where it started):

- **backup** every affected store → `~/.xylem/queue-backups/<stamp>/`, kept to 40
- **journal** every action → `~/.xylem/apply-journal.jsonl`, append-only

Both live **outside every repo**: they are verbatim copies of other projects'
stores, and this is the repo that publishes.

12 of the 20 stores on this machine are **not tracked in git**, so for most
projects that backup is the only undo that exists.

## 9. Invariants — do not break these

1. **Never spend money.** No metered API, no billed CLI, never on a timer, and
   never offered as an option without its price attached.
2. **Never write to a store from the browser or the Worker.** Intents only.
3. **`run_worker_first = true`** stays in `wrangler.toml`, and the publish gate
   check stays in `publish.ps1`.
4. **Bump `?v=` in `index.html` AND `SHELL` AND `ASSETS` in `sw.js` together** on
   any `app.js`/`app.css` change. Sweep all of them at once — hand-picking
   patterns already missed the `ASSETS` array, which precached URLs the page
   never requests, so offline served an empty shell. Invisible online.
5. **Never track `.cambium/` or another project's `.context/` in any repo.**
6. **Pages are artifacts; laws are judgement.** Recompile pages freely. Never
   auto-write a supersession or a citation from a heuristic — an edge written
   from a guess silently retires a rule that may still be in force.
7. **Status colours are reserved.** A recommendation uses the series accent, not
   a status colour, and never colour alone.
8. **ASCII only in agentsync notes.** One non-ASCII byte bricks all coordination.

## 10. Gotchas that cost real time

- **The Browser pane runs read-only** (no Worker), so `actionBar` renders **zero**
  buttons on localhost. Stub `queueAvailable = true` before concluding a control
  is missing — and reload after editing `app.js`, or the pane keeps the old
  module.
- **A `<span>` ignores height and percentage width.** Meters, bars and dots need
  `display: block`/`inline-block`. Computed style will report the colour while
  nothing paints.
- **`$args` is an automatic variable in PowerShell.** Assigning to it silently
  gives you an argument list that is not the one you wrote.
- **A single em-dash kills a redirected `cp1252` pipe** with
  `UnicodeEncodeError`. Force stdout to UTF-8 in anything that runs unattended.
- **Cloudflare 403s urllib's default User-Agent.** Send an explicit one, or it
  reads as an auth failure and you go hunting the token.
- **Never bulk-edit repo text with PowerShell `Get-Content`/`Set-Content`** — it
  mangles em-dashes and adds a BOM.

## 11. Commands

```bash
python tools/evals.py list
```

```bash
python tools/apply_queue.py --dry-run
```

```bash
powershell -File .\publish.ps1
```

`publish.ps1` does all three steps — refresh the snapshot, assemble `dist/`,
deploy — and then **verifies the gate**, throwing if anything is served without
the token.
