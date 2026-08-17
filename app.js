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
  // Reset before the cards are built, for the same reason renderLinks does:
  // a re-render must recount, not accumulate. Separate bucket from links, so
  // each bar acts only on its own list.
  BULK.lessons = { send: [], apply: [] };
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
            topics, not yet cited — decide each one:</div>
            <div class="candidates">${law.unincorporated.map((e) => {
              const subject = `${law.id}:${e}`;
              const cand = ENTRIES.get(e);
              const shared = cand
                ? (cand.tags || []).filter((t) => (law.topics || []).includes(t))
                : [];
              const cev = (law.unincorporated_evals || {})[e];
              // The queued intent has to name the project itself: unlike a link,
              // a candidate id arrives with no project attached, and the desktop
              // would have to guess which store holds it.
              const cpayload = { kind: "candidate", subject, law: law.id,
                                 older: e, project: (cand || {}).project };
              bulkNote("lessons", cpayload, cev,
                       (law.unincorporated_awaiting || []).includes(e));
              return `<div class="candidate" data-subject="${esc(subject)}">
                <code>${esc(e)}</code>
                ${cand && cand.title
                  ? `<span class="cand-title">${esc(clamp(cand.title, 90))}</span>` : ""}
                ${actionBar(subject, cpayload, cev,
                            (law.unincorporated_awaiting || []).includes(e))}
                ${cev ? evalBlock(cev, cpayload) : ""}
                ${detailsFor([e], shared.length
                  ? `<p class="detail-why">Matched this law on
                     <b>${esc(shared.join(", "))}</b>. Apply if the law should
                     account for it; Not this if the overlap is incidental.</p>`
                  : `<p class="detail-why">Shares this law's topics. Apply if the
                     law should account for it; Not this if the overlap is
                     incidental.</p>`)}
              </div>`;
            }).join("")}${
              law.unincorporated_count > law.unincorporated.length
                ? `<div class="muted" style="font-size:.74rem;margin-top:6px">+${
                    law.unincorporated_count - law.unincorporated.length} more</div>` : ""}
            </div>` : ""}
        </aside>
      </div>
    </article>`;
  });
  // Built AFTER the cards, because bulkNote fills the bucket during that map.
  // Its bucket holds only law candidates, so these buttons never touch a link
  // proposal.
  $("#view-lessons").innerHTML = head + bulkBar("lessons") + cards.join("");
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

  /* One button for the whole set, not one per page. A stale page needs no
     decision -- its body is regenerated from the entries it cites, so "stale"
     means the sources moved. Rebuilding is deterministic, local and free, and
     there is nothing to weigh page by page. */
  const subject = "pages:all_stale";
  const decided = QUEUE.get(subject);
  const rebuild = !stale.length ? "" : `<article class="row" data-subject="${esc(subject)}">
      <div class="head"><span class="title">${
        plural(stale.length, "page is", "pages are")} stale</span>
        ${state("warn", "rebuildable")}</div>
      <div class="meta">Their sources changed after they were compiled. Pages are
        build artifacts, so this is a recompile, not a decision — nothing is
        judged and nothing is written to a store.</div>
      ${!queueAvailable ? "" : decided
        ? `<span class="actions"><span class="decided">queued to rebuild</span></span>`
        : `<span class="actions"><button class="act implement"
             data-payload="${esc(JSON.stringify({ kind: "pages", subject }))}"
             data-implement="recompile">Rebuild ${
               plural(stale.length, "stale page", "stale pages")}</button></span>`}
    </article>`;

  $("#view-pages").innerHTML = head
    + (stale.length ? `<div class="section-h">Needs attention</div>${rebuild}${staleCards}` : "")
    + `<div class="section-h">All pages by project</div>${table}`;
}

/* An agent's audit of one proposal. Deliberately styled as EVIDENCE rather
   than as an answer: the verdict word is not a status colour and there is no
   one-tap "do what it said". It did the reading; you still rule. */
const EVAL_VERDICT = {
  // link proposals
  supersedes: { label: "reads as a replacement", cls: "warn" },
  unrelated: { label: "reads as unrelated", cls: "unknown" },
  related: { label: "related, not a replacement", cls: "unknown" },
  // law candidates
  cite: { label: "the law should account for this", cls: "warn" },
  incidental: { label: "overlap is incidental", cls: "unknown" },
  // both
  unsure: { label: "could not tell", cls: "unknown" },
};

/* Each verdict implies exactly one action, so Implement queues it directly
   instead of making you translate "supersedes" back into which button to press.
   It is still a tap, and it still goes through the same queue and the same
   drain -- the gate has not moved, the arithmetic has. `unsure` implies nothing
   and gets no button: the honest answer to "I could not tell" is that a person
   has to look. */
const IMPLIES = {
  supersedes: { action: "apply", label: "Implement: mark superseded" },
  related: { action: "dismiss", label: "Implement: not a replacement" },
  unrelated: { action: "dismiss", label: "Implement: not a replacement" },
  cite: { action: "apply", label: "Implement: cite in this law" },
  incidental: { action: "dismiss", label: "Implement: mark incidental" },
  unsure: null,
  // A repair proposal has already been reasoned about by the time it appears,
  // so Apply is what it points at -- but it is still only a recommendation.
  repair: { action: "apply", label: "Implement: apply this edit" },
};

/* Bulk actions, collected during render so the buttons count exactly what is on
   screen rather than re-deriving eligibility from the snapshot and drifting.
   Keyed by view; each render replaces its own bucket. */
const BULK = { links: { send: [], apply: [] }, lessons: { send: [], apply: [] },
               quality: { send: [], apply: [] } };

function bulkNote(view, payload, ev, awaiting) {
  if (QUEUE.get(payload.subject)) return;          // already decided this session
  if (!ev && !awaiting) BULK[view].send.push(payload);
  const imp = ev && IMPLIES[ev.verdict];
  if (imp) BULK[view].apply.push({ ...payload, action: imp.action });
}

/* Two taps for the bulk apply, one for the bulk send.
   Sending costs nothing and is trivially reversible by ignoring the result.
   Applying commits N rulings to stores in one gesture on a phone, where a
   mis-tap is easy and the undo is a backup directory. The count is in the
   confirm label so you are agreeing to a number, not to a word. */
/* Each view sends a different THING, and one generic label made the quality bar
   read "Send all 19 for eval" when what it queues is 19 projects for repair. */
const BULK_SEND_LABEL = {
  links: (n) => `Send all ${n} for eval`,
  lessons: (n) => `Send all ${n} for eval`,
  quality: (n) => `Send all ${n} ${n === 1 ? "project" : "projects"} for repair`,
};

function bulkBar(view) {
  if (!queueAvailable) return "";
  const b = BULK[view];
  if (!b.send.length && !b.apply.length) return "";
  return `<div class="bulkbar" data-view="${esc(view)}">
    ${b.send.length ? `<button class="act bulk" data-bulk="send" data-view="${esc(view)}">
        ${esc(BULK_SEND_LABEL[view](b.send.length))}</button>` : ""}
    ${b.apply.length ? `<button class="act bulk implement" data-bulk="apply" data-view="${esc(view)}">
        Apply all ${b.apply.length} recommendations</button>` : ""}
    <span class="bulk-status"></span>
  </div>`;
}

async function runBulk(view, which, btn) {
  const items = BULK[view][which];
  const bar = btn.closest(".bulkbar");
  const status = bar.querySelector(".bulk-status");
  bar.querySelectorAll("button").forEach((x) => { x.disabled = true; });
  let ok = 0, failed = 0;
  for (const it of items) {
    const payload = which === "send" ? { ...it, action: "eval" } : it;
    try {
      const r = await fetch("api/queue", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(String(r.status));
      QUEUE.set(payload.subject, payload);
      ok++;
      // Paint each row as it lands, so a long run visibly progresses instead of
      // looking hung.
      const row = document.querySelector(`[data-subject="${CSS.escape(payload.subject)}"]`);
      if (row) paintDecision(row, payload.action);
    } catch { failed++; }
    status.textContent = `${ok} queued${failed ? `, ${failed} failed` : ""}…`;
  }
  status.textContent = failed
    ? `${ok} queued, ${failed} failed — reload and retry the rest`
    : `${ok} queued. They apply on the next drain.`;
  bar.querySelectorAll("button").forEach((x) => x.remove());
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.act.bulk");
  if (!btn) return;
  const { bulk: which, view } = btn.dataset;
  const n = BULK[view][which].length;
  if (which === "apply" && btn.dataset.confirm !== "1") {
    btn.dataset.confirm = "1";
    btn.textContent = `Tap again to apply ${n} rulings`;
    setTimeout(() => {
      if (btn.dataset.confirm === "1") {
        btn.dataset.confirm = "";
        btn.textContent = `Apply all ${n} recommendations`;
      }
    }, 6000);
    return;
  }
  runBulk(view, which, btn);
});

function evalBlock(ev, payload) {
  const v = EVAL_VERDICT[ev.verdict] || { label: ev.verdict || "audited", cls: "unknown" };
  const conf = ev.confidence != null ? ` · confidence ${esc(String(ev.confidence))}` : "";
  const imp = IMPLIES[ev.verdict];
  // Hidden once the pair is already decided, and hidden in read-only mode, for
  // the same reasons the action bar is.
  const showImp = imp && payload && queueAvailable && !QUEUE.get(payload.subject);
  return `<div class="evalbox">
    <div class="evalhead">${state(v.cls, "agent read it")}
      <b>${esc(v.label)}</b><span class="muted">${conf}${
        ev.model ? ` · ${esc(ev.model)}` : ""}</span></div>
    ${ev.reasoning ? `<p class="prose">${esc(ev.reasoning)}</p>` : ""}
    ${showImp ? `<div class="eval-act"><button class="act implement"
        data-payload="${esc(JSON.stringify(payload))}"
        data-implement="${esc(imp.action)}">${esc(imp.label)}</button></div>` : ""}
  </div>`;
}

/* ------------------------------------------------------------------ links */
function renderLinks(snap) {
  // Reset first: a re-render must recount, never accumulate. And this bucket
  // only ever receives LINK proposals, so the links bar can never act on a law
  // candidate, or vice versa.
  BULK.links = { send: [], apply: [] };
  const blocks = snap.projects.map((p) => {
    const l = p.links || {};
    if (!l.checked) {
      return `<article class="row"><div class="head">
        <span class="title">${esc(p.name)}</span>${state("unknown", "not surveyed")}</div>
        <div class="meta">${esc(l.reason || "not run")}</div></article>`;
    }
    if (!l.proposals.length) return "";
    const rows = l.proposals.map((r) => {
      const subject = `${p.name}:${r.newer_id}:${r.older_id}`;
      const payload = { kind: "link", subject, project: p.name,
                        older: r.older_id, newer: r.newer_id };
      bulkNote("links", payload, r.eval, r.awaiting_eval);
      return `<article class="row" data-subject="${esc(subject)}">
      <div class="head">
        <span class="title"><code>${esc(r.newer_id)}</code> may supersede
          <code>${esc(r.older_id)}</code></span>
        ${r.tier === "likely" ? state("warn", "likely") : state("unknown", "lead")}
      </div>
      ${(r.replacement_signals || []).length
        ? `<div class="meta">${esc(r.replacement_signals.join("; "))}</div>` : ""}
      ${r.eval ? evalBlock(r.eval, payload) : ""}
      ${/* action bar below carries the recommendation mark */ ""}
      ${r.newer_summary
        ? `<p class="prose">${esc(clamp(r.newer_summary, 130))}<br>
           <span class="muted">replacing:</span> ${esc(clamp(r.older_summary || "", 130))}</p>`
        : ""}
      <div class="seen">overlap ${esc(String(r.overlap_score ?? "?"))}${
        (r.shared_tags || []).length ? ` · shares <b>${esc(r.shared_tags.join(", "))}</b>` : ""}</div>
      ${actionBar(subject, payload, r.eval, r.awaiting_eval)}
      ${detailsFor([r.newer_id, r.older_id],
        `<p class="detail-why">Apply records that <code>${esc(r.newer_id)}</code>
         REPLACED <code>${esc(r.older_id)}</code>: the older entry becomes
         <em>superseded</em> and stops being served as current. Read both below —
         if they merely cover the same area, choose Not this.${
           r.tier === "likely"
             ? " Tier <b>likely</b>: the newer entry names the older beside change language (80% precision measured)."
             : " Tier <b>lead</b>: they share a subject and nothing more (21.9% precision)."}</p>`)}
    </article>`;
    });
    return `<div class="section-h">${esc(p.name)} — ${
      plural(l.count, "proposal", "proposals")}${l.likely ? `, ${l.likely} likely` : ""}${
      l.audited ? `, ${l.audited} audited` : ""}</div>${rows.join("")}`;
  }).filter(Boolean);

  $("#view-links").innerHTML =
    `<div class="note"><b>Proposals only — nothing has been written.</b>
      <em>Likely</em> means the newer entry names the older beside change language:
      measured 80% precision on 34 hand-labelled pairs. Everything else shares a
      subject and nothing more, which measured 21.9%. Apply the ones you agree with
      via <code>deprecate_entry(old, reason, superseded_by=new)</code>.
      <br><b>Send for eval</b> queues the pair for the next Claude Code session on
      the PC, which reads both entries in full and reports back here with its
      reasoning. Nothing extra is spent and nothing is written to a store — the
      ruling stays yours.</div>`
    + bulkBar("links")
    + blocks.join("");
}

/* ---------------------------------------------------------------- quality */
function renderQuality(snap) {
  // Own bucket, own bar. A repair request is per PROJECT, so this list is
  // projects and never entries -- and it can never queue a link or a candidate.
  BULK.quality = { send: [], apply: [] };
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

  /* Every issue, bucketed by what can actually be DONE about it. A single
     total treats "one tap fixes this", "this clears itself", and "somebody has
     to read code" as the same outstanding item -- so the number never moves and
     the app reads as broken even while it is working. */
  const cls = { auto: 0, review: 0, waiting: 0, blocked: 0 };
  for (const p of snap.projects) {
    const g = (p.quality || {}).gap_classes;
    if (g) for (const k of Object.keys(cls)) cls[k] += g[k] || 0;
  }
  const CLS_COPY = {
    auto:    ["Fixable now", "One tap. The desktop applies these with no judgement involved — links a checker already computed, rationale already written, hints drawn from the entry's own words."],
    review:  ["Needs writing, then your approval", "An agent drafts the text in a session, you approve or reject it on the card. Nothing is written until you tap."],
    waiting: ["Already remediated", "These entries were loaded often and never queried, so they now carry retrieval hints. The flag only clears once one is actually returned by a search — no edit can force it."],
    blocked: ["Blocked on a code read", "The code moved under these entries. Writing anything would stamp them as re-verified without anyone checking, so they are left alone until read."],
  };
  const clsCards = `<div class="card">
    <div class="section-h" style="margin:0 0 4px">What can be done about them</div>
    <p class="meta" style="margin:0 0 14px">${issueTotal} issues across ${flagged}
      flagged entries. They are not one queue — these four behave completely
      differently.</p>
    ${Object.entries(CLS_COPY).map(([k, [title, why]]) => `
      <div class="row" style="margin-bottom:8px">
        <div class="head">
          <span class="title">${esc(title)}</span>
          ${state(k === "auto" ? "good" : k === "blocked" ? "bad" : k === "review" ? "warn" : "unknown",
                  String(cls[k]))}
        </div>
        <div class="meta">${esc(why)}</div>
      </div>`).join("")}
  </div>`;

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
    const subject = `quality:${p.name}`;
    const qpayload = { kind: "quality", subject, project: p.name };
    bulkNote("quality", qpayload, null, q.awaiting_repair);

    /* Proposed edits, each ruled on individually. A repair that rewrites an
       entry's TEXT is judgement, so it gets the same treatment as a proposed
       supersession: the change shown in full, the reasoning attached, and
       nothing written until a tap. Repairs used to be applied directly, which
       made this the only surface in the app with no approval step. */
    const props = (q.repair_proposals || []).map((r) => {
      const rp = { kind: "repair", subject: r.key, project: p.name };
      bulkNote("quality", rp, { verdict: "repair" }, false);
      return `<div class="row" data-subject="${esc(r.key)}" style="margin-top:9px">
        <div class="head"><span class="title"><code>${esc(r.entry_id)}</code>
          &middot; <span class="muted">${esc(r.field)}</span></span>
          ${state("warn", "proposed edit")}</div>
        ${r.why ? `<p class="prose">${esc(r.why)}</p>` : ""}
        ${r.proposed ? `<p class="prose" style="border-left:2px solid var(--series-1);
          padding-left:10px">${esc(clamp(String(r.proposed), 340))}</p>` : ""}
        ${actionBar(r.key, rp)}
      </div>`;
    }).join("");
    return `<article class="row" data-subject="${esc(subject)}">
      <div class="head"><span class="title">${esc(p.name)}</span>
        ${state("warn", plural(q.gaps.length, "gap", "gaps"))}</div>
      ${q.drift_checked === false
        ? `<div class="meta">Drift not checked — no work tree to compare against.</div>` : ""}
      ${props}
      ${!queueAvailable ? "" : QUEUE.get(subject)
        ? `<span class="actions"><span class="decided">queued for repair</span></span>`
        : q.awaiting_repair && (q.fixable_now || 0) === 0
        ? `<span class="actions"><span class="muted" style="font-size:.78rem">Repaired —
             what remains needs writing or a code read, see the breakdown above</span></span>`
        : q.awaiting_repair
        ? `<span class="actions"><span class="await-tag">sent for repair · awaiting a session</span></span>`
        : (q.fixable_now || 0) > 0
        ? `<span class="actions"><button class="act eval implement"
             data-payload="${esc(JSON.stringify(qpayload))}"
             data-eval="1">Fix ${q.fixable_now} now</button>
           <span class="muted" style="font-size:.76rem">${
             q.gaps.length - q.fixable_now} need reading or are waiting</span></span>`
        : `<span class="actions"><span class="muted" style="font-size:.78rem">Nothing
             here can be fixed automatically — see the breakdown above</span></span>`}
      <table class="tv"><thead><tr><th>Entry</th><th>Issues</th></tr></thead><tbody>
        ${q.gaps.slice(0, 40).map((g) => `<tr>
          <td><code>${esc(g.id)}</code></td>
          <td>${esc((g.issues || []).map((i) => i.type).join(", "))}</td></tr>`).join("")}
      </tbody></table>
      ${q.gaps.length > 40
        ? `<div class="seen muted">+${q.gaps.length - 40} more</div>` : ""}
    </article>`;
  });

  $("#view-quality").innerHTML = clsCards + chart
    + `<div class="section-h">By project</div>` + bulkBar("quality") + blocks.join("");
}

/* --------------------------------------------------------------- decisions
   The phone records what you decided; the desktop applies it. Queueing is
   deliberately NOT a write to any store — see the Worker. The UI reflects the
   decision immediately so a review pass feels like one, and the queue is the
   authority on what has already been decided. */
const QUEUE = new Map();          // subject -> {action, ...}
let queueAvailable = false;

async function loadQueue() {
  try {
    const r = await fetch("api/queue", { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    QUEUE.clear();
    for (const it of data.items || []) QUEUE.set(it.subject, it);
    queueAvailable = true;
  } catch {
    // Read-only mode is a legitimate state (opened from a local file server,
    // or the Worker's KV not bound). Say so rather than showing dead buttons.
    queueAvailable = false;
  }
}

async function decide(payload, btn) {
  const row = btn.closest("[data-subject]");
  row.dataset.pending = "1";
  try {
    const r = await fetch("api/queue", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(String(r.status));
    QUEUE.set(payload.subject, payload);
    paintDecision(row, payload.action);
  } catch (e) {
    row.dataset.pending = "";
    const err = document.createElement("span");
    err.className = "decided bad";
    err.textContent = "could not queue — try again";
    row.querySelector(".actions").replaceChildren(err);
  }
}

const DECISION_LABEL = {
  apply: "queued to apply",
  dismiss: "queued to dismiss",
  eval: "sent for eval",
  recompile: "queued to rebuild",
};
/* Actions with no opposite. Undo flips apply <-> dismiss because those are the
   two sides of one ruling; asking for a read, or for a rebuild, has no inverse
   to offer. */
const NO_UNDO = new Set(["eval", "recompile"]);

function paintDecision(row, action) {
  row.dataset.pending = "";
  row.dataset.decided = action;
  // Implement lives in the verdict block, not the action bar, so replacing the
  // bar below would leave it sitting there inviting a second tap on something
  // already decided.
  const impl = row.querySelector(".eval-act");
  if (impl) impl.remove();
  const box = row.querySelector(".actions");
  if (!box) return;
  const tag = document.createElement("span");
  tag.className = "decided";
  tag.textContent = DECISION_LABEL[action] || action;
  if (NO_UNDO.has(action)) {
    const note = document.createElement("span");
    note.className = "muted";
    note.textContent = action === "eval"
      ? "verdict appears here after the next drain"
      : "rebuilt on the next drain";
    box.replaceChildren(tag, note);
    return;
  }
  const undo = document.createElement("button");
  undo.className = "linkish";
  undo.textContent = "undo";
  undo.addEventListener("click", () => {
    const sub = row.dataset.subject;
    const prev = QUEUE.get(sub);
    if (!prev) return;
    decide({ ...prev, action: prev.action === "apply" ? "dismiss" : "apply" },
           undo);
  });
  box.replaceChildren(tag, undo);
}

/* Every entry in the mesh, by id, so a review can show what it is actually
   about rather than an id and a shrug. */
const ENTRIES = new Map();
function indexEntries(snap) {
  for (const p of snap.projects) {
    for (const e of p.entries || []) ENTRIES.set(e.id, { ...e, project: p.name });
  }
}

/* The detail panel. Built from the snapshot the page already has, so opening it
   costs nothing and works offline. */
function detailsFor(ids, extra) {
  const blocks = ids.map((id) => {
    const e = ENTRIES.get(id);
    if (!e) {
      return `<div class="detail-entry"><code>${esc(id)}</code>
        <p class="muted">Not in this snapshot — it may have been deleted, or it
        belongs to a project that is not exported.</p></div>`;
    }
    return `<div class="detail-entry">
      <div class="detail-head"><code>${esc(e.id)}</code>
        <span class="muted">${esc(e.project)} · ${esc(e.kind)}${
          e.status && e.status !== "active" ? ` · ${esc(e.status)}` : ""}</span></div>
      ${e.title ? `<p class="detail-title">${esc(e.title)}</p>` : ""}
      ${e.excerpt ? `<p class="prose">${esc(e.excerpt)}</p>` : ""}
      ${(e.tags || []).length
        ? `<div class="tagline">${e.tags.map((t) =>
            `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
    </div>`;
  }).join("");
  return `<div class="details" hidden>${extra || ""}${blocks}</div>`;
}

function detailsToggle() {
  return `<button class="act details-btn" type="button">Details</button>`;
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.details-btn");
  if (!btn) return;
  const panel = btn.closest("[data-subject]").querySelector(".details");
  if (!panel) return;
  panel.hidden = !panel.hidden;
  btn.textContent = panel.hidden ? "Details" : "Hide details";
});

function actionBar(subject, payload, verdict, awaiting) {
  if (!queueAvailable) return "";
  const decided = QUEUE.get(subject);
  if (decided) {
    return `<span class="actions">${detailsToggle()}<span class="decided">${
      esc(DECISION_LABEL[decided.action] || decided.action)
    }</span></span>`;
  }
  // Once an agent has read the pair, mark the button its verdict points at, so
  // the recommendation lands on the control you would actually press rather
  // than needing to be translated. Never colour alone: the filled treatment is
  // paired with a visible "recommended" tag, because a reader who cannot
  // separate the two hues would otherwise get no signal at all.
  const rec = verdict ? (IMPLIES[verdict.verdict] || {}).action : null;
  const mark = (which) => (rec === which ? " recommended" : "");
  const p = esc(JSON.stringify(payload));
  // Both kinds get it; the question differs. For a link: did the newer entry
  // really replace the older. For a law candidate: should this law account for
  // this entry, and what would change if it did. The second is the harder read
  // and the one most worth handing to something that will actually go and read
  // the law and the entry side by side.
  // Once audited there is nothing left to send. While a filed request is still
  // waiting on a reader, say so -- the queue clears as soon as it drains, so
  // without this the button would come straight back and the tap would look
  // like it had failed.
  const evalBtn = (verdict || awaiting) ? ""
    : `<button class="act eval" data-payload="${p}" data-eval="1">Send for eval</button>`;
  const waitTag = (awaiting && !verdict)
    ? `<span class="await-tag">sent for eval · awaiting verdict</span>` : "";
  const recTag = rec
    ? `<span class="rec-tag">recommended</span>` : "";
  return `<span class="actions">
    ${detailsToggle()}
    <button class="act apply${mark("apply")}" data-payload="${p}">Apply</button>
    <button class="act${mark("dismiss")}" data-payload="${p}" data-dismiss="1">Not this</button>
    ${evalBtn}${waitTag}${recTag}
  </span>`;
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.act");
  if (!btn) return;
  const payload = JSON.parse(btn.dataset.payload);
  payload.action = btn.dataset.implement ? btn.dataset.implement
                 : btn.dataset.eval ? "eval"
                 : btn.dataset.dismiss ? "dismiss"
                 : "apply";
  decide(payload, btn);
});

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
    $("#foot-note").textContent = (snap.includes_bodies
      ? "Snapshot includes entry text — keep it private."
      : "Snapshot carries ids and counts only.")
      + (queueAvailable
          ? ` ${QUEUE.size} decision(s) queued; run publish.ps1 on the desktop to apply.`
          : " Read-only: decisions cannot be queued from here.");
    return loadQueue().then(() => snap);
  })
  .then((snap) => {
    indexEntries(snap);
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
