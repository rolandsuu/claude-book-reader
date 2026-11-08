// Book Reader: library, EPUB (epub.js) and PDF (pdf.js) views for Claude Code's side panel.

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const api = {
  async get(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  },
  post(url, body, keepalive = false) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive }).catch(() => {});
  },
};

const ICON = {
  library: '<svg viewBox="0 0 24 24"><path d="M4.5 4h3.5v16H4.5zM10 4h3.5v16H10z"/><path d="M15.6 5.1l3.3-.8 3.6 15.3-3.3.8z"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" stroke-width="2.4"/></svg>',
  prev: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  next: '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  theme: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
};

const SERIF = '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif';
const SANS = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", system-ui, sans-serif';
const DEFAULTS = { theme: 'auto', fontSize: 150, font: 'original', lineHeight: 'original', flow: 'paged', pdfFlow: 'scroll', pdfZoom: 'page-width' };

let settings = { ...DEFAULTS };
try { Object.assign(settings, JSON.parse(localStorage.getItem('br-settings') || '{}')); } catch {}

const darkMQ = matchMedia('(prefers-color-scheme: dark)');
const isDark = () => settings.theme === 'dark' || (settings.theme === 'auto' && darkMQ.matches);
let engine = null;

function applyTheme() {
  const root = document.documentElement;
  if (settings.theme === 'auto') root.removeAttribute('data-theme');
  else root.dataset.theme = settings.theme;
  engine?.onTheme?.();
}
darkMQ.addEventListener('change', applyTheme);

function saveSettings(patch) {
  Object.assign(settings, patch);
  try { localStorage.setItem('br-settings', JSON.stringify(settings)); } catch {}
  api.post('/api/settings', patch);
}

let toastTimer;
function toast(text) {
  let el = $('.toast');
  if (!el) { el = document.createElement('div'); el.className = 'toast'; document.body.append(el); }
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

function coverHTML(b) {
  return `<div class="cover">${b.hasCover ? `<img loading="lazy" src="/api/book/${b.id}/cover" alt="" onerror="this.remove()">` : ''}<div class="ph">${esc(b.title)}</div></div>`;
}
const pctOf = (b) => (typeof b.progress?.percent === 'number' ? Math.round(b.progress.percent * 100) : null);

// ------------------------------------------------------------------ library

async function showLibrary() {
  document.title = 'Library';
  $('#app').innerHTML = `
    <div class="library">
      <div class="lib-head"><h1>Library</h1><button class="icon-btn" id="theme" title="Theme: ${settings.theme}">${ICON.theme}</button></div>
      <input class="search" type="search" placeholder="Search your books" autocomplete="off" spellcheck="false">
      <div id="lib"><div class="empty">Loading your books…</div></div>
      <div class="tip">While you read, ask Claude in the chat about the page you are on or the text you select.</div>
    </div>`;
  $('#theme').onclick = () => {
    const order = ['auto', 'light', 'dark'];
    saveSettings({ theme: order[(order.indexOf(settings.theme) + 1) % 3] });
    applyTheme();
    $('#theme').title = `Theme: ${settings.theme}`;
    toast(`Theme: ${settings.theme === 'auto' ? 'match system' : settings.theme}`);
  };
  let data;
  try { data = await api.get('/api/library'); } catch (e) {
    $('#lib').innerHTML = `<div class="empty">Could not load the library (${esc(e.message)}).</div>`;
    return;
  }
  const books = data.books;
  const search = $('.search');
  search.placeholder = `Search ${books.length} books`;
  const render = () => {
    const q = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const match = (b) => q.every((t) => `${b.title} ${b.author || ''}`.toLowerCase().includes(t));
    const shown = books.filter(match);
    const recent = !q.length ? books.find((b) => b.progress?.updated) : null;
    let html = '';
    if (recent) {
      const p = pctOf(recent) ?? 0;
      html += `<div class="section-label">Continue reading</div>
        <a class="hero" href="/read/${recent.id}">${coverHTML(recent)}
          <div class="meta"><div class="t">${esc(recent.title)}</div>${recent.author ? `<div class="a">${esc(recent.author)}</div>` : ''}
          <div class="resume">${esc(recent.progress.label || '')}${recent.progress.label ? ' · ' : ''}${p}%</div>
          <div class="bar"><i style="width:${p}%"></i></div></div></a>`;
    }
    html += `<div class="section-label">${q.length ? `${shown.length} found` : 'All books'}</div><ul class="list">`;
    for (const b of shown) {
      const p = pctOf(b);
      const bits = [b.format.toUpperCase()];
      if (p !== null) bits.push(p >= 99 ? 'finished' : `${p}%`);
      if (b.cloud) bits.push('in iCloud');
      html += `<li><a class="row" href="/read/${b.id}">${coverHTML(b)}<div class="meta"><div class="t">${esc(b.title)}</div>${b.author ? `<div class="a">${esc(b.author)}</div>` : ''}<div class="s">${bits.join(' · ')}</div></div></a></li>`;
    }
    html += '</ul>';
    if (!shown.length) html += `<div class="empty">No books match “${esc(search.value)}”.</div>`;
    $('#lib').innerHTML = html;
  };
  search.oninput = render;
  search.onkeydown = (e) => { if (e.key === 'Enter') $('#lib a')?.click(); };
  document.onkeydown = (e) => { if (e.key === '/' && document.activeElement !== search) { e.preventDefault(); search.focus(); } };
  render();
}

// ------------------------------------------------------------------ reader shell

function readerShell() {
  $('#app').innerHTML = `
    <div class="reader">
      <header class="top">
        <a class="icon-btn" href="/" title="Library">${ICON.library}</a>
        <button class="icon-btn" data-act="toc" title="Contents and search (T)">${ICON.list}</button>
        <div class="heading"><div class="bt"></div><div class="ch"></div></div>
        <button class="icon-btn aa" data-act="settings" title="Display">Aa</button>
      </header>
      <main class="stage">
        <div id="view"></div>
        <button class="edge prev" data-act="prev" aria-label="Previous page">${ICON.prev}</button>
        <button class="edge next" data-act="next" aria-label="Next page">${ICON.next}</button>
        <div class="loading"><div class="lt"></div><div class="lbar indeterminate"><i></i></div></div>
      </main>
      <footer class="bottom">
        <button class="icon-btn" data-act="prev" title="Previous (←)">${ICON.prev}</button>
        <input class="scrub" type="range" min="0" max="1000" value="0" aria-label="Position in book">
        <span class="where"></span>
        <button class="icon-btn" data-act="next" title="Next (→)">${ICON.next}</button>
      </footer>
      <div class="scrim"></div>
      <aside class="drawer">
        <header><h2>Contents</h2><button class="icon-btn" data-act="close">${ICON.close}</button></header>
        <div class="tabs"><button class="on" data-tab="toc">Contents</button><button data-tab="find">Search</button></div>
        <div class="body toc" data-pane="toc"><div class="note">Loading…</div></div>
        <div class="body" data-pane="find" hidden>
          <div class="find-box"><input type="search" placeholder="Search in this book" spellcheck="false"></div>
          <ul class="hits"></ul>
        </div>
      </aside>
      <div class="pop"></div>
    </div>`;
  const ui = {
    root: $('.reader'), stage: $('.stage'), view: $('#view'), title: $('.bt'), chapter: $('.ch'),
    scrub: $('.scrub'), where: $('.where'), loading: $('.loading'), drawer: $('.drawer'), scrim: $('.scrim'),
    pop: $('.pop'), toc: $('[data-pane="toc"]'), hits: $('.hits'), find: $('.find-box input'),
  };
  ui.setLoading = (text, frac) => {
    ui.loading.hidden = false;
    if (text != null) $('.lt', ui.loading).textContent = text;
    const bar = $('.lbar', ui.loading);
    bar.classList.toggle('indeterminate', frac == null);
    $('i', bar).style.width = frac == null ? '30%' : `${Math.round(frac * 100)}%`;
  };
  ui.fail = (msg) => {
    ui.loading.hidden = false;
    ui.loading.innerHTML = `<div class="err">${esc(msg)}</div><a href="/">Back to the library</a>`;
  };
  let scrubbing = false;
  ui.setWhere = (frac, text) => {
    ui.where.textContent = text;
    if (!scrubbing && Number.isFinite(frac)) {
      ui.scrub.value = Math.round(frac * 1000);
      ui.scrub.style.setProperty('--p', `${frac * 100}%`);
    }
  };
  ui.scrub.addEventListener('input', () => {
    scrubbing = true;
    ui.scrub.style.setProperty('--p', `${ui.scrub.value / 10}%`);
    ui.where.textContent = `${Math.round(ui.scrub.value / 10)}%`;
  });
  ui.scrub.addEventListener('change', () => { scrubbing = false; engine?.goFraction(ui.scrub.value / 1000); });
  return ui;
}

function wireShell(ui) {
  const openDrawer = (tab = 'toc') => {
    closePop();
    ui.drawer.classList.add('show'); ui.scrim.classList.add('show');
    $$('.tabs button', ui.drawer).forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    $$('[data-pane]', ui.drawer).forEach((p) => { p.hidden = p.dataset.pane !== tab; });
    $('h2', ui.drawer).textContent = tab === 'toc' ? 'Contents' : 'Search';
    if (tab === 'find') setTimeout(() => ui.find.focus(), 50);
    else $('.current', ui.toc)?.scrollIntoView({ block: 'center' });
  };
  const closeDrawer = () => { ui.drawer.classList.remove('show'); ui.scrim.classList.remove('show'); };
  const closePop = () => ui.pop.classList.remove('show');
  ui.closeDrawer = closeDrawer;
  ui.openDrawer = openDrawer;
  ui.scrim.onclick = () => { closeDrawer(); closePop(); };
  ui.root.addEventListener('click', (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    const tab = e.target.closest('[data-tab]')?.dataset.tab;
    if (tab) openDrawer(tab);
    if (!act) return;
    if (act === 'prev') engine?.prev();
    if (act === 'next') engine?.next();
    if (act === 'toc') ui.drawer.classList.contains('show') ? closeDrawer() : openDrawer('toc');
    if (act === 'close') closeDrawer();
    if (act === 'settings') {
      if (ui.pop.classList.toggle('show')) { renderSettings(ui); ui.scrim.classList.add('show'); ui.scrim.style.background = 'transparent'; }
      else ui.scrim.classList.remove('show');
    }
  });
  ui.scrim.addEventListener('transitionend', () => { if (!ui.scrim.classList.contains('show')) ui.scrim.style.background = ''; });

  let findTimer;
  ui.find.addEventListener('input', () => {
    clearTimeout(findTimer);
    findTimer = setTimeout(() => runSearch(ui, ui.find.value.trim()), 350);
  });
  ui.find.addEventListener('keydown', (e) => { if (e.key === 'Enter') { clearTimeout(findTimer); runSearch(ui, ui.find.value.trim()); } });

  ui.onKey = (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target?.closest?.('input, textarea, [contenteditable]');
    if (e.key === 'Escape') { closeDrawer(); closePop(); ui.scrim.classList.remove('show'); ui.root.classList.remove('immersive'); return; }
    if (typing) return;
    const paged = engine?.isPaged?.();
    const keys = paged
      ? { ArrowRight: 1, ArrowDown: 1, PageDown: 1, ' ': 1, ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }
      : { ArrowRight: 1, ArrowLeft: -1 };
    let dir = keys[e.key];
    if (e.key === ' ' && e.shiftKey && paged) dir = -1;
    if (dir) { e.preventDefault(); dir > 0 ? engine?.next() : engine?.prev(); return; }
    if (e.key === 't') openDrawer('toc');
    else if (e.key === '/') { e.preventDefault(); openDrawer('find'); }
    else if (e.key === 'f') ui.root.classList.toggle('immersive');
  };
  document.addEventListener('keydown', ui.onKey);
}

let searchRun = 0;
async function runSearch(ui, q) {
  const run = ++searchRun;
  ui.hits.innerHTML = '';
  if (q.length < 2) return;
  const note = document.createElement('li');
  note.className = 'note';
  note.textContent = 'Searching…';
  ui.hits.append(note);
  let n = 0;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig');
  for await (const hit of engine.search(q)) {
    if (run !== searchRun) return;
    const li = document.createElement('li');
    li.innerHTML = `<a href="#"><span class="loc">${esc(hit.label || '')}</span>${esc(hit.excerpt).replace(re, (m) => `<mark>${m}</mark>`)}</a>`;
    li.firstChild.onclick = (e) => { e.preventDefault(); engine.goTo(hit.target, q); ui.closeDrawer(); };
    note.before(li);
    if (++n >= 300) break;
  }
  if (run === searchRun) note.textContent = n ? `${n}${n >= 300 ? '+' : ''} result${n === 1 ? '' : 's'}` : 'No results.';
}

function renderSettings(ui) {
  const isPdf = engine?.kind === 'pdf';
  const seg = (key, opts) => `<div class="seg" data-key="${key}">${opts.map(([v, l, cls]) => `<button data-v="${v}" class="${String(settings[key]) === String(v) ? 'on' : ''} ${cls || ''}">${l}</button>`).join('')}</div>`;
  let html = `<div><div class="lbl">Theme</div>${seg('theme', [['auto', 'Auto'], ['light', 'Light'], ['dark', 'Dark']])}</div>`;
  if (isPdf) {
    html += `<div><div class="lbl">Layout</div>${seg('pdfFlow', [['scroll', 'Scroll'], ['pages', 'One page']])}</div>`;
    html += `<div><div class="lbl">Zoom</div><div class="stepper"><button data-zoom="-1">−</button><span data-zoom="fit">${engine.zoomLabel()}</span><button data-zoom="1">+</button></div></div>`;
  } else {
    html += `<div><div class="lbl">Text size</div><div class="stepper"><button data-size="-10">A−</button><span>${settings.fontSize}%</span><button data-size="10">A+</button></div></div>`;
    html += `<div><div class="lbl">Font</div>${seg('font', [['original', 'Book'], ['serif', 'Serif', 'serif'], ['sans', 'Sans']])}</div>`;
    html += `<div><div class="lbl">Line spacing</div>${seg('lineHeight', [['original', 'Book'], ['1.5', 'Normal'], ['1.8', 'Loose']])}</div>`;
    html += `<div><div class="lbl">Layout</div>${seg('flow', [['paged', 'Pages'], ['scroll', 'Scroll']])}</div>`;
  }
  ui.pop.innerHTML = html;
  ui.pop.onclick = (e) => {
    const b = e.target.closest('button, [data-zoom]');
    if (!b) return;
    const key = b.closest('[data-key]')?.dataset.key;
    if (key) {
      saveSettings({ [key]: key === 'fontSize' ? +b.dataset.v : b.dataset.v });
      if (key === 'theme') applyTheme();
      else engine?.onSettings(key);
    } else if (b.dataset.size) {
      saveSettings({ fontSize: Math.max(60, Math.min(220, settings.fontSize + +b.dataset.size)) });
      engine?.onSettings('fontSize');
    } else if (b.dataset.zoom) {
      engine?.zoom(b.dataset.zoom);
    }
    renderSettings(ui);
  };
}

function progressSaver(id) {
  let pending = null;
  let timer = 0;
  const flush = (keepalive = false) => {
    clearTimeout(timer);
    if (!pending) return;
    api.post(`/api/book/${id}/progress`, pending, keepalive);
    pending = null;
  };
  addEventListener('pagehide', () => flush(true));
  document.addEventListener('visibilitychange', () => { if (document.hidden) flush(true); });
  return {
    push(data) { pending = data; clearTimeout(timer); timer = setTimeout(flush, 600); },
    flush,
  };
}

function selectionReporter(id, labelFn) {
  let timer = 0;
  let last = '';
  let hinted = false;
  return (text) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      text = (text || '').trim();
      if (!text || text === last) return;
      last = text;
      api.post('/api/selection', { id, text, label: labelFn() });
      if (!hinted && text.length > 3) { hinted = true; toast('Ask Claude about this selection in the chat'); }
    }, 500);
  };
}

async function fetchBuffer(url, onProgress) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`The book file could not be read (HTTP ${r.status}).`);
  const total = +r.headers.get('Content-Length') || 0;
  if (!r.body || !total) return r.arrayBuffer();
  const reader = r.body.getReader();
  const out = new Uint8Array(total);
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    out.set(value, got);
    got += value.length;
    onProgress(got / total);
  }
  return out.buffer;
}

function makeWheelTurner(engine) {
  let locked = false;
  let acc = 0;
  let idle = 0;
  return (e) => {
    if (!engine.isPaged()) return;
    e.preventDefault();
    clearTimeout(idle);
    idle = setTimeout(() => { locked = false; acc = 0; }, 200);
    if (locked) return;
    acc += Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (Math.abs(acc) > 45) { locked = true; acc > 0 ? engine.next() : engine.prev(); }
  };
}

// ------------------------------------------------------------------ EPUB

async function EpubEngine(book, ui) {
  const id = book.id;
  const paged = settings.flow !== 'scroll';
  ui.root.classList.toggle('flow-scroll', !paged);
  let src;
  if (book.unpacked) src = `${location.origin}/api/book/${id}/epub/`;
  else src = await fetchBuffer(`/api/book/${id}/file`, (f) => ui.setLoading(null, f));
  ui.setLoading(null, null);
  const ebook = book.unpacked ? ePub(src, { openAs: 'directory' }) : ePub(src);
  await ebook.ready;

  const rendition = ebook.renderTo(ui.view, {
    width: '100%', height: '100%', spread: 'none', allowScriptedContent: false,
    flow: paged ? 'paginated' : 'scrolled', manager: paged ? 'default' : 'continuous',
  });
  const saver = progressSaver(id);
  let lastLoc = null;
  let haveLocations = false;
  let flat = [];
  const self = { kind: 'epub', rendition, ebook, debug: () => ({ want, inFlight, lastLoc: lastLoc?.start?.cfi }) };

  // After every resize epub.js re-renders at the spot it last reported, which can be stale (a jump
  // that has not reported yet) or junk (reported while the side panel was hidden or animating shut).
  // Re-render at our own spot instead, and skip the layout while the panel has no real size.
  // This must be set before rendition.start() binds it, which happens on a later animation frame.
  let want = null;
  let inFlight = 0;
  const hiddenStage = () => document.hidden || ui.view.clientWidth < 120 || ui.view.clientHeight < 120;
  rendition.onResized = function (size, cfi) {
    this.emit('resized', { width: size.width, height: size.height }, cfi);
    if (hiddenStage()) return;
    const target = cfi || want || this.location?.start?.cfi;
    if (target) display(target);
  };
  // A resize in the middle of a display throws away the half-loaded view, and epub.js then never
  // settles that display, so its queue (and every later jump) hangs. Hold resizes until displays end.
  let heldResize = false;
  const releaseResize = () => {
    if (!heldResize || inFlight || rendition.displaying) return;
    heldResize = false;
    rendition.manager?.resize();
  };
  rendition.on('started', () => { // fires inside start(), after the manager exists and before it binds this
    rendition.manager.onResized = function () {
      if (inFlight || rendition.displaying) heldResize = true;
      else this.resize();
    };
  });
  rendition.on('displayed', () => setTimeout(releaseResize, 0));
  const reportSelection = selectionReporter(id, () => ui.chapter.textContent);

  const contentCss = () => {
    const dark = isDark();
    let css = `:root { color-scheme: ${dark ? 'dark' : 'light'} !important; }
      html, body { background: transparent !important; }
      body { color: ${dark ? '#e2e2e2' : '#141414'} !important; }
      a { color: inherit !important; }
      ::selection { background: rgba(128,128,128,.38); }`;
    if (dark) css += `body *:not(img):not(svg):not(svg *):not(video):not(image) { color: inherit !important; background-color: transparent !important; border-color: #3a3a3a !important; }`;
    if (settings.font !== 'original') {
      css += `body, body *:not(pre):not(code):not(kbd):not(samp):not(tt):not(pre *) { font-family: ${settings.font === 'serif' ? SERIF : SANS} !important; }`;
    }
    if (settings.lineHeight !== 'original') css += `body p, body li, body blockquote, body dd, body div { line-height: ${settings.lineHeight} !important; }`;
    if (!paged) css += `body { max-width: 42em !important; margin: 0 auto !important; padding: 12px 26px !important; box-sizing: border-box !important; }`;
    return css;
  };
  const styleContents = (contents) => {
    const doc = contents.document;
    let st = doc.getElementById('br-style');
    if (!st) { st = doc.createElement('style'); st.id = 'br-style'; }
    st.textContent = contentCss();
    (doc.head || doc.documentElement).append(st); // keep it last so it wins
  };
  const wheel = makeWheelTurner(self);
  rendition.hooks.content.register((contents) => {
    styleContents(contents);
    const doc = contents.document;
    doc.addEventListener('keydown', ui.onKey);
    doc.addEventListener('wheel', wheel, { passive: false });
    doc.addEventListener('click', (e) => {
      if (!paged || e.target.closest('a[href]')) return;
      const sel = contents.window.getSelection();
      if (sel && !sel.isCollapsed) return;
      const fr = contents.window.frameElement.getBoundingClientRect();
      const st = ui.stage.getBoundingClientRect();
      const rel = (fr.left + e.clientX - st.left) / st.width;
      if (rel < 0.25) self.prev();
      else if (rel > 0.75) self.next();
      else ui.root.classList.toggle('immersive');
    });
    doc.addEventListener('selectionchange', () => reportSelection(contents.window.getSelection()?.toString()));
  });
  ui.stage.addEventListener('wheel', (e) => { if (!e.target.closest('.loading')) wheel(e); }, { passive: false });
  rendition.themes.fontSize(`${settings.fontSize}%`);

  const sectionFor = (href) => {
    const path = (href || '').split('#')[0];
    let s = null;
    try { s = ebook.spine.get(path); } catch {}
    if (!s) {
      const base = decodeURIComponent(path.split('/').pop());
      s = ebook.spine.spineItems.find((x) => decodeURIComponent(x.href.split('/').pop()) === base) || null;
    }
    return s;
  };
  const chapterItem = (index, startNode = null) => {
    let best = null;
    for (const f of flat) {
      if (f.index < 0 || f.index > index) continue;
      if (f.index < index || !f.hash || !startNode) { best = f; continue; }
      // Same file: the chapter has started only if its anchor is at or before the top of the page.
      const el = startNode.ownerDocument?.getElementById(f.hash);
      if (!el || el === startNode || el.contains(startNode) || (el.compareDocumentPosition(startNode) & 4)) best = f;
    }
    return best;
  };

  const tidy = (s) => s.replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim().slice(0, 5000);
  // Scrolled layout: epub.js's start/end ranges don't resolve there, so read what the stage shows.
  const scrolledText = () => {
    const box = ui.view.getBoundingClientRect();
    const out = [];
    for (const c of rendition.getContents()) {
      const frame = c.window?.frameElement;
      const doc = c.document;
      if (!frame || !doc?.body) continue;
      const fr = frame.getBoundingClientRect();
      const top = Math.max(box.top, fr.top) - fr.top;
      const bottom = Math.min(box.bottom, fr.bottom) - fr.top;
      if (bottom - top < 8) continue;
      const nodes = [];
      const tw = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      while (tw.nextNode()) if (tw.currentNode.data.trim()) nodes.push(tw.currentNode);
      const r = doc.createRange();
      const rect = (n) => { r.selectNodeContents(n); return r.getBoundingClientRect(); };
      let lo = 0, hi = nodes.length; // first text node that reaches below the top edge
      while (lo < hi) { const m = (lo + hi) >> 1; if (rect(nodes[m]).bottom <= top) lo = m + 1; else hi = m; }
      const first = lo;
      hi = nodes.length; // last text node that starts above the bottom edge
      while (lo < hi) { const m = (lo + hi) >> 1; if (rect(nodes[m]).top < bottom) lo = m + 1; else hi = m; }
      const last = lo - 1;
      if (first > last) continue;
      r.setStart(nodes[first], 0);
      r.setEnd(nodes[last], nodes[last].length);
      out.push(r.toString());
    }
    return out.join('\n');
  };

  const visibleText = (loc) => {
    if (!paged) { try { return tidy(scrolledText()); } catch { return ''; } }
    try {
      const a = rendition.getRange(loc.start.cfi);
      const doc = a.startContainer.ownerDocument;
      const r = doc.createRange();
      r.setStart(a.startContainer, a.startOffset);
      try {
        const b = rendition.getRange(loc.end.cfi);
        if (b.endContainer.ownerDocument === doc) r.setEnd(b.endContainer, b.endOffset);
        else r.setEndAfter(doc.body.lastChild);
      } catch { r.setEndAfter(doc.body.lastChild); }
      return tidy(r.toString());
    } catch { return ''; }
  };

  const onRelocated = (loc) => {
    if (hiddenStage()) return; // the panel is hidden or collapsing, so this is not where the reader is
    lastLoc = loc;
    if (!inFlight) want = loc.start.cfi;
    const idx = loc.start.index;
    let startNode = null;
    try { startNode = rendition.getRange(loc.start.cfi)?.startContainer || null; } catch {}
    const item = chapterItem(idx, startNode);
    const label = item ? item.label : '';
    const d = loc.start.displayed || {};
    let frac;
    if (haveLocations) frac = ebook.locations.percentageFromCfi(loc.start.cfi);
    else frac = (idx + ((d.page || 1) - 1) / Math.max(1, d.total || 1)) / Math.max(1, ebook.spine.length);
    if (loc.atEnd) frac = 1;
    const pageInfo = paged && d.total > 1 ? `page ${d.page} of ${d.total}` : '';
    ui.chapter.textContent = [label, pageInfo].filter(Boolean).join(' · ');
    ui.setWhere(frac, `${Math.round(frac * 100)}%`);
    $$('a.current', ui.toc).forEach((a) => a.classList.remove('current'));
    if (item) item.el?.classList.add('current');
    saver.push({ location: loc.start.cfi, percent: frac, label: [label, pageInfo].filter(Boolean).join(', '), text: visibleText(loc) });
  };
  rendition.on('relocated', onRelocated);

  // Contents
  let tocDone;
  self.tocReady = new Promise((r) => { tocDone = r; });
  ebook.loaded.navigation.then((nav) => {
    flat = [];
    const build = (items, depth) => {
      const ol = document.createElement('ol');
      for (const it of items || []) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '#';
        a.textContent = (it.label || '').trim() || 'Untitled';
        a.onclick = (e) => { e.preventDefault(); ui.closeDrawer(); display(it.href); };
        li.append(a);
        const s = sectionFor(it.href);
        const hash = decodeURIComponent((it.href || '').split('#')[1] || '');
        flat.push({ label: a.textContent, href: it.href, index: s ? s.index : -1, hash, el: a, depth });
        if (it.subitems?.length) li.append(build(it.subitems, depth + 1));
        ol.append(li);
      }
      return ol;
    };
    ui.toc.innerHTML = '';
    if (nav.toc?.length) ui.toc.append(build(nav.toc, 0));
    else ui.toc.innerHTML = '<div class="note">This book has no table of contents.</div>';
    if (lastLoc) onRelocated(lastLoc);
    tocDone();
  }, () => tocDone());

  // epub.js aims at a spot before the chapter's styles and font size have reflowed it, so the first
  // landing is short of the target. Once the layout settles, aim again (the view is loaded by then).
  const settle = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 150))));
  const display = async (target) => {
    if (target) want = target;
    inFlight++;
    try {
      await rendition.display(target);
      if (target && /[#!]/.test(target)) { await settle(); await rendition.display(target); }
    } catch (e) {
      console.warn('display failed', target, e);
      const s = sectionFor(target);
      if (s) await rendition.display(s.href);
    } finally {
      inFlight--;
      setTimeout(releaseResize, 0);
    }
  };

  Object.assign(self, {
    isPaged: () => paged,
    next: () => rendition.next(),
    prev: () => rendition.prev(),
    goFraction: (f) => {
      if (haveLocations) return display(ebook.locations.cfiFromPercentage(Math.min(0.9999, f)));
      const s = ebook.spine.get(Math.min(ebook.spine.length - 1, Math.floor(f * ebook.spine.length)));
      if (s) display(s.href);
    },
    goTo: (cfi) => display(cfi),
    goChapter: async (words) => {
      await self.tocReady;
      const it = matchChapter(flat, words);
      if (it) await display(it.href);
      return !!it;
    },
    onTheme: () => rendition.getContents().forEach(styleContents),
    onSettings: async (key) => {
      if (key === 'flow') { saver.flush(); location.reload(); return; }
      if (key === 'fontSize') rendition.themes.fontSize(`${settings.fontSize}%`);
      rendition.getContents().forEach(styleContents);
      const cfi = lastLoc?.start?.cfi;
      await new Promise((r) => setTimeout(r, 60));
      if (cfi) display(cfi);
    },
    async *search(q) {
      for (const section of ebook.spine.spineItems) {
        let found = [];
        try {
          await section.load(ebook.load.bind(ebook));
          found = section.find(q) || [];
        } catch {}
        try { section.unload(); } catch {}
        const label = chapterItem(section.index)?.label || '';
        for (const r of found) yield { target: r.cfi, excerpt: r.excerpt.trim(), label };
      }
    },
  });

  const saved = book.progress?.location;
  await display(saved || undefined);
  ui.loading.hidden = true;

  // Exact percentages need "locations"; build them once per book and keep them on the server.
  (async () => {
    const CHARS = 1200;
    try {
      const cached = await api.get(`/api/book/${id}/locations`);
      if (cached.locations && cached.chars === CHARS) ebook.locations.load(cached.locations);
      else {
        await ebook.locations.generate(CHARS);
        api.post(`/api/book/${id}/locations`, { locations: ebook.locations.save(), chars: CHARS });
      }
      haveLocations = ebook.locations.length() > 0;
      if (lastLoc) onRelocated(lastLoc);
    } catch (e) { console.warn('locations', e); }
  })();
  return self;
}

// ------------------------------------------------------------------ PDF

async function PdfEngine(book, ui) {
  const pdfjsLib = await import('/static/vendor/pdfjs/pdf.min.mjs');
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
  globalThis.pdfjsLib = pdfjsLib;
  const V = await import('/static/vendor/pdfjs/pdf_viewer.mjs');
  ui.root.classList.add('pdf');
  ui.view.innerHTML = '<div class="pdf-container"><div class="pdfViewer"></div></div>';
  const container = ui.view.firstElementChild;
  const eventBus = new V.EventBus();
  const linkService = new V.PDFLinkService({ eventBus, externalLinkTarget: 2 });
  const findController = new V.PDFFindController({ eventBus, linkService });
  const viewer = new V.PDFViewer({ container, viewer: container.firstElementChild, eventBus, linkService, findController, removePageBorders: true, textLayerMode: 1 });
  linkService.setViewer(viewer);
  const task = pdfjsLib.getDocument({
    url: `/api/book/${book.id}/file`, cMapUrl: '/static/vendor/pdfjs/cmaps/', cMapPacked: true,
    standardFontDataUrl: '/static/vendor/pdfjs/standard_fonts/', isEvalSupported: false,
  });
  task.onProgress = ({ loaded, total }) => { if (total) ui.setLoading(null, loaded / total); };
  const doc = await task.promise;
  const inited = new Promise((r) => eventBus.on('pagesinit', r, { once: true }));
  viewer.setDocument(doc);
  linkService.setDocument(doc, null);
  await inited;

  const count = doc.numPages;
  const saver = progressSaver(book.id);
  let outline = [];
  const self = { kind: 'pdf' };
  const labelFor = (n) => {
    let best = null;
    for (const o of outline) if (o.page && o.page <= n) best = o;
    return best;
  };
  const reportSelection = selectionReporter(book.id, () => ui.chapter.textContent);
  document.addEventListener('selectionchange', () => {
    if (container.contains(document.getSelection()?.anchorNode)) reportSelection(document.getSelection().toString());
  });

  const pageText = async (n) => {
    try {
      const tc = await (await doc.getPage(n)).getTextContent();
      return tc.items.map((i) => i.str + (i.hasEOL ? '\n' : '')).join('').replace(/[ \t]+/g, ' ').trim().slice(0, 5000);
    } catch { return ''; }
  };
  const applyLayout = () => {
    const pages = settings.pdfFlow === 'pages';
    ui.root.classList.toggle('flow-pages', pages);
    const n = viewer.currentPageNumber;
    viewer.scrollMode = pages ? V.ScrollMode.PAGE : V.ScrollMode.VERTICAL;
    viewer.currentScaleValue = pages ? 'page-fit' : String(settings.pdfZoom || 'page-width');
    viewer.currentPageNumber = n;
  };
  const onTheme = () => ui.root.classList.toggle('dark-pages', isDark());
  const onPage = (n) => {
    const item = labelFor(n);
    ui.chapter.textContent = item ? `${item.label} · page ${n}` : `Page ${n} of ${count}`;
    ui.setWhere(count > 1 ? (n - 1) / (count - 1) : 1, `${n} / ${count}`);
    $$('a.current', ui.toc).forEach((a) => a.classList.remove('current'));
    item?.el?.classList.add('current');
    pageText(n).then((text) => saver.push({
      location: String(n), page: n, pages: count, percent: n / count,
      label: item ? `${item.label}, page ${n} of ${count}` : `page ${n} of ${count}`, text,
    }));
  };
  eventBus.on('pagechanging', ({ pageNumber }) => onPage(pageNumber));
  let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const v = viewer.currentScaleValue;
      if (v === 'page-width' || v === 'page-fit' || v === 'auto') viewer.currentScaleValue = v;
    }, 120);
  });
  const wheel = makeWheelTurner(self);
  container.addEventListener('wheel', (e) => { if (self.isPaged() && !e.ctrlKey) wheel(e); }, { passive: false });

  // Contents from the PDF outline
  let tocDone;
  self.tocReady = new Promise((r) => { tocDone = r; });
  (async () => {
    const items = (await doc.getOutline().catch(() => null)) || [];
    const pageOf = async (dest) => {
      try {
        const d = typeof dest === 'string' ? await doc.getDestination(dest) : dest;
        if (!Array.isArray(d)) return null;
        const ref = d[0];
        if (ref && typeof ref === 'object') return (await doc.getPageIndex(ref)) + 1;
        return Number.isInteger(ref) ? ref + 1 : null;
      } catch { return null; }
    };
    const build = async (list) => {
      const ol = document.createElement('ol');
      for (const it of list) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '#';
        const page = await pageOf(it.dest);
        a.innerHTML = `${page ? `<span class="pg">${page}</span>` : ''}${esc((it.title || '').trim() || 'Untitled')}`;
        a.onclick = (e) => {
          e.preventDefault(); ui.closeDrawer();
          if (it.dest) linkService.goToDestination(it.dest); else if (page) viewer.currentPageNumber = page;
        };
        li.append(a);
        outline.push({ label: (it.title || '').trim(), page, el: a });
        if (it.items?.length) li.append(await build(it.items));
        ol.append(li);
      }
      return ol;
    };
    ui.toc.innerHTML = '';
    if (items.length) {
      ui.toc.append(await build(items));
      outline = outline.filter((o) => o.page).sort((a, b) => a.page - b.page);
    } else {
      ui.toc.innerHTML = '<div class="note">This PDF has no table of contents.</div>';
    }
    const jump = document.createElement('div');
    jump.className = 'find-box';
    jump.innerHTML = `<input type="number" min="1" max="${count}" placeholder="Go to page (1–${count})">`;
    jump.firstChild.onkeydown = (e) => {
      if (e.key === 'Enter') { const n = Math.max(1, Math.min(count, +e.target.value || 1)); viewer.currentPageNumber = n; ui.closeDrawer(); }
    };
    ui.toc.prepend(jump);
    onPage(viewer.currentPageNumber);
  })().finally(() => tocDone());

  Object.assign(self, {
    isPaged: () => settings.pdfFlow === 'pages',
    next: () => viewer.nextPage(),
    prev: () => viewer.previousPage(),
    goFraction: (f) => { viewer.currentPageNumber = Math.max(1, Math.min(count, Math.round(f * (count - 1)) + 1)); },
    goPage: (n) => { viewer.currentPageNumber = Math.max(1, Math.min(count, n)); },
    goChapter: async (words) => {
      await self.tocReady;
      const it = matchChapter(outline, words);
      if (it) viewer.currentPageNumber = it.page;
      return !!it;
    },
    goTo: (page, q) => {
      viewer.currentPageNumber = page;
      if (q) eventBus.dispatch('find', { source: self, type: '', query: q, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: false, matchDiacritics: false });
    },
    onTheme,
    onSettings: (key) => { if (key === 'pdfFlow') applyLayout(); },
    zoomLabel: () => {
      const v = viewer.currentScaleValue;
      return v === 'page-width' ? 'Fit width' : v === 'page-fit' ? 'Fit page' : `${Math.round(viewer.currentScale * 100)}%`;
    },
    zoom: (how) => {
      if (how === 'fit') {
        const next = viewer.currentScaleValue === 'page-width' ? 'page-fit' : 'page-width';
        viewer.currentScaleValue = next;
        saveSettings({ pdfZoom: next });
        return;
      }
      const s = Math.max(0.3, Math.min(5, viewer.currentScale * (how > 0 ? 1.15 : 1 / 1.15)));
      viewer.currentScale = s;
      if (settings.pdfFlow !== 'pages') saveSettings({ pdfZoom: s.toFixed(3) });
    },
    async *search(q) {
      const needle = q.toLowerCase();
      for (let n = 1; n <= count; n++) {
        const text = (await pageText(n)).replace(/\s+/g, ' ');
        const low = text.toLowerCase();
        let at = low.indexOf(needle);
        while (at >= 0) {
          const a = Math.max(0, at - 50);
          yield { target: n, label: `Page ${n}`, excerpt: `${a > 0 ? '…' : ''}${text.slice(a, at + needle.length + 70)}…` };
          at = low.indexOf(needle, at + needle.length);
        }
      }
    },
  });

  onTheme();
  applyLayout();
  const start = +book.progress?.page || 1;
  if (start > 1 && start <= count) viewer.currentPageNumber = start;
  ui.loading.hidden = true;
  onPage(viewer.currentPageNumber);
  return self;
}

// ------------------------------------------------------------------ start

function matchChapter(items, words) {
  const norm = (t) => (t || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const q = norm(words);
  if (!q) return null;
  const num = q.match(/^(?:chapter|ch|part|section)?\s*(\d+)$/)?.[1];
  const tests = [
    (l) => l === q,
    (l) => l.startsWith(q),
    num ? (l) => new RegExp(`^(?:chapter |part |section )?${num}\\b`).test(l) : null,
    (l) => l.includes(q),
    (l) => q.split(' ').every((w) => l.includes(w)),
  ].filter(Boolean);
  for (const t of tests) {
    const hit = items.find((it) => t(norm(it.label)));
    if (hit) return hit;
  }
  return null;
}

// Claude can steer the reader with /read/<id>?chapter=…, ?page=… (PDF) or ?find=….
async function applyUrlOptions(ui) {
  const params = new URLSearchParams(location.search);
  if (![...params.keys()].length) return;
  history.replaceState(null, '', location.pathname);
  const chapter = params.get('chapter');
  const page = parseInt(params.get('page') || '', 10);
  const find = params.get('find');
  if (chapter && !(await engine.goChapter(chapter))) toast(`No chapter matching “${chapter}”`);
  if (page && engine.goPage) engine.goPage(page);
  if (find) {
    ui.openDrawer('find');
    ui.find.value = find;
    runSearch(ui, find.trim());
  }
}

async function openReader(id) {
  const ui = readerShell();
  wireShell(ui);
  ui.setLoading('Opening…', null);
  let book;
  try { book = await api.get(`/api/book/${id}`); } catch {
    ui.fail('This book is not in the library any more.');
    return;
  }
  document.title = book.title;
  ui.title.textContent = book.title;
  ui.setLoading(book.cloud ? `Downloading ${book.title} from iCloud…` : book.title, null);
  try {
    engine = book.format === 'pdf' ? await PdfEngine(book, ui) : await EpubEngine(book, ui);
    globalThis.reader = engine; // for debugging from the console
    await applyUrlOptions(ui);
  } catch (e) {
    console.error(e);
    ui.fail(`Could not open this book: ${e?.message || e}`);
  }
}

(async () => {
  try { Object.assign(settings, await api.get('/api/settings')); } catch {}
  applyTheme();
  const m = location.pathname.match(/^\/read\/([0-9a-f]{12})$/);
  if (m) openReader(m[1]);
  else showLibrary();
})();
