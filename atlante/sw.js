/* Atlante della Musica — service worker (solo la cartella atlante/).
   App: rete prima, copia salvata se offline. Indice dei dischi (../index.html): rete prima, copia se offline.
   Copertine: conservate dopo la prima visione. MusicBrainz, Wikidata, Wikipedia: sempre dalla rete. */
const VERSION = 'amus-1.6';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png', 'fonts/inter-var.woff2'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('amus-') && k !== VERSION && k !== 'amus-dati' && k !== 'amus-copertine').map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request; if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(/(^|\.)(coverartarchive\.org|archive\.org)$/.test(url.hostname)){
    e.respondWith(caches.open('amus-copertine').then(async c => { const hit = await c.match(req); if(hit) return hit; try{ const r = await fetch(req); if(r && (r.ok || r.type === 'opaque')) c.put(req, r.clone()); return r; }catch(err){ return hit || Response.error(); } }));
    return;
  }
  if(url.origin !== location.origin) return;
  const inApp = url.pathname.includes('/atlante/');
  if(!inApp && url.pathname.endsWith('/index.html')){   // l'indice dei dischi
    e.respondWith(fetch(req).then(r => { if(r.ok){ const cp = r.clone(); caches.open('amus-dati').then(c => c.put('indice', cp)); } return r; }).catch(() => caches.open('amus-dati').then(c => c.match('indice')).then(h => h || Response.error())));
    return;
  }
  if(!inApp) return;
  if(req.mode === 'navigate' || url.pathname.endsWith('/atlante/') || url.pathname.endsWith('/atlante/index.html')){
    e.respondWith(fetch(req).then(r => { const cp = r.clone(); caches.open(VERSION).then(c => c.put('index.html', cp)); return r; }).catch(() => caches.open(VERSION).then(c => c.match('index.html'))));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req)));
});
