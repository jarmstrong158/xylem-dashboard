/* Renders snapshot.json. No network beyond that one same-origin file, no
   external libraries, no build step.

   Two editorial rules run through this file:
     1. A thing that was NOT measured must never render as a thing that measured
        clean. Unknown gets its own state, never a zero.
     2. Status colour never carries meaning alone and never sits behind text —
        it is a dot beside an ink label. The validated palette puts status-warning
        at 1.79:1 on the light surface, so a visible label is obligatory, and
        text stays in text tokens rather than series colour. */

const $ = (sel) => document.querySelector(sel);

/* ?theme=dark|light forces a theme, overriding the OS preference. Both palettes
   are selected sets rather than an automatic flip, so each needs to be viewable
   on demand — otherwise the one you are not currently running is unverifiable. */
(() => {
  const t = new URLSearchParams(location.search).get("theme");
  if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
})();

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const clamp = (t, n = 110) => {
  const s = String(t);
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
};
function label(entry, bodies) {
  return bodies && entry && entry.title ? entry.title : (entry ? entry.id : "?");
}

/* A state is always dot + word. `tone` is good | warn | bad | unknown. */
function state(tone, text) {
  return `<span class="state"><span class="dot ${esc(tone)}"></span>${esc(text)}</span>`;
}

/* Horizontal bars, one hue for every bar. Projects and issue types are nominal
   categories, and a value-ramp on nominal categories double-encodes bar length
   as lightness while burning the only free channel. Values are direct-labelled,
   so the chart is its own table. */
function bars(rows, opts) {
  const o = opts || {};
  const max = Math.max(1, ...rows.map((r) => r.value));
  const shown = o.limit ? rows.slice(0, o.limit) : rows;
  const rest = rows.length - shown.length;
  const body = shown.map((r) => `
    <div class="bar-row">
      <span class="name" title="${esc(r.name)}">${esc(r.name)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${
        Math.max(1.5, (r.value / max) * 100)}%"></span></span>
      <span class="val">${r.value}</span>
    </div>`).join("");
  const tail = rest > 0
    ? `<div class="bar-row"><span class="name muted">+${rest} more</span>
         <span></span><span class="val muted">${
           rows.slice(shown.length).reduce((a, b) => a + b.value, 0)}</span></div>`
    : "";
  return `<div class="bars">${body}${tail}</div>`;
}

function meter(fraction, tone) {
  const pct = Math.max(0, Math.min(100, fraction * 100));
  return `<span class="meter-track"><span class="meter-fill ${esc(tone)}"
    style="width:${pct.toFixed(1)}%"></span></span>`;
}

/* ------------------------------------------------------------------- KPIs */
function renderKpis(snap) {
  const t = snap.totals || {};
  const L = snap.lessons || { count: 0, needs_update: 0 };
  const pages = t.pages || 0;
  const stale = t.stale_pages || 0;
  const uncheckedQ = t.projects_without_quality_check || 0;
  const allUnchecked = uncheckedQ >= (t.projects || 0) && (t.projects || 0) > 0;

  const tiles = [
    {
      label: "Laws",
      value: L.count,
      foot: L.needs_update
        ? { tone: "warn", text: `${L.needs_update} have new evidence to review` }
        : { tone: "good", text: "all cite their evidence" },
    },
    {
      label: "Entries",
      value: t.entries || 0,
      foot: { tone: "", text: `across ${plural(t.projects || 0, "project", "projects")}` },
    },
    {
      label: "Pages fresh",
      value: `${pages - stale}<span class="of"> / ${pages}</span>`,
      foot: stale
        ? { tone: "bad", text: `${plural(stale, "page is", "pages are")} stale` }
        : { tone: "good", text: "none stale" },
      meterFrac: pages ? (pages - stale) / pages : 1,
      meterTone: stale ? "warn" : "good",
    },
    {
      label: "Quality gaps",
      // A scan that could not run must never render as a zero.
      value: allUnchecked ? "—" : (t.quality_gaps || 0),
      foot: allUnchecked
        ? { tone: "unknown", text: "not checked" }
        : uncheckedQ
          ? { tone: "warn", text: `${uncheckedQ} project(s) unchecked` }
          : { tone: "", text: "across all projects" },
    },
  ];

  $("#kpis").innerHTML = tiles.map((k) => `
    <article class="kpi">
      <div class="label">${esc(k.label)}</div>
      <div class="value">${typeof k.value === "number" ? k.value : k.value}</div>
      ${k.meterFrac !== undefined
        ? `<div class="meter" style="margin-top:9px">${meter(k.meterFrac, k.meterTone)}</div>` : ""}
      <div class="foot">${
        k.foot.tone ? `<span class="dot ${esc(k.foot.tone)}"></span>` : ""
      }<span>${esc(k.foot.text)}</span></div>
    </article>`).join("");
}

/* ---------------------------------------------------------------- banners */
function renderBanners(snap) {
  const out = [];
  if (!snap.includes_bodies) {
    out.push(`<div class="note"><b>Ids only.</b> This snapshot carries no entry
      text. Re-export with <code>--bodies</code> for titles and evidence.</div>`);
  }
  const unchecked = snap.projects.filter((p) => !p.quality.checked);
  if (unchecked.length) {
    out.push(`<div class="note warn"><b>Quality not checked for
      ${plural(unchecked.length, "project", "projects")}.</b>
      ${esc(unchecked.map((p) => p.name).join(", "))} —
      ${esc(unchecked[0].quality.reason)}. Shown as unknown, not as clean.</div>`);
  }
  if (snap.skipped_projects && snap.skipped_projects.length) {
    out.push(`<div class="note warn"><b>Skipped.</b> ${
      snap.skipped_projects.map((s) =>
        `${esc(s.name)} (${esc(s.reason)})`).join("; ")}</div>`);
  }
  $("#banners").innerHTML = out.join("");
}

/* ---------------------------------------------------------------- lessons */
function renderLessons(snap) {
  const L = snap.lessons || { laws: [] };
  if (!L.laws.length) {
    $("#view-lessons").innerHTML = `<p class="empty">No concept pages yet.
      Capture cross-project laws into cambium tagged <code>xylem-law</code>.</p>`;
    return;
  }
  const behind = L.needs_update || 0;
  const head = `<div class="note${behind ? " warn" : ""}">
    <b>${L.count} laws drawn across ${snap.projects.length} projects.</b>
    ${behind
      ? `${behind} cite less than the corpus now holds — those are listed first.
         A law is written by judgement; whether it has fallen behind is computed.`
      : `Every law cites all the evidence carrying its topics.`}</div>`;

  const cards = L.laws.map((law) => {
    const stale = law.unincorporated_count > 0;
    const topics = (law.topics || []).slice(0, 5);
    return `<article class="row">
      <div class="head">
        <span class="title">${esc(law.law)}</span>
        ${stale
          ? state("warn", `${law.unincorporated_count} to review`)
          : state("good", "current")}
      </div>
      <div class="meta">
        ${esc(law.scope)} · ${plural((law.cites || []).length, "citation", "citations")}
        ${law.recalls ? ` · ${plural(law.recalls, "recall", "recalls")}` : ""}
      </div>
      <div class="law-body">
        <div>
          ${topics.length
            ? `<div class="tagline">${topics.map((t) =>
                `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
          ${law.evidence ? `<p class="prose clamp">${esc(law.evidence)}</p>
            <details class="more"><summary>Full evidence</summary>
              <p class="prose">${esc(law.evidence)}</p></details>`
            : `<p class="prose muted">Evidence omitted — this snapshot carries no bodies.</p>`}
        </div>
        <aside class="law-aside">
          <div class="seen">Seen in<br><b>${
            esc((law.evidence_projects || []).join(", ") || "—")}</b></div>
          ${stale ? `<div class="seen" style="margin-top:12px">Carries this law's
            topics, not yet cited — a review list, not a verdict:</div>
            <div class="ids">${law.unincorporated.map((e) =>
              `<code>${esc(e)}</code>`).join("")}${
              law.unincorporated_count > law.unincorporated.length
                ? `<span class="muted" style="font-size:.74rem">+${
                    law.unincorporated_count - law.unincorporated.length} more</span>` : ""}
            </div>` : ""}
        </aside>
      </div>
    </article>`;
  });
  $("#view-lessons").innerHTML = head + cards.join("");
}

/* --------------------------------------------------------------- projects */
function renderProjects(snap) {
  const byEntries = snap.projects
    .map((p) => ({ name: p.name, value: p.counts.total }))
    .sort((a, b) => b.value - a.value);

  const chart = `<div class="card">
    <div class="section-h" style="margin:0 0 12px">Entries by project</div>
    ${bars(byEntries, { limit: 12 })}
  </div>`;

  const cards = snap.projects.map((p) => {
    const st = p.counts.by_status || {};
    const q = p.quality;
    const stale = p.stale_page_count;
    const pages = p.pages.length;
    return `<article class="card">
      <div class="head" style="display:flex;justify-content:space-between;gap:10px">
        <span class="title">${esc(p.name)}</span>
      </div>
      <div class="value" style="font-size:1.6rem;font-weight:640;margin-top:8px">${p.counts.total}</div>
      <div class="meta">entries · ${
        Object.entries(st).map(([k, v]) => `${v} ${esc(k)}`).join(" · ")}</div>
      <div class="foot" style="margin-top:11px;display:flex;flex-direction:column;gap:6px;align-items:stretch">
        <div style="display:flex;align-items:center;gap:6px;font-size:.8rem;color:var(--ink-2)">
          ${pages
            ? (stale
                ? `<span class="dot warn"></span><span>${stale} of ${pages} pages stale</span>`
                : `<span class="dot good"></span><span>${pages} pages fresh</span>`)
            : `<span class="dot"></span><span class="muted">no pages</span>`}
        </div>
        <div style="display:flex;align-items:center;gap:6px;font-size:.8rem;color:var(--ink-2)">
          ${q.checked
            ? (q.count
                ? `<span class="dot warn"></span><span>${plural(q.count, "quality gap", "quality gaps")}</span>`
                : `<span class="dot good"></span><span>no quality gaps</span>`)
            : `<span class="dot"></span><span class="muted">quality not checked</span>`}
        </div>
      </div>
    </article>`;
  });

  $("#view-projects").innerHTML =
    chart + `<div class="section-h">All projects</div><div class="grid">${cards.join("")}</div>`;
}

/* ----------------------------------------------------------------- chains */
function buildChains(project) {
  const edges = project.supersession_edges || [];
  if (!edges.length) return { chains: [], rendered: new Set() };
  const byId = new Map((project.entries || []).map((e) => [e.id, e]));
  const next = new Map(edges.map((e) => [e.from, e]));
  const targets = new Set(edges.map((e) => e.to));
  const roots = edges.map((e) => e.from).filter((id) => !targets.has(id));
  const chains = [];
  const rendered = new Set();
  for (const root of roots) {
    /* `seen` is per-root: sharing one set across roots dropped a whole chain
       whenever two entries were superseded by the same target. */
    const seen = new Set();
    const chain = [];
    let cur = root;
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      const edge = next.get(cur);
      chain.push({ id: cur, entry: byId.get(cur), dangling: false });
      if (!edge) break;
      rendered.add(`${edge.from}->${edge.to}`);
      if (!next.has(edge.to)) {
        chain.push({ id: edge.to, entry: byId.get(edge.to), dangling: edge.dangling });
        break;
      }
      cur = edge.to;
    }
    if (chain.length > 1) chains.push(chain);
  }
  return { chains, rendered };
}

function renderChains(snap) {
  const blocks = [];
  let dropped = 0;
  for (const p of snap.projects) {
    const { chains, rendered } = buildChains(p);
    const total = (p.supersession_edges || []).length;
    dropped += Math.max(0, total - rendered.size);
    if (!chains.length) continue;
    const rows = chains.map((chain) => {
      const parts = chain.map((n, i) => {
        const cls = n.dangling ? "node missing"
          : (n.entry && n.entry.status === "superseded") ? "node superseded" : "node";
        const full = n.dangling ? `${n.id} (missing)` : label(n.entry, snap.includes_bodies);
        const arrow = i < chain.length - 1 ? `<span class="arrow">→</span>` : "";
        return `<span class="${cls}" title="${esc(n.id)} — ${esc(full)}">${
          esc(clamp(full))}</span>${arrow}`;
      });
      return `<div class="row"><div class="chain">${parts.join("")}</div></div>`;
    });
    blocks.push(`<div class="section-h">${esc(p.name)}</div>${rows.join("")}`);
  }
  const note = dropped
    ? `<div class="note warn"><b>${plural(dropped, "edge", "edges")} not drawn.</b>
       A cycle or a shape this path view cannot express — the edge exists in the
       data even though no chain below shows it.</div>` : "";
  $("#view-chains").innerHTML = blocks.length
    ? note + blocks.join("")
    : note + `<p class="empty">No supersession edges recorded. Either nothing has
       replaced anything, or reversals are landing as in-place edits.</p>`;
}

/* ------------------------------------------------------------------ pages */
function renderPages(snap) {
  const rows = [];
  for (const p of snap.projects) {
    for (const page of p.pages) rows.push({ project: p.name, page });
  }
  rows.sort((a, b) => (b.page.stale_causes || []).length - (a.page.stale_causes || []).length
    || a.project.localeCompare(b.project));
  const stale = rows.filter((r) => r.page.stale);

  const head = `<div class="note${stale.length ? " warn" : ""}">
    <b>${rows.length} pages compiled${stale.length ? `, ${stale.length} stale` : ", none stale"}.</b>
    Staleness is recomputed against the live store on every export — never cached,
    never inferred from age.</div>`;

  if (!rows.length) {
    $("#view-pages").innerHTML = `<p class="empty">No pages compiled yet. Run
      <code>compile_project</code> to build them.</p>`;
    return;
  }

  /* Only the stale ones are cards, because only they need acting on. Rendering
     all 427 as identical cards saying "fresh" buried the question this view
     exists to answer under four hundred rows of the answer being "no". */
  const staleCards = stale.map(({ project, page }) => {
    const causes = page.stale_causes || [];
    return `<article class="row">
      <div class="head">
        <span class="title">${esc(page.title || page.id)}</span>
        ${state("bad", "stale")}
      </div>
      <div class="meta mono">${esc(project)} · ${
        plural(page.source_count, "source", "sources")} of ${page.candidate_count} active</div>
      ${causes.length ? `<div class="seen">Stale because:</div>
        <div class="ids">${causes.map((c) =>
          `<code>${esc(c.entry_id)} ${esc(c.cause.replace(/_/g, " "))}</code>`).join("")}</div>`
        : ""}
    </article>`;
  }).join("");

  /* Everything else collapses to one row per project — 20 rows, not 427. */
  const byProject = new Map();
  for (const { project, page } of rows) {
    const e = byProject.get(project) || { pages: 0, stale: 0, sources: 0 };
    e.pages++; e.sources += page.source_count || 0;
    if (page.stale) e.stale++;
    byProject.set(project, e);
  }
  const table = `<div class="card">
    <table class="tv">
      <thead><tr><th>Project</th><th class="n">Pages</th><th class="n">Sources</th><th>State</th></tr></thead>
      <tbody>${[...byProject.entries()]
        .sort((a, b) => b[1].pages - a[1].pages)
        .map(([name, e]) => `<tr>
          <td>${esc(name)}</td>
          <td class="n">${e.pages}</td>
          <td class="n">${e.sources}</td>
          <td>${e.stale
            ? `<span class="dot bad"></span> ${e.stale} stale`
            : `<span class="dot good"></span> all fresh`}</td>
        </tr>`).join("")}
      </tbody>
    </table>
    <p class="meta" style="margin:10px 0 0">Page bodies live in the exported vault
      — <code>cambium-mcp export-pages --out vault</code>.</p>
  </div>`;

  $("#view-pages").innerHTML = head
    + (stale.length ? `<div class="section-h">Needs attention</div>${staleCards}` : "")
    + `<div class="section-h">All pages by project</div>${table}`;
}

/* ------------------------------------------------------------------ links */
function renderLinks(snap) {
  const blocks = snap.projects.map((p) => {
    const l = p.links || {};
    if (!l.checked) {
      return `<article class="row"><div class="head">
        <span class="title">${esc(p.name)}</span>${state("unknown", "not surveyed")}</div>
        <div class="meta">${esc(l.reason || "not run")}</div></article>`;
    }
    if (!l.proposals.length) return "";
    const rows = l.proposals.map((r) => `<article class="row">
      <div class="head">
        <span class="title"><code>${esc(r.newer_id)}</code> may supersede
          <code>${esc(r.older_id)}</code></span>
        ${r.tier === "likely" ? state("warn", "likely") : state("unknown", "lead")}
      </div>
      ${(r.replacement_signals || []).length
        ? `<div class="meta">${esc(r.replacement_signals.join("; "))}</div>` : ""}
      ${r.newer_summary
        ? `<p class="prose">${esc(clamp(r.newer_summary, 130))}<br>
           <span class="muted">replacing:</span> ${esc(clamp(r.older_summary || "", 130))}</p>`
        : ""}
      <div class="seen">overlap ${esc(String(r.overlap_score ?? "?"))}${
        (r.shared_tags || []).length ? ` · shares <b>${esc(r.shared_tags.join(", "))}</b>` : ""}</div>
    </article>`);
    return `<div class="section-h">${esc(p.name)} — ${
      plural(l.count, "proposal", "proposals")}${l.likely ? `, ${l.likely} likely` : ""}</div>${rows.join("")}`;
  }).filter(Boolean);

  $("#view-links").innerHTML =
    `<div class="note"><b>Proposals only — nothing has been written.</b>
      <em>Likely</em> means the newer entry names the older beside change language:
      measured 80% precision on 34 hand-labelled pairs. Everything else shares a
      subject and nothing more, which measured 21.9%. Apply the ones you agree with
      via <code>deprecate_entry(old, reason, superseded_by=new)</code>.</div>`
    + blocks.join("");
}

/* ---------------------------------------------------------------- quality */
function renderQuality(snap) {
  const byType = {};
  let checked = 0;
  for (const p of snap.projects) {
    if (!p.quality.checked) continue;
    checked++;
    for (const g of p.quality.gaps || []) {
      for (const i of g.issues || []) {
        const k = i.type || "?";
        byType[k] = (byType[k] || 0) + 1;
      }
    }
  }
  const rows = Object.entries(byType)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
  const issueTotal = rows.reduce((a, r) => a + r.value, 0);
  const flagged = (snap.totals || {}).quality_gaps || 0;

  /* The KPI counts flagged ENTRIES; this counts ISSUES, and one entry usually
     carries several. Two different denominators on one screen is how a reader
     concludes the dashboard is wrong, so both are named. */
  const chart = rows.length ? `<div class="card">
    <div class="section-h" style="margin:0 0 4px">Issues by type</div>
    <p class="meta" style="margin:0 0 14px">${issueTotal} issues across ${
      flagged} flagged entries — an entry usually carries more than one.${
      checked < snap.projects.length
        ? ` ${checked} of ${snap.projects.length} projects checked.` : ""}</p>
    ${bars(rows)}
  </div>` : "";

  const blocks = snap.projects.map((p) => {
    const q = p.quality;
    if (!q.checked) {
      return `<article class="row"><div class="head">
        <span class="title">${esc(p.name)}</span>${state("unknown", "not checked")}</div>
        <div class="meta">${esc(q.reason)}</div></article>`;
    }
    if (!q.gaps.length) {
      return `<article class="row"><div class="head">
        <span class="title">${esc(p.name)}</span>${state("good", "no gaps")}</div>
        ${q.drift_checked === false
          ? `<div class="meta">Drift was not checked — no work tree to compare
             against. That is "no gaps found", not "nothing drifted".</div>` : ""}
      </article>`;
    }
    return `<article class="row">
      <div class="head"><span class="title">${esc(p.name)}</span>
        ${state("warn", plural(q.gaps.length, "gap", "gaps"))}</div>
      ${q.drift_checked === false
        ? `<div class="meta">Drift not checked — no work tree to compare against.</div>` : ""}
      <table class="tv"><thead><tr><th>Entry</th><th>Issues</th></tr></thead><tbody>
        ${q.gaps.slice(0, 40).map((g) => `<tr>
          <td><code>${esc(g.id)}</code></td>
          <td>${esc((g.issues || []).map((i) => i.type).join(", "))}</td></tr>`).join("")}
      </tbody></table>
      ${q.gaps.length > 40
        ? `<div class="seen muted">+${q.gaps.length - 40} more</div>` : ""}
    </article>`;
  });

  $("#view-quality").innerHTML = chart
    + `<div class="section-h">By project</div>` + blocks.join("");
}

/* ------------------------------------------------------------------- boot */
const VIEWS = ["lessons", "projects", "chains", "pages", "links", "quality"];

function switchTo(view) {
  if (!VIEWS.includes(view)) return;
  document.querySelectorAll(".tab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.view === view)));
  document.querySelectorAll(".view").forEach((v) =>
    v.hidden = v.id !== `view-${view}`);
  if (location.hash.replace("#", "") !== view) history.replaceState(null, "", `#${view}`);
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => switchTo(t.dataset.view)));
window.addEventListener("hashchange", () => switchTo(location.hash.replace("#", "")));

function counts(snap) {
  const t = snap.totals || {};
  const set = (id, n) => { const el = $(id); if (el && n) el.textContent = n; };
  set("#n-lessons", (snap.lessons || {}).count);
  set("#n-projects", t.projects);
  set("#n-chains", snap.projects.reduce((a, p) => a + (p.supersession_edges || []).length, 0));
  set("#n-pages", t.pages);
  set("#n-links", t.link_proposals);
  set("#n-quality", t.quality_gaps);
}

fetch("snapshot.json", { cache: "no-store" })
  .then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  })
  .then((snap) => {
    const t = snap.totals || {};
    $("#subtitle").textContent =
      `${plural(t.projects || 0, "project", "projects")} · ${t.entries || 0} entries`;
    $("#foot-note").textContent = snap.includes_bodies
      ? "Snapshot includes entry text — keep it private."
      : "Snapshot carries ids and counts only.";
    renderKpis(snap);
    renderBanners(snap);
    counts(snap);
    renderLessons(snap);
    renderProjects(snap);
    renderChains(snap);
    renderPages(snap);
    renderLinks(snap);
    renderQuality(snap);
    /* Deep links now work on FIRST load, not only on hashchange. */
    switchTo(location.hash.replace("#", "") || "lessons");
  })
  .catch((err) => {
    $("#subtitle").textContent = "Could not load snapshot.json";
    $("#banners").innerHTML = `<div class="note warn"><b>No snapshot.</b>
      ${esc(err.message)}. Generate one with
      <code>cambium-mcp refresh --out snapshot.json --vault vault</code>, and serve
      this directory over HTTP — opening index.html via file:// blocks the
      fetch.</div>`;
  });

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
