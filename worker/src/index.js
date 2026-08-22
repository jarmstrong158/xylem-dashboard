/* Serves the dashboard behind a path-token credential.
 *
 * This is the same trust model as the other Xylem Workers (cambium-remote,
 * context-keeper-remote, agentsync-remote), which authenticate as
 * /mcp/<AUTH_TOKEN>. The URL IS the credential: there is no login screen, which
 * is the point — a phone opens a bookmark and the app is simply there.
 *
 * Being honest about what that is worth: a path token is weaker than real
 * identity. It rides in browser history and in any Referer a link click would
 * send, it cannot be revoked per-device, and anyone holding the URL is fully
 * authorised. It is chosen here because the alternative with real identity
 * (Cloudflare Access) needs dashboard configuration this deploy cannot perform,
 * and because the same operator already runs three Workers on this exact model.
 * Adding Access in front later changes nothing in this code.
 *
 * Mitigations that are cheap and therefore not optional:
 *   - a wrong or absent token gets 404, never 401: nothing here advertises that
 *     a correct token exists to be guessed at
 *   - Referrer-Policy: no-referrer so the token cannot leak through an outbound
 *     link click
 *   - noindex, and a robots.txt that disallows everything
 *   - constant-time-ish comparison, so the 404 does not leak the prefix
 */

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const DENY = () =>
  new Response("Not found", {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "private, no-store",
      "referrer-policy": "no-referrer",
    },
  });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/robots.txt") {
      return new Response("User-agent: *\nDisallow: /\n", {
        headers: { "content-type": "text/plain" },
      });
    }

    // .trim() is not cosmetic: piping a value into `wrangler secret put` stores
    // the trailing newline the shell adds, so the stored secret was one byte
    // longer than the token in the URL and every correct request was refused.
    const token = (env.AUTH_TOKEN || "").trim();
    if (!token) return DENY();   // unconfigured serves nothing, never everything

    const parts = url.pathname.split("/").filter(Boolean);
    if (!parts.length || !safeEqual(parts[0], token)) return DENY();

    // Strip the token segment and hand the rest to the static assets.
    const rest = "/" + parts.slice(1).join("/");

    // ---- decision queue -------------------------------------------------- #
    // The phone records what you decided; it does not act. Every entry here is
    // an INTENT that the desktop drain replays through context-keeper's own
    // lifecycle tools, so the write path and its gates are unchanged.
    if (rest === "/api/queue") {
      if (request.method === "GET") {
        const list = await env.QUEUE.list({ prefix: "d:" });
        const items = await Promise.all(list.keys.map(async (k) =>
          JSON.parse((await env.QUEUE.get(k.name)) || "null")));
        return json({ items: items.filter(Boolean) });
      }
      if (request.method === "POST") {
        let body;
        try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
        const kind = String(body.kind || "");
        const action = String(body.action || "");
        const subject = String(body.subject || "");
        // "pages" carries no per-item identity -- it asks the desktop to rebuild
        // every stale page. Pages are build artifacts regenerated from entries,
        // so this is deterministic work, not a decision.
        // "quality" asks for a project's flagged entries to be repaired. Like
        // "link" and "candidate" it only ever files a request; the repair is
        // done by a session agent with context-keeper's own update_entry.
        // "repair" rules on one PROPOSED edit to one entry. Same footing as a
        // link verdict: the agent proposes the new text, the tap applies it.
        // "synthesis" names a project whose entries no law cites, and asks a
        // session agent to DRAFT one. Like the others it only files a request:
        // writing the law is judgement, and it still has to be approved.
        if (!["link", "candidate", "pages", "quality", "repair", "synthesis"].includes(kind)) return json({ error: "bad kind" }, 400);
        // "eval" asks the desktop to have an agent AUDIT the pair and report
        // back. It is still only an intent -- it authorises reading, never a
        // write, and the ruling stays with whoever taps Apply afterwards.
        // "recompile" rebuilds stale pages: deterministic, and it regenerates
        // build artifacts rather than editing any entry.
        if (!["apply", "dismiss", "eval", "recompile"].includes(action)) return json({ error: "bad action" }, 400);
        if (!subject || subject.length > 200) return json({ error: "bad subject" }, 400);
        const rec = {
          kind, action, subject,
          project: String(body.project || "").slice(0, 80),
          // Which actionability bucket a mesh-wide request applies to:
          // auto | review | blocked. Empty for per-item intents.
          cls: String(body.cls || "").slice(0, 16),
          older: String(body.older || "").slice(0, 80),
          newer: String(body.newer || "").slice(0, 80),
          law: String(body.law || "").slice(0, 200),
          // Entry ids a "synthesis" intent names. Carried rather than
          // recomputed at drain time so the tap means the entries that were on
          // screen when it was tapped, not whatever the set has drifted to.
          // Bounded on both axes: KV values are capped, and an unbounded list
          // from a client is an unbounded write.
          entries: Array.isArray(body.entries)
            ? body.entries.slice(0, 40).map((e) => String(e).slice(0, 80))
            : [],
          at: new Date().toISOString(),
        };
        // Keyed by subject so deciding twice replaces rather than duplicates.
        await env.QUEUE.put("d:" + kind + ":" + subject, JSON.stringify(rec));
        return json({ ok: true, queued: rec });
      }
      if (request.method === "DELETE") {
        const list = await env.QUEUE.list({ prefix: "d:" });
        await Promise.all(list.keys.map((k) => env.QUEUE.delete(k.name)));
        return json({ ok: true, cleared: list.keys.length });
      }
      return json({ error: "method" }, 405);
    }

    const assetPath = rest === "/" ? "/index.html" : rest;
    const assetUrl = new URL(assetPath, url.origin);

    if (url.searchParams.has("__diag")) {
      const probe = await env.ASSETS.fetch(new URL("/index.html", url.origin).toString());
      return new Response(JSON.stringify({
        assetPath, probeStatus: probe.status,
        probeType: probe.headers.get("content-type"),
      }, null, 1), { headers: { "content-type": "application/json" } });
    }

    // Plain string URL, and no copied request: forwarding the original request's
    // headers here was enough to make every asset lookup miss.
    let res = await env.ASSETS.fetch(assetUrl.toString());
    if (res.status === 404 && assetPath !== "/index.html") {
      res = await env.ASSETS.fetch(new URL("/index.html", url.origin).toString());
    }

    const headers = new Headers(res.headers);
    headers.set("Referrer-Policy", "no-referrer");
    headers.set("X-Robots-Tag", "noindex, nofollow");
    headers.set("X-Content-Type-Options", "nosniff");
    // The snapshot is private data: never let a shared cache hold it.
    headers.set("Cache-Control", "private, no-store");
    return new Response(res.body, { status: res.status, headers });
  },
};
