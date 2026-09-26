const CACHE = 'zebra-checkin-cache-v10';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './sw.js',
  './libs/dexie.min.js',
  './libs/xlsx.full.min.js'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  e.respondWith((async () => {
    const cached = await caches.match(e.request);
    if (cached) return cached;
    try {
      const fresh = await fetch(e.request);
      return fresh;
    } catch {
      // fallback: root
      return caches.match('./index.html');
    }
  })());
});
