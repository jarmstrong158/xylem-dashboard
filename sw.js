/* Offline shell for the installed app.

   The SHELL is cached; the snapshot is not. A memory dashboard that served a
   stale snapshot from cache would be lying in exactly the way the rest of this
   system works hard to avoid — so snapshot.json is always network-first, and
   only falls back to a cached copy when the phone is genuinely offline (in
   which case the page is still better than nothing, and the staleness it shows
   is the store's, not the cache's). */

const SHELL = "xylem-shell-v1";
const DATA = "xylem-data-v1";
const ASSETS = ["./", "index.html", "app.css", "app.js",
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

  if (url.pathname.endsWith("snapshot.json")) {
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(DATA).then((c) => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
