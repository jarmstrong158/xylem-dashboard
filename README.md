# xylem-dashboard

A static, offline-capable view of the Xylem memory mesh: every project's
context-keeper entries, cambium's compiled pages and their staleness,
supersession chains, and verify_quality gaps.

No server, no build step, no dependencies, no network calls. The whole app is
`index.html` + `app.css` + `app.js` reading one file: `snapshot.json`.

## Why it is not on GitHub Pages

It holds your entire cross-project memory, including private repos and projects
with no remote. **A GitHub Pages site built from a private repo is still a
public website** — private Pages requires GitHub Enterprise Cloud. Publishing it
would also violate `con-015-12da` in context-keeper, which forbids committing
anything derived from other projects' `.context` stores to a public repo, and
the same reasoning that keeps `cambium/dashboard.html` gitignored.

So it is served from your own machine and reached over Tailscale. The data never
leaves the desktop.

## Generate the snapshot

Point cambium at the projects you want included — the map is explicit on
purpose, so a store can only be read because you named it:

```bash
cambium-mcp export-snapshot --out snapshot.json --bodies
```

`--bodies` includes entry titles, quality-gap summaries and issue detail. Without
it the snapshot carries ids, counts, statuses and edges only. Requires
`CAMBIUM_PROJECTS` (the project→path map) and, for the quality scan,
`CAMBIUM_CONTEXT_KEEPER` pointing at context-keeper's `server.py`. A project
whose quality scan could not run is shown as **not checked**, never as clean.

The payload carries no generated-at timestamp, so re-exporting an unchanged mesh
produces a byte-identical file.

## Serve it on the desktop

```bash
python -m http.server 8137 --directory .
```

Then open http://localhost:8137. Opening `index.html` directly via `file://`
will not work — the browser blocks the `fetch` of `snapshot.json`.

## Reach it from your phone

`tailscale serve` puts it on your tailnet with a real HTTPS certificate, which
is also what makes the app installable:

```bash
tailscale serve --bg 8137
```

`tailscale status` shows the URL (`https://<machine>.<tailnet>.ts.net`). Open it
on the phone, then **Add to Home Screen** — the manifest and service worker make
it launch standalone with an offline cache of the shell. The snapshot itself is
always fetched network-first, so an installed app never shows you a cached
snapshot while claiming it is current; it falls back to the last one only when
the phone is genuinely offline.

To stop sharing: `tailscale serve --https=443 off`.

## Regenerate the icons

```bash
python tools/gen_icons.py
```

## Committing it

The site is code and holds no memory content, so it is safe anywhere.
**`snapshot.json` is not** — it is gitignored here. If you want it synced across
machines, commit it to a private repo (`jarmstrong158/knowledge` is already
private and is cambium's org store), and do not enable Pages on that repo.
