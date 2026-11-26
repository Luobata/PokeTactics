/* /play Service Worker (docs/72): installable app shell + static-asset cache.
 *
 * Served by server.py at /play/sw.js with the CONFIG literal below replaced:
 *   version  - hash of every precached shell file (play JS/CSS, icons, manifest);
 *              any change installs a new worker and drops the old shell cache.
 *   media    - hash of the pinned PMD sprite index; large sprite atlases survive
 *              code updates and are dropped only when the sprites are re-imported.
 *   precache - shell URLs fetched on install.
 *
 * Only static resources are cached. API calls (/api/...), saves, backups, battle
 * frames and anything that is not GET stay on the network, untouched: the Python
 * server remains authoritative for every game state change.
 */
"use strict";
const CONFIG = /*__PT_CONFIG__*/{"version": "dev", "media": "dev", "precache": []}/*__PT_CONFIG_END__*/;
const SHELL = `pt-shell-${CONFIG.version}`;
const MEDIA = `pt-media-${CONFIG.media}`;
const PAGE = "/play";
// Set when a freshly fetched /play page reports a newer shell version than this
// worker caches: until the new worker takes over, shell files come from the
// network so new HTML never runs with old scripts.
let outdated = false;

/** Which cache a same-origin GET belongs to, or null to leave it to the network. */
function bucketFor(pathname) {
  if (pathname === "/play/sw.js") return null;
  if (pathname.startsWith("/api/")) return null;
  if (pathname.startsWith("/play/assets/") || pathname.startsWith("/play/icons/")
      || pathname === "/play/manifest.webmanifest" || pathname.startsWith("/demo/sprite/")
      || pathname.startsWith("/pmd/thumb/")) return SHELL;
  if (/^\/pmd\/(portrait\/)?\d{4}(-shiny)?\.(png|json)$/.test(pathname)) return MEDIA;
  return null;
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    // One failed file must not block installing the app: cache what we can.
    await Promise.all([PAGE, ...CONFIG.precache].map((url) =>
      cache.add(new Request(url, {cache: "reload"})).catch(() => null)));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL, MEDIA]);
    for (const key of await caches.keys()) {
      if (key.startsWith("pt-") && !keep.has(key)) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

async function cacheFirst(request, bucket) {
  if (outdated && bucket === SHELL) return fetch(request);
  const cache = await caches.open(bucket);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") cache.put(request, response.clone()).catch(() => null);
  return response;
}

async function pageNetworkFirst(request) {
  try {
    const response = await fetch(request);
    const served = response.headers?.get?.("X-PT-Shell-Version");
    if (served && served !== CONFIG.version) outdated = true;
    if (response.ok && !outdated) {
      const cache = await caches.open(SHELL);
      cache.put(PAGE, response.clone()).catch(() => null);
    }
    return response;
  } catch (error) {
    // Offline or the dev machine is down: open the cached shell; its own error
    // handling reports that the game server cannot be reached.
    const cached = await caches.match(PAGE, {cacheName: SHELL});
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    if (url.pathname === "/play" || url.pathname === "/play/") event.respondWith(pageNetworkFirst(request));
    return;
  }
  const bucket = bucketFor(url.pathname);
  if (bucket) event.respondWith(cacheFirst(request, bucket));
});

self.addEventListener("message", (event) => {
  if (event.data === "version") event.source?.postMessage({type: "pt-sw-version", version: CONFIG.version, media: CONFIG.media});
});

if (typeof module === "object" && module.exports) module.exports = {bucketFor, CONFIG, SHELL, MEDIA};
