#!/usr/bin/env python3
"""
Aggiorna l'indice offline di My Physical Music Library.

Scarica l'archivio JSON ufficiale dei "release group" (gli album) di MusicBrainz
(https://data.metabrainz.org, dati CC0), tiene gli album ed EP piu diffusi
(misurati da quanto la comunita li ha descritti e votati) e li inserisce nel file
HTML dell'app (di solito index.html).

Formato di ogni riga (dentro il blocco compresso):
  id (32 caratteri, senza trattini)|titolo|artista|anno|tipo|generi
  tipo: A = album, E = EP, piu L (live) C (compilation) S (colonna sonora) R (remix)

Uso:
  python aggiorna_indice_musica.py index.html                    # scarica l'archivio di oggi
  python aggiorna_indice_musica.py index.html --local FILE      # usa un release-group.tar.xz (o .jsonl) gia scaricato
  Opzioni: --top N (album da tenere, predefinito 80000), --min N (minimo per inserirlo, predefinito 20000)
Solo libreria standard di Python 3.8+.
"""
import sys, os, re, io, json, gzip, time, base64, heapq, tarfile, datetime, urllib.request, urllib.error

BASE = 'https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/'
UA = {'User-Agent': 'MyPhysicalMusicLibrary-index-updater/1.0 (personal use)'}
EXCLUDE = {'Demo', 'Interview', 'Audiobook', 'Audio drama', 'Spokenword', 'Field recording', 'DJ-mix', 'Mixtape/Street'}
SEC = {'Live': 'L', 'Compilation': 'C', 'Soundtrack': 'S', 'Remix': 'R'}

def log(*a): print(*a, flush=True)

def fetch(url, timeout=60, tries=3):
    """Richiesta con fino a 3 tentativi e attese crescenti (errori di rete momentanei)."""
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404: raise
            last = e
        except Exception as e:
            last = e
        log(f'  tentativo {i + 1} non riuscito ({last}), riprovo…'); time.sleep(5 * (i + 1))
    raise last

def find_dump():
    """Cartella dell'archivio piu recente e indirizzo del file dei release group."""
    folder = ''
    try:
        folder = fetch(BASE + 'LATEST').read().decode().strip()
        log('Archivio indicato da LATEST:', folder)
    except Exception as e:
        log('LATEST non disponibile (', e, '): leggo l\'elenco delle cartelle')
    if not re.fullmatch(r'\d{8}-\d{6}', folder or ''):
        listing = fetch(BASE).read().decode('utf-8', 'replace')
        found = sorted(set(re.findall(r'href="(\d{8}-\d{6})/?"', listing)))
        if not found: raise SystemExit('Nessuna cartella di archivio trovata su ' + BASE)
        folder = found[-1]; log('Archivio piu recente nell\'elenco:', folder)
    url = f'{BASE}{folder}/release-group.tar.xz'
    try:
        r = fetch(url, timeout=600)
        return folder, r
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
    listing = fetch(f'{BASE}{folder}/').read().decode('utf-8', 'replace')
    names = re.findall(r'href="([^"]*release[-_]group[^"]*\.tar\.xz)"', listing)
    if not names: raise SystemExit(f'File dei release group non trovato in {BASE}{folder}/')
    log('File trovato nell\'elenco:', names[0])
    return folder, fetch(f'{BASE}{folder}/{names[0].split("/")[-1]}', timeout=600)
def clean(s): return str(s or '').replace('|', '/').replace('\n', ' ').replace('\r', ' ').strip()
def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

def lines_from(src):
    """Righe JSON dal release-group.tar.xz (stream, senza estrarre su disco) o da un .jsonl."""
    if isinstance(src, str) and (src.endswith('.jsonl') or src.endswith('.json')):   # un download dalla rete non ha un nome
        with open(src, encoding='utf-8') as f:
            yield from f
        return
    opener = (lambda: tarfile.open(fileobj=src, mode='r|xz')) if hasattr(src, 'read') else (lambda: tarfile.open(src, mode='r|xz'))
    with opener() as tar:
        for m in tar:
            if m.isfile() and m.name.rstrip('/').endswith('release-group'):
                f = tar.extractfile(m)
                buf = b''
                while True:   # lettura a blocchi: in streaming il lettore di testo standard non funziona
                    chunk = f.read(1 << 20)
                    if not chunk: break
                    buf += chunk
                    *lines, buf = buf.split(b'\n')
                    for l in lines: yield l.decode('utf-8', 'replace')
                if buf: yield buf.decode('utf-8', 'replace')
                return
    raise SystemExit('File "release-group" non trovato nell\'archivio')

NOTABLE = ('wikidata', 'wikipedia', 'discogs', 'allmusic', 'review', 'lyrics', 'other databases')
def score(rg):
    s = 0
    for g in rg.get('genres') or []: s += 2 * int(g.get('count') or 0)
    for t in rg.get('tags') or []: s += int(t.get('count') or 0)
    r = rg.get('rating') or {}
    s += 3 * int(r.get('votes-count') or r.get('votes_count') or 0)
    for rel in rg.get('relations') or []:   # i collegamenti (Wikipedia, Discogs, AllMusic…) dicono quanto un album e noto
        ty = str(rel.get('type') or '').lower()
        s += 4 if ty in ('wikidata', 'wikipedia') else 2 if any(k in ty for k in NOTABLE) else 1
    return s

def build(src, top):
    heap, n, kept, bad = [], 0, 0, 0
    for raw in lines_from(src):
        n += 1
        if n % 500000 == 0: log(f'  letti {n:,} album… (tenuti finora: {len(heap):,})')
        try: rg = json.loads(raw)
        except Exception:
            bad += 1; continue
        if n == 1: log('Campi del primo album:', ', '.join(sorted(rg.keys()))[:400])
        pt = rg.get('primary-type') or rg.get('primary_type') or ''
        if pt not in ('Album', 'EP'): continue
        sec = rg.get('secondary-types') or []
        if any(x in EXCLUDE for x in sec): continue
        sc = score(rg)   # anche 0: se mancano tutti i segnali, l'indice si riempie comunque di album ed EP
        ac = ''.join((x.get('name') or (x.get('artist') or {}).get('name') or '') + (x.get('joinphrase') or '') for x in (rg.get('artist-credit') or []))
        gen = sorted((rg.get('genres') or []), key=lambda g: -int(g.get('count') or 0))
        if not gen: gen = sorted((rg.get('tags') or []), key=lambda g: -int(g.get('count') or 0))
        typ = ('A' if pt == 'Album' else 'E') + ''.join(SEC[x] for x in sec if x in SEC)
        row = '|'.join([str(rg.get('id', '')).replace('-', ''), clean(rg.get('title')), clean(ac), str(rg.get('first-release-date') or '')[:4], typ, clean(', '.join(g.get('name', '') for g in gen[:2]))])
        if len(row) < 40: continue
        item = (sc, n, row)
        if len(heap) < top: heapq.heappush(heap, item)
        elif sc > heap[0][0]: heapq.heapreplace(heap, item)
        kept += 1
    log(f'Album letti: {n:,} · righe non leggibili: {bad:,} · album ed EP validi: {kept:,} · tenuti: {len(heap):,}')
    if heap: log(f'Punteggio minimo tenuto: {min(h[0] for h in heap)} · massimo: {max(h[0] for h in heap)}')
    rows = [r for _, _, r in sorted(heap, key=lambda x: (-x[0], x[1]))]   # dal piu diffuso
    return '\n'.join(rows) + '\n', len(rows)

def embed(html_path, text, built, dump):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as g: g.write(text.encode('utf-8'))
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    html = open(html_path, encoding='utf-8').read()
    tag = f'<script type="text/plain" id="mbIndexData" data-built="{built}" data-dump="{dump}">{b64}</script>'
    new, n = re.subn(r'<script type="text/plain" id="mbIndexData"[^>]*>[^<]*</script>', lambda _: tag, html, count=1)
    if n == 0: new = html.replace('</body>', tag + '\n</body>', 1)
    open(html_path, 'w', encoding='utf-8').write(new)
    log(f'Indice inserito in {html_path} ({len(b64) / 1048576:.2f} MB, archivio {dump})')

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    html, top, minimum = sys.argv[1], int(arg('--top', 80000)), int(arg('--min', 20000))
    built = arg('--date') or datetime.date.today().isoformat()
    if '--local' in sys.argv:
        src = arg('--local'); dump = os.path.basename(src)
        text, n = build(src, top)
    else:
        log('Cerco l\'archivio MusicBrainz piu recente…')
        dump, resp = find_dump()
        size = resp.headers.get('Content-Length')
        log(f'Scarico e leggo i release group (archivio {dump}' + (f', {int(size) / 1048576:.0f} MB' if size else '') + ')…')
        text, n = build(resp, top)
    if n < minimum: raise SystemExit(f'Indice sospetto ({n} album): non lo inserisco')
    embed(html, text, built, dump)

if __name__ == '__main__': main()
