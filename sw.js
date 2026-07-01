// Merged with OneSignal's push handling per their "existing service worker"
// integration guide, so this one file covers both PWA installability and
// web push (avoids two service workers fighting over the same scope).
importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");

// Minimal app-shell cache so the site is installable (Chrome requires an
// active service worker with a fetch handler). Network-first: always tries
// to fetch the latest version first (and updates the cache with it), only
// falling back to the cached copy when offline. A pure cache-first strategy
// here would mean anyone who installed the app never sees content updates.
const CACHE = "nyc-gallery-shell-v2";
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/data/")) {
    return; // let cross-origin (map tiles, ads) and live data requests pass straight through
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
