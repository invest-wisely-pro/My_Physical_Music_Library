/* My Physical Music Library — service worker
   App: rete prima (sempre l'ultima versione), copia salvata se offline.
   Copertine (Cover Art Archive): conservate dopo la prima visione, così lo scaffale resta completo offline. */
const VERSION = 'mpmlm-2026-10-16';
const CORE = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION && k !== 'covers').map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request; if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(/(^|\.)(coverartarchive\.org|archive\.org)$/.test(url.hostname)){
    e.respondWith(caches.open('covers').then(async c => { const hit = await c.match(req); if(hit) return hit; try{ const r = await fetch(req); if(r && (r.ok || r.type === 'opaque')) c.put(req, r.clone()); return r; }catch(err){ return hit || Response.error(); } }));
    return;
  }
  if(url.origin !== location.origin) return;   // MusicBrainz, caratteri: sempre dalla rete
  if(req.mode === 'navigate' || url.pathname.endsWith('/') || url.pathname.endsWith('index.html')){
    e.respondWith(fetch(req).then(r => { const cp = r.clone(); caches.open(VERSION).then(c => c.put('index.html', cp)); return r; }).catch(() => caches.match('index.html')));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req)));
});
