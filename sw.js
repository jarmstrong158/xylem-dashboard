/* Offline shell for the installed app.

   The SHELL is cached; the snapshot is not. A memory dashboard that served a
   stale snapshot from cache would be lying in exactly the way the rest of this
   system works hard to avoid — so snapshot.json is always network-first, and
   only falls back to a cached copy when the phone is genuinely offline (in
   which case the page is still better than nothing, and the staleness it shows
   is the store's, not the cache's). */

/* SHELL must be bumped with every app.css/app.js change, in step with the ?v=
   query in index.html. Pinned at v1, an installed client served the first shell
   it ever cached forever — new markup against old styles, which presents as a
   broken dashboard rather than a stale one. */
const SHELL = "xylem-shell-v19";
const DATA = "xylem-data-v1";
/* These URLs must carry the SAME ?v= as index.html. They are precache keys, and
   a cache is keyed by URL: leaving them a version behind caches app.js?v=N-1,
   which the page never requests, so the precache holds nothing the page uses and
   offline serves an empty shell. Nothing warns you -- online it works perfectly,
   because every request just misses the cache and goes to network. */
const ASSETS = ["./", "index.html", "app.css?v=19", "app.js?v=19",
                "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))
  )).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  /* Only ever cache a genuine 200. Behind an auth gate an expired session
     answers with a redirect to a login page; caching that would pin the login
     screen into the app and it would never recover. `res.ok` is false for
     redirects and errors alike, which is exactly the set to refuse. */
  if (url.pathname.endsWith("snapshot.json")) {
    e.respondWith(
      fetch(e.request).then((res) => {
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(DATA).then((c) => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  /* THE DOCUMENT IS NETWORK-FIRST. It must be.

     index.html is the only cached URL that is NOT versioned, and it is the file
     that names which app.js the page loads. Serving it cache-first pins a client
     to whatever shell it first saw: the stale index keeps requesting
     app.css?v=OLD and app.js?v=OLD, so every ?v= bump and every SHELL rename is
     defeated. It fails in the most deceiving way possible -- snapshot.json is
     network-first, so the DATA updates and the numbers move while the interface
     never changes by a pixel. A deploy looks live and is not, and no amount of
     reloading helps, because reloading re-reads the same cached document.

     That is exactly what happened here: a live client sat on build 4 through
     thirteen version bumps while the data kept updating. (Written without a
     literal version query, because the release bumper rewrites every one it
     finds -- including inside this comment, which it already did once.)
     Cache-first is right for versioned assets, whose URL changes when their
     content does; it is never right for the document that names those URLs. */
  const isDocument = e.request.mode === "navigate"
    || url.pathname === "/" || url.pathname.endsWith("/index.html");

  if (isDocument) {
    e.respondWith(
      fetch(e.request).then((res) => {
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request).then((hit) => hit
        || caches.match("index.html")))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok && res.type === "basic") {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put(e.request, copy));
      }
      return res;
    }))
  );
});
