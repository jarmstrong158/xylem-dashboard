/* Renders snapshot.json. No network beyond that one same-origin file, no
   external libraries, no build step — everything here runs from the file the
   exporter wrote.

   The one editorial rule in this file: a thing that was NOT measured must never
   render as a thing that measured clean. A project whose verify_quality could
   not run shows an explicit "not checked" state, never an empty gap list. */

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function label(entry, bodies) {
  return bodies && entry && entry.title ? entry.title : (entry ? entry.id : "?");
}

/* Entry summaries are mini-narratives by design — the schema pushes for them —
   so a chain node shows a readable head and keeps the rest in the tooltip. */
function clamp(text, n = 110) {
  const s = String(text);
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

/* ---------------------------------------------------------------- banners */
function renderBanners(snap) {
  const out = [];
  if (!snap.includes_bodies) {
    out.push(`<div class="banner info"><strong>Ids only</strong>
      This snapshot carries no entry text. Re-export with
      <code>--bodies</code> to see titles and rationale summaries.</div>`);
  }
  const unchecked = snap.projects.filter((p) => !p.quality.checked);
  if (unchecked.length) {
    out.push(`<div class="banner"><strong>Quality not checked for
      ${plural(unchecked.length, "project", "projects")}</strong>
      ${esc(unchecked.map((p) => p.name).join(", "))} —
      ${esc(unchecked[0].quality.reason)}.
      These are shown as unknown, not as clean.</div>`);
  }
  if (snap.skipped_projects && snap.skipped_projects.length) {
    out.push(`<div class="banner"><strong>Skipped</strong>
      ${snap.skipped_projects.map((s) =>
        `${esc(s.name)} (${esc(s.reason)})`).join("; ")}</div>`);
  }
  $("#banners").innerHTML = out.join("");
}

/* ---------------------------------------------------------------- lessons */
/* The concept tier. One page per IDEA, drawn across every project — not one per
   project, which is the axis the rest of this dashboard uses and the wrong one
   for synthesis. Each law shows its evidence and, crucially, what the corpus
   has recorded since the law was written that it does not yet account for.
   That last number is the self-iteration signal: non-zero means the page is
   behind and an agent should recompile it, without anyone having to notice. */
function renderLessons(snap) {
  const L = snap.lessons || { laws: [] };
  if (!L.laws.length) {
    $("#view-lessons").innerHTML = `<p class="empty">No concept pages yet.
      Capture cross-project laws into cambium tagged <code>xylem-law</code>.</p>`;
    return;
  }
  const behind = L.needs_update || 0;
  const head = `<div class="banner ${behind ? "" : "info"}">
    <strong>${L.count} laws drawn across ${snap.projects.length} projects</strong>
    ${behind
      ? `${behind} ${behind === 1 ? "law has" : "laws have"} candidate evidence
         in the corpus they don't cite — listed first, worst first. That's the
         next compile's review list.`
      : `Every law cites all the evidence carrying its topics.`}
    </div>`;

  const cards = L.laws.map((law) => {
    const stale = law.unincorporated_count > 0;
    return `<article class="row">
      <div class="head">
        <span class="title">${esc(law.law)}</span>
        <span class="badge ${stale ? "stale" : "fresh"}">${
          stale ? `${law.unincorporated_count} new` : "current"}</span>
      </div>
      <div class="chips">
        <span class="chip">${esc(law.scope)}</span>
        ${law.topics.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}
        <span class="chip">${plural(law.cites.length, "citation", "citations")}</span>
        ${law.recalls ? `<span class="chip ok">${law.recalls} recalls</span>` : ""}
      </div>
      ${law.evidence ? `<div class="cause">${esc(law.evidence)}</div>` : ""}
      <div class="cause muted">
        Seen in: ${law.evidence_projects.map((p) => esc(p)).join(", ") || "—"}
      </div>
      ${stale ? `<div class="cause">
        <strong>Candidate evidence</strong> — carries this law's topics and is
        not cited by it. Some will be relevant, some won't; this is the review
        list, not a verdict:
        <div class="mono" style="margin-top:4px">${
          law.unincorporated.map((e) => `<code>${esc(e)}</code>`).join(" ")}${
          law.unincorporated_count > law.unincorporated.length
            ? ` <span class="muted">+${law.unincorporated_count - law.unincorporated.length} more</span>` : ""}
        </div></div>` : ""}
    </article>`;
  });
  $("#view-lessons").innerHTML = head + cards.join("");
}

/* --------------------------------------------------------------- projects */
function renderProjects(snap) {
  const cards = snap.projects.map((p) => {
    const st = p.counts.by_status || {};
    const q = p.quality;
    const qChip = q.checked
      ? `<span class="chip ${q.count ? "warn" : "ok"}">${plural(q.count, "quality gap", "quality gaps")}</span>`
      : `<span class="chip bad">quality not checked</span>`;
    /* "0 pages fresh" is a nonsense reading of "this project has no pages" —
       say which one it actually is. */
    const staleChip = p.stale_page_count
      ? `<span class="chip bad">${plural(p.stale_page_count, "stale page", "stale pages")}</span>`
      : p.pages.length
        ? `<span class="chip ok">${plural(p.pages.length, "page", "pages")} fresh</span>`
        : `<span class="chip">no pages</span>`;
    return `<article class="card">
      <h3>${esc(p.name)}</h3>
      <div class="big">${p.counts.total}</div>
      <div class="muted" style="font-size:.85rem">entries</div>
      <div class="chips">
        ${Object.entries(st).map(([k, v]) =>
          `<span class="chip">${esc(k)} ${v}</span>`).join("")}
      </div>
      <div class="chips">
        ${staleChip}
        ${qChip}
        <span class="chip">${plural((p.supersession_edges || []).length, "edge", "edges")}</span>
      </div>
    </article>`;
  });
  $("#view-projects").innerHTML = cards.length
    ? `<div class="grid">${cards.join("")}</div>`
    : `<p class="empty">No projects in the snapshot.</p>`;
}

/* ----------------------------------------------------------------- chains */
function buildChains(project) {
  /* Follow superseded_by from each root forward. A root is any node that
     supersedes something but nothing supersedes it. Nodes are visited once, so
     a cycle (possible if a store was hand-edited into one) terminates instead
     of hanging the page. */
  const edges = project.supersession_edges || [];
  if (!edges.length) return [];
  const byId = new Map((project.entries || []).map((e) => [e.id, e]));
  const next = new Map(edges.map((e) => [e.from, e]));
  const targets = new Set(edges.map((e) => e.to));
  const roots = edges.map((e) => e.from).filter((id) => !targets.has(id));
  const seen = new Set();
  const chains = [];
  for (const root of roots) {
    const chain = [];
    let cur = root;
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      const edge = next.get(cur);
      chain.push({ id: cur, entry: byId.get(cur), dangling: false });
      if (!edge) break;
      if (!next.has(edge.to)) {
        chain.push({ id: edge.to, entry: byId.get(edge.to),
                     dangling: edge.dangling });
        seen.add(edge.to);
        break;
      }
      cur = edge.to;
    }
    if (chain.length > 1) chains.push(chain);
  }
  return chains;
}

function renderChains(snap) {
  const blocks = snap.projects.map((p) => {
    const chains = buildChains(p);
    if (!chains.length) return "";
    const rows = chains.map((chain) => {
      const parts = chain.map((n, i) => {
        const cls = n.dangling ? "node missing"
          : (n.entry && n.entry.status === "superseded") ? "node superseded"
          : "node";
        const full = n.dangling
          ? `${n.id} (missing)`
          : label(n.entry, snap.includes_bodies);
        const arrow = i < chain.length - 1 ? `<span class="arrow">→</span>` : "";
        return `<span class="${cls}" title="${esc(n.id)} — ${esc(full)}">${
          esc(clamp(full))}</span>${arrow}`;
      });
      return `<div class="row"><div class="chain">${parts.join("")}</div></div>`;
    });
    return `<h3>${esc(p.name)}</h3>${rows.join("")}`;
  }).filter(Boolean);
  $("#view-chains").innerHTML = blocks.length
    ? blocks.join("")
    : `<p class="empty">No supersession edges recorded. Nothing has replaced
       anything yet — or reversals are landing as in-place edits.</p>`;
}

/* ------------------------------------------------------------------ pages */
function renderPages(snap) {
  const rows = [];
  for (const p of snap.projects) {
    for (const page of p.pages) {
      const causes = page.stale_causes || [];
      rows.push({ project: p.name, page, causes });
    }
  }
  rows.sort((a, b) => (b.causes.length - a.causes.length)
    || a.project.localeCompare(b.project));
  $("#view-pages").innerHTML = rows.length ? rows.map(({ project, page, causes }) => `
    <article class="row">
      <div class="head">
        <span class="title">${esc(page.title || page.id)}</span>
        <span class="badge ${page.stale ? "stale" : "fresh"}">
          ${page.stale ? "stale" : "fresh"}</span>
      </div>
      <div class="muted mono" style="font-size:.8rem">
        ${esc(project)} · ${esc(page.id)} ·
        ${plural(page.source_count, "source", "sources")} of
        ${page.candidate_count} active
      </div>
      ${causes.length ? `<div class="cause">Stale because:<ul>${
        causes.map((c) => `<li><code>${esc(c.entry_id)}</code> —
          ${esc(c.cause.replace(/_/g, " "))}: ${esc(c.detail)}</li>`).join("")
      }</ul></div>` : ""}
    </article>`).join("")
    : `<p class="empty">No pages compiled yet. Run
       <code>compile_project</code> to build them.</p>`;
}

/* ------------------------------------------------------------------ links */
function renderLinks(snap) {
  const blocks = snap.projects.map((p) => {
    const l = p.links || {};
    if (!l.checked) {
      return `<article class="row">
        <div class="head"><span class="title">${esc(p.name)}</span>
        <span class="badge stale">not surveyed</span></div>
        <div class="cause">${esc(l.reason || "not run")}</div></article>`;
    }
    if (!l.proposals.length) return "";
    const rows = l.proposals.map((r) => `<li>
      <code>${esc(r.newer_id)}</code> may supersede <code>${esc(r.older_id)}</code>
      ${r.tier === "likely" ? `<span class="badge stale">likely</span>` : ""}
      <div class="muted">${
        r.newer_summary ? esc(clamp(r.newer_summary, 90)) + "<br>replacing: "
                          + esc(clamp(r.older_summary || "", 90)) + "<br>" : ""
      }${(r.replacement_signals || []).length
          ? "evidence: " + esc(r.replacement_signals.join("; ")) + " · " : ""
      }overlap ${r.overlap_score ?? "?"}${
        r.shared_tags.length ? " · shares " + esc(r.shared_tags.join(", ")) : ""
      }</div></li>`);
    return `<article class="row">
      <div class="head"><span class="title">${esc(p.name)}</span>
        <span class="badge ${l.likely ? "stale" : ""}">${
          plural(l.count, "proposal", "proposals")}${
          l.likely ? `, ${l.likely} likely` : ""}</span></div>
      <div class="cause"><ul>${rows.join("")}</ul></div>
      ${l.unpaired_markers ? `<div class="cause muted">${
        plural(l.unpaired_markers, "entry says", "entries say")} something changed
        but no sibling was found to pair it with.</div>` : ""}
    </article>`;
  }).filter(Boolean);
  $("#view-links").innerHTML = (blocks.length ? blocks.join("") : "") +
    `<div class="banner info"><strong>Proposals only</strong>
      Nothing has been written to any store. <em>likely</em> means the newer
      entry names the older beside change language — measured 80% precision on
      34 hand-labelled pairs. Everything else shares a subject and nothing more,
      and a subject match is not a replacement: that signal measured 21.9%.
      Apply the ones you agree with via
      <code>deprecate_entry(old, reason, superseded_by=new)</code>.</div>`;
}

/* ---------------------------------------------------------------- quality */
function renderQuality(snap) {
  const blocks = snap.projects.map((p) => {
    const q = p.quality;
    if (!q.checked) {
      return `<article class="row">
        <div class="head"><span class="title">${esc(p.name)}</span>
        <span class="badge stale">not checked</span></div>
        <div class="cause">${esc(q.reason)}</div></article>`;
    }
    if (!q.gaps.length) {
      return `<article class="row">
        <div class="head"><span class="title">${esc(p.name)}</span>
        <span class="badge fresh">no gaps</span></div>
        ${q.drift_checked === false ? `<div class="cause">Drift was not
          checked (no work tree to compare against), so this is "no gaps found",
          not "nothing drifted".</div>` : ""}
      </article>`;
    }
    return `<article class="row">
      <div class="head"><span class="title">${esc(p.name)}</span>
      <span class="badge stale">${plural(q.gaps.length, "gap", "gaps")}</span></div>
      <div class="cause"><ul>${q.gaps.map((g) => `<li><code>${esc(g.id)}</code>
        ${g.summary ? esc(g.summary) + " — " : ""}
        <span class="muted">${esc((g.issues || [])
          .map((i) => i.detail ? `${i.type}: ${i.detail}` : i.type)
          .join(" · "))}</span></li>`).join("")}</ul></div>
    </article>`;
  });
  $("#view-quality").innerHTML = blocks.join("");
}

/* ------------------------------------------------------------------- boot */
function switchTo(view) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.view === view)));
  document.querySelectorAll(".view").forEach((v) =>
    v.hidden = v.id !== `view-${view}`);
  location.hash = view;
}

// Deep-linkable, so a law can be sent to someone (or to a future session).
window.addEventListener("hashchange", () => {
  const v = location.hash.replace("#", "");
  if (document.getElementById(`view-${v}`)) switchTo(v);
});

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => switchTo(t.dataset.view)));

fetch("snapshot.json", { cache: "no-store" })
  .then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  })
  .then((snap) => {
    const t = snap.totals || {};
    /* "0 quality gaps" is a lie when nothing was scanned — it is the exact
       reading the rest of this app exists to prevent, so the headline reports
       coverage before it reports a count. */
    const unchecked = t.projects_without_quality_check || 0;
    const quality = unchecked >= (t.projects || 0)
      ? "quality not checked"
      : `${t.quality_gaps || 0} quality gaps` +
        (unchecked ? ` (${unchecked} unchecked)` : "");
    $("#subtitle").textContent =
      `${plural(t.projects || 0, "project", "projects")} · ` +
      `${t.entries || 0} entries · ${t.stale_pages || 0}/${t.pages || 0} pages stale · ` +
      quality;
    $("#foot-note").textContent = snap.includes_bodies
      ? "Snapshot includes entry text — keep it private."
      : "Snapshot carries ids and counts only.";
    renderBanners(snap);
    renderLessons(snap);
    renderProjects(snap);
    renderChains(snap);
    renderPages(snap);
    renderLinks(snap);
    renderQuality(snap);
  })
  .catch((err) => {
    $("#subtitle").textContent = "Could not load snapshot.json";
    $("#banners").innerHTML = `<div class="banner"><strong>No snapshot</strong>
      ${esc(err.message)}. Generate one with
      <code>cambium-mcp export-snapshot --out snapshot.json</code>, and serve
      this directory over HTTP — opening index.html via file:// blocks the
      fetch.</div>`;
  });

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
