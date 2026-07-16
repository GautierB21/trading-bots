const CACHE_NAME = "trading-bots-v4";
const ASSETS = [
  "/",
  "/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

// Install: cache core assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first with cache fallback (API calls are never cached)
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls
  if (url.pathname.startsWith("/api/")) {
    return event.respondWith(fetch(event.request));
  }

  // Static assets and navigation: cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        if (response.ok && url.pathname !== "/api/") {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
