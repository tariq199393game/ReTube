'use strict';
/* Grabit UI. Everything shown from remote sites is inserted as text, never as HTML. */
const $ = id => document.getElementById(id);
const native = window.GrabitNative || null;   // present inside the Android app
// iPhone: the app tells the page how much room the notch and home bar take
function setInsets(top, bottom) {
  if (top > 0) document.documentElement.style.setProperty('--sat', top + 'px');
  if (bottom > 0) document.documentElement.style.setProperty('--sab', bottom + 'px');
}
{ const q = new URLSearchParams(location.search); setInsets(parseFloat(q.get('sat')), parseFloat(q.get('sab'))); }

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

async function api(name, body) {
  const res = await fetch('api/' + name, body === undefined ? {} :
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (!res.ok) throw new Error(data.error || 'Something went wrong.');
  return data;
}

const proxied = (url, ref) => 'thumb?u=' + encodeURIComponent(url) + (ref ? '&r=' + encodeURIComponent(ref) : '') +
  (state.account ? '&a=' + encodeURIComponent(state.account) : '');
const mediaUrl = rel => 'media/' + rel.split('/').map(encodeURIComponent).join('/');
const fmtSize = n => !n ? '' : n > 1073741824 ? (n / 1073741824).toFixed(2) + ' GB' : n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
const fmtTime = s => { s = Math.round(s || 0); if (!s) return ''; const m = Math.floor(s / 60) % 60, hh = Math.floor(s / 3600); return (hh ? hh + ':' + String(m).padStart(2, '0') : m) + ':' + String(s % 60).padStart(2, '0'); };

let toastTimer;
function toast(msg) {
  $('toast').textContent = msg; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3200);
}

const state = { tab: 'video', mode: 'single', account: '', status: {}, lib: [], libFilter: 'all', view: [], viewAt: 0, images: null, playlist: null, seenDone: new Set(), search: null, jobCount: 0, firstPoll: true };

const TABS = {
  video: { head: 'Grab a video', placeholder: 'Paste a video link', button: 'Get Info', hint: 'YouTube, Facebook and most other sites.' },
  playlist: { head: 'Grab a playlist', placeholder: 'Paste a playlist or channel link', button: 'Get Playlist', hint: 'Lists every video so you can choose.' },
  images: { head: 'Grab images', placeholder: 'Paste a page or image link', button: 'Find Images', hint: 'Finds the pictures on a page so you can pick.' },
};

/* ------------------------------------------------------------ tabs */
// what the link box currently does: 'video', 'playlist' or 'images'
const kind = () => state.tab === 'video' && state.mode === 'playlist' ? 'playlist' : state.tab;
const PLAYLIST_LINK = /[?&]list=|\/playlist|\/channel\/|\/c\/|\/user\/|youtube\.com\/@|\/sets\/|\/album\/|\/videos\/?(\?|$)|\/shorts\/?$/i;

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll('#mode button').forEach(b => { b.classList.toggle('on', b.dataset.mode === mode); b.setAttribute('aria-checked', b.dataset.mode === mode); });
  if (state.tab === 'video') setTab('video');
}
document.querySelectorAll('#mode button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
// a pasted playlist link switches to Playlist by itself
function autoMode() {
  if (state.tab !== 'video') return;
  const v = $('url').value.trim();
  if (PLAYLIST_LINK.test(v) && !/[?&]v=/.test(v) && state.mode !== 'playlist') setMode('playlist');
}

function setTab(tab) {
  if (state.search) stopSearch(true);   // leaving the screen ends the search
  state.tab = tab;
  $('mode').hidden = tab !== 'video';
  document.querySelectorAll('.dock button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  const grabbing = tab === 'video' || tab === 'images';
  $('grab').hidden = !grabbing;
  $('library').hidden = tab !== 'library';
  $('settings').hidden = tab !== 'settings';
  $('jobsCard').hidden = !grabbing || !state.jobCount;
  window.scrollTo(0, 0);
  if (tab === 'library') { $('badge').hidden = true; return loadLibrary(); }
  if (!grabbing) return;
  const k = kind();
  $('headline').textContent = TABS[k].head;
  $('hero').dataset.art = k === 'images' ? 'images' : 'video';
  $('url').placeholder = TABS[k].placeholder;
  $('goLabel').textContent = TABS[k].button;
  $('hint').textContent = TABS[k].hint;
  $('error').hidden = true;
  $('result').replaceChildren();
  if (k === 'images' && state.images) renderImages();
  if (k === 'playlist' && state.playlist) renderPlaylist();
}
document.querySelectorAll('.dock button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));

function fail(msg) { $('error').textContent = msg; $('error').hidden = false; }

const sleep = ms => new Promise(r => setTimeout(r, ms));
const NOUN = { video: '', playlist: 'video', images: 'image' };

function searchIdle() {
  const btn = $('go');
  state.search = null;
  btn.disabled = false; btn.classList.remove('busy', 'stop');
  if (TABS[kind()]) $('goLabel').textContent = TABS[kind()].button;
}

// Stop the running search. Playlists and image searches hand back what they found so far.
function stopSearch(abandon) {
  const s = state.search;
  if (!s) return;
  api('search_stop', { id: s.id }).catch(() => {});
  if (abandon || s.kind === 'video') { s.dropped = true; searchIdle(); }
  else { s.stopping = true; $('go').disabled = true; $('goLabel').textContent = 'Finishing...'; }
}

async function go() {
  if (state.search) return stopSearch(false);
  const url = $('url').value.trim();
  if (!url) return fail('Paste a link first.');
  autoMode();
  const tab = kind(), btn = $('go');
  $('error').hidden = true; $('result').replaceChildren();
  const s = state.search = { kind: tab, id: 0 };
  btn.classList.add('busy', 'stop'); $('goLabel').textContent = 'Searching... tap to stop';
  try {
    s.id = (await api('search', { kind: tab, url, account: state.account })).id;
    let r;
    for (;;) {
      await sleep(450);
      if (s.dropped) return;
      r = await api('search?id=' + s.id);
      if (s.dropped) return;
      if (r.done) break;
      if (!s.stopping) {
        const n = r.found, noun = NOUN[tab];
        $('goLabel').textContent = n && noun ? `Stop · ${n} ${noun}${n === 1 ? '' : 's'} found` : 'Searching... tap to stop';
      }
    }
    if (r.error && !r.result) throw new Error(r.error);
    if (tab === 'video') renderVideo(r.result, url);
    else if (tab === 'playlist') { state.playlist = r.result; renderPlaylist(); }
    else { state.images = r.result; prepareImages(); renderImages(); }
  } catch (e) { if (!s.dropped) fail(e.message); }
  if (state.search === s) searchIdle();
}
$('go').addEventListener('click', go);
$('url').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
$('url').addEventListener('input', autoMode);

async function readClipboard() {
  if (native && native.clipboard) return native.clipboard();
  if (state.status.platform === 'ios') return (await api('clipboard')).text;
  return navigator.clipboard.readText();
}
if ((native && native.clipboard) || (navigator.clipboard && navigator.clipboard.readText)) $('paste').hidden = false;
$('paste').addEventListener('click', async () => {
  try { const t = (await readClipboard() || '').trim(); if (t) { $('url').value = t; go(); } else toast('Clipboard is empty'); }
  catch (e) { toast('Could not read the clipboard'); }
});

// in-page question box (the system one is not available inside every app shell)
function ask(message, yes) {
  return new Promise(done => {
    const close = v => { box.remove(); done(v); };
    const box = h('div', { class: 'ask', onclick: e => { if (e.target === box) close(false); } },
      h('div', {}, h('p', {}, message), h('div', { class: 'row end' },
        h('button', { class: 'ghost', type: 'button', onclick: () => close(false) }, 'Cancel'),
        h('button', { class: 'ghost danger', type: 'button', onclick: () => close(true) }, yes || 'Delete'))));
    document.body.append(box);
  });
}
// a link shared to the app from another app
window.grabitIncoming = link => { if (!TABS[kind()]) setTab('video'); $('url').value = link; go(); };

/* ------------------------------------------------------------ video */
function qualitySelect(options) {
  return h('select', {}, options.map(o => h('option', { value: o.id }, o.label + (o.size ? '  ·  ' + fmtSize(o.size) : ''))));
}

function renderVideo(info, url) {
  const sel = qualitySelect(info.options);
  const btn = h('button', { class: 'primary', type: 'button', onclick: async () => {
    btn.disabled = true;
    try { await api('download', { items: [{ url, title: info.title }], quality: sel.value, account: state.account }); toast('Download started'); pollSoon(); }
    catch (e) { fail(e.message); }
    btn.disabled = false;
  } }, 'Download');
  const thumb = info.thumb ? h('img', { src: proxied(info.thumb, info.url), alt: '', onerror: e => e.target.remove() }) : null;
  $('result').replaceChildren(
    h('div', { class: 'media' }, thumb, h('div', {},
      h('div', { class: 't' }, info.title),
      h('div', { class: 'meta' }, [info.site, info.uploader, fmtTime(info.duration)].filter(Boolean).join(' · ')))),
    h('label', {}, 'Quality:'), sel, btn);
}

/* ------------------------------------------------------------ playlist */
function renderPlaylist() {
  const pl = state.playlist, picked = new Set(pl.entries.map((_, i) => i));
  const quality = qualitySelect([{ id: 'best', label: 'Best quality' }, { id: '1080', label: '1080p' }, { id: '720', label: '720p' },
    { id: '480', label: '480p' }, { id: '360', label: '360p' }, { id: 'audio', label: 'Audio only' }]);
  const all = h('input', { type: 'checkbox', checked: true });
  const btn = h('button', { class: 'primary', type: 'button' });
  const boxes = [];
  const sync = () => { btn.textContent = `Download ${picked.size} video${picked.size === 1 ? '' : 's'}`; btn.disabled = !picked.size; all.checked = picked.size === pl.entries.length; };
  const rows = pl.entries.map((e, i) => {
    const box = h('input', { type: 'checkbox', checked: true });
    box.addEventListener('change', () => { box.checked ? picked.add(i) : picked.delete(i); sync(); });
    boxes.push(box);
    return h('label', { class: 'item' }, box,
      e.thumb ? h('img', { src: proxied(e.thumb), loading: 'lazy', alt: '', onerror: ev => ev.target.remove() }) : null,
      h('span', { class: 't' }, e.title), h('span', { class: 'd' }, fmtTime(e.duration)));
  });
  all.addEventListener('change', () => { boxes.forEach((b, i) => { b.checked = all.checked; all.checked ? picked.add(i) : picked.delete(i); }); sync(); });
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const items = pl.entries.filter((_, i) => picked.has(i)).map(e => ({ url: e.url, title: e.title }));
      await api('download', { items, quality: quality.value, account: state.account, folder: pl.entries.length > 1 ? pl.title : '' });
      toast(`${items.length} download${items.length === 1 ? '' : 's'} queued`); pollSoon();
    } catch (e) { fail(e.message); }
    sync();
  });
  sync();
  $('result').replaceChildren(
    h('div', { class: 't' }, pl.title), h('div', { class: 'meta' }, `${pl.entries.length} videos`),
    h('div', { class: 'bar' }, h('label', { class: 'check' }, all, 'Select all')),
    h('div', { class: 'list' }, rows), h('label', {}, 'Quality:'), quality, btn);
}

/* ------------------------------------------------------------ images */
const SIZES = [[0, 'Any size'], [200, '200px +'], [500, '500px +'], [1000, '1000px +']];

function prepareImages() {
  const im = state.images;
  im.type = 'all'; im.min = 0; im.picked = new Set();
  im.images.forEach(i => { i.state = 'wait'; i.type = i.type || ''; });
}

function loadPreview(img, tileImg) {
  // fetched as a blob so we learn the real type and size; then shown from memory
  return fetch(proxied(img.url, state.images.page)).then(r => { if (!r.ok) throw 0; return r.blob(); }).then(blob => new Promise((ok, bad) => {
    const mime = (blob.type || '').replace('image/', '').replace('jpeg', 'jpg').replace('svg+xml', 'svg').replace('x-icon', 'ico').replace('vnd.microsoft.icon', 'ico');
    if (mime) img.type = mime;
    img.bytes = blob.size;
    tileImg.onload = () => { img.w = tileImg.naturalWidth || img.w; img.h = tileImg.naturalHeight || img.h; img.state = 'ok'; ok(); };
    tileImg.onerror = bad;
    tileImg.src = URL.createObjectURL(blob);
  })).catch(() => { img.state = 'bad'; });
}

function renderImages() {
  const im = state.images, root = $('result');
  const visible = i => i.state !== 'bad' && (im.type === 'all' || i.type === im.type) &&
    (!im.min || i.state !== 'ok' || i.type === 'svg' || Math.max(i.w, i.h) >= im.min);
  const chips = h('div', { class: 'chips' }), sizeSel = h('select', {}, SIZES.map(([v, t]) => h('option', { value: v }, t)));
  const grid = h('div', { class: 'grid' }), count = h('div', { class: 'meta' });
  const btn = h('button', { class: 'primary', type: 'button' });
  const tiles = new Map();
  sizeSel.value = im.min;

  const refresh = () => {
    const types = {};
    im.images.forEach(i => { if (i.state !== 'bad' && i.type) types[i.type] = (types[i.type] || 0) + 1; });
    const total = im.images.filter(i => i.state !== 'bad').length;
    chips.replaceChildren(...[['all', total], ...Object.entries(types).sort((a, b) => b[1] - a[1])].map(([t, n]) =>
      h('button', { class: 'chip' + (im.type === t ? ' on' : ''), type: 'button', onclick: () => { im.type = t; refresh(); } }, `${t === 'all' ? 'All' : t.toUpperCase()} ${n}`)));
    let shown = 0, sel = 0;
    im.images.forEach(i => {
      const t = tiles.get(i), vis = visible(i);
      t.hidden = !vis;
      if (!vis) im.picked.delete(i);
      else { shown++; if (im.picked.has(i)) sel++; }
      t.classList.toggle('sel', im.picked.has(i));
      t.lastChild.textContent = [i.type && i.type.toUpperCase(), i.w && i.h ? `${i.w}×${i.h}` : '', fmtSize(i.bytes)].filter(Boolean).join(' · ');
    });
    count.textContent = `${shown} image${shown === 1 ? '' : 's'} shown · ${sel} selected`;
    btn.textContent = sel ? `Download ${sel} image${sel === 1 ? '' : 's'}` : 'Select images to download';
    btn.disabled = !sel;
  };

  const queue = [];
  im.images.forEach(i => {
    const pic = h('img', { alt: i.alt || '' });
    const tile = h('button', { class: 'tile', type: 'button', title: i.alt || i.url, onclick: () => { im.picked.has(i) ? im.picked.delete(i) : im.picked.add(i); refresh(); } },
      pic, h('span', { class: 'tick' }), h('span', { class: 'tag' }));
    tiles.set(i, tile); grid.append(tile);
    if (i.state !== 'bad') queue.push([i, pic]);
  });
  let active = 0, dirty = false;
  const pump = () => {
    while (active < 6 && queue.length) {
      const [i, pic] = queue.shift(); active++;
      loadPreview(i, pic).then(() => { active--; if (!dirty) { dirty = true; setTimeout(() => { dirty = false; if (state.images === im && grid.isConnected) refresh(); }, 150); } pump(); });
    }
  };
  sizeSel.addEventListener('change', () => { im.min = +sizeSel.value; refresh(); });
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await api('download_images', { page: im.page, title: im.title, urls: [...im.picked].map(i => i.url), account: state.account });
      toast('Download started'); pollSoon();
    } catch (e) { fail(e.message); }
    refresh();
  });
  root.replaceChildren(
    h('div', { class: 't' }, im.title), count,
    h('label', {}, 'Type:'), chips,
    h('div', { class: 'bar' }, sizeSel,
      h('button', { class: 'ghost', type: 'button', onclick: () => { im.images.forEach(i => { if (visible(i)) im.picked.add(i); }); refresh(); } }, 'Select all'),
      h('button', { class: 'ghost', type: 'button', onclick: () => { im.picked.clear(); refresh(); } }, 'None')),
    grid, btn);
  refresh(); pump();
}

/* ------------------------------------------------------------ downloads */
let pollTimer, pollFast = 0;
function pollSoon() { pollFast = 8; clearTimeout(pollTimer); poll(); }

function jobLine(j) {
  if (j.status === 'queued') return 'Waiting...';
  if (j.status === 'finishing') return 'Finishing...';
  if (j.status === 'running') return [j.progress + '%', fmtSize(j.size), j.speed ? fmtSize(j.speed) + '/s' : '', j.eta ? fmtTime(j.eta) + ' left' : ''].filter(Boolean).join(' · ');
  if (j.status === 'done') return ['Saved', fmtSize(j.size)].filter(Boolean).join(' · ');
  if (j.status === 'cancelled') return 'Cancelled';
  return j.error || 'Failed';
}

async function poll() {
  let jobs = [];
  try { jobs = await api('jobs'); } catch (e) { /* app closing */ }
  state.jobCount = jobs.length;
  $('jobsCard').hidden = !jobs.length || !TABS[kind()];
  const busy = jobs.some(j => ['queued', 'running', 'finishing'].includes(j.status));
  $('jobs').replaceChildren(...jobs.map(j => {
    const live = ['queued', 'running', 'finishing'].includes(j.status);
    const action = live ? h('button', { class: 'mini', type: 'button', onclick: () => api('cancel', { id: j.id }).then(pollSoon) }, 'Cancel')
      : j.status === 'done' ? h('button', { class: 'mini go', type: 'button', onclick: () => openFromJob(j) }, j.kind === 'images' ? 'View' : 'Play') : null;
    return h('div', { class: 'job ' + j.status }, h('div', { class: 'top' }, h('div', { class: 't' }, j.title), action),
      h('div', { class: 'track' }, h('i', { style: `width:${j.status === 'done' ? 100 : j.progress}%` })), h('div', { class: 's' }, jobLine(j)));
  }));
  let fresh = false;
  jobs.forEach(j => { if (j.status === 'done' && !state.seenDone.has(j.id)) { state.seenDone.add(j.id); fresh = true; } });
  if (fresh && state.tab === 'library') loadLibrary();
  else if (fresh && !state.firstPoll) $('badge').hidden = false;
  state.firstPoll = false;
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, busy || pollFast-- > 0 ? 700 : 4000);
}
$('clear').addEventListener('click', () => api('clear', {}).then(pollSoon));

async function openFromJob(j) {
  await loadLibrary(true);
  let list = state.lib.filter(i => i.rel === j.file || i.rel.startsWith(j.file + '/'));
  if (!list.length) return toast('The file is no longer in the library');
  openViewer(list, 0);
}

/* ------------------------------------------------------------ library + player */
const KINDS = [['all', 'All'], ['video', 'Videos'], ['audio', 'Audio'], ['image', 'Images']];

async function loadLibrary(quiet) {
  try { state.lib = await api('library'); } catch (e) { return; }
  if (quiet) return;
  $('libFilter').replaceChildren(...KINDS.map(([k, label]) => {
    const n = k === 'all' ? state.lib.length : state.lib.filter(i => i.kind === k).length;
    return h('button', { class: 'chip' + (state.libFilter === k ? ' on' : ''), type: 'button', onclick: () => { state.libFilter = k; loadLibrary(); } }, `${label} ${n}`);
  }));
  const list = state.lib.filter(i => state.libFilter === 'all' || i.kind === state.libFilter);
  $('libEmpty').hidden = !!list.length;
  $('libGrid').replaceChildren(...list.map((item, idx) => {
    let body;
    if (item.kind === 'image') body = [h('img', { src: mediaUrl(item.rel), loading: 'lazy', alt: '' })];
    else if (item.kind === 'video') body = [item.thumb ? h('img', { src: 'libthumb/' + item.rel.split('/').map(encodeURIComponent).join('/'), loading: 'lazy', alt: '' }) : null, h('span', { class: 'play' })];
    else body = [h('span', { class: 'note' }, '♪')];
    return h('button', { class: 'tile', type: 'button', title: item.name, onclick: () => openViewer(list, idx) }, body, h('span', { class: 'tag' }, item.name));
  }));
}

function openViewer(list, at) { state.view = list; state.viewAt = at; $('viewer').hidden = false; showItem(); }

function showItem() {
  const item = state.view[state.viewAt], src = mediaUrl(item.rel);
  let el;
  if (item.kind === 'video') el = h('video', { src, controls: true, autoplay: true, playsinline: true });
  else if (item.kind === 'audio') el = h('audio', { src, controls: true, autoplay: true });
  else el = h('img', { src, alt: item.name });
  el.addEventListener('error', () => { if (item.kind !== 'image') toast('This file cannot be played here. Use "Open in another app".'); });
  $('vStage').replaceChildren(el);
  $('vTitle').textContent = item.name;
  $('vPrev').hidden = state.viewAt === 0;
  $('vNext').hidden = state.viewAt >= state.view.length - 1;
}

function closeViewer() { $('vStage').replaceChildren(); $('viewer').hidden = true; }
function step(d) { const n = state.viewAt + d; if (n >= 0 && n < state.view.length) { state.viewAt = n; showItem(); } }
$('vClose').addEventListener('click', closeViewer);
$('vPrev').addEventListener('click', () => step(-1));
$('vNext').addEventListener('click', () => step(1));
document.addEventListener('keydown', e => {
  if ($('viewer').hidden) return;
  if (e.key === 'Escape') closeViewer(); else if (e.key === 'ArrowLeft') step(-1); else if (e.key === 'ArrowRight') step(1);
});
let touchX = null;
$('vStage').addEventListener('touchstart', e => { touchX = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
$('vStage').addEventListener('touchend', e => {
  if (touchX == null) return;
  const dx = e.changedTouches[0].clientX - touchX; touchX = null;
  if (Math.abs(dx) > 70 && state.view[state.viewAt].kind === 'image') step(dx < 0 ? 1 : -1);
}, { passive: true });
// Android back button: close the player first
window.grabitBack = () => { if (!$('viewer').hidden) { closeViewer(); return true; } return false; };

const current = () => state.view[state.viewAt];
$('vOpen').addEventListener('click', () => api('open', { rel: current().rel }).catch(e => toast(e.message)));
$('vShare').addEventListener('click', () => api('share', { rel: current().rel }).catch(e => toast(e.message)));
$('vReveal').addEventListener('click', () => api('reveal', { rel: current().rel }).catch(e => toast(e.message)));
$('vDelete').addEventListener('click', async () => {
  const item = current();
  if (!await ask(`Delete "${item.name}" from this device?`)) return;
  try { await api('delete', { rel: item.rel }); } catch (e) { return toast(e.message); }
  state.view.splice(state.viewAt, 1);
  if (!state.view.length) closeViewer(); else { state.viewAt = Math.min(state.viewAt, state.view.length - 1); showItem(); }
  if (state.tab === 'library') loadLibrary();
});

/* ------------------------------------------------------------ account + proxy */
function showChip(s) {
  const bits = [state.account, s.proxy_mode === 'custom' ? 'Proxy on' : ''].filter(Boolean);
  $('chip').textContent = bits.join(' · '); $('chip').hidden = !bits.length;
}

async function loadSettings() {
  const s = await api('settings');
  state.account = s.accounts.includes(s.account) ? s.account : '';
  $('account').replaceChildren(h('option', { value: '' }, 'No account'), ...s.accounts.map(a => h('option', { value: a }, a)));
  $('account').value = state.account;
  $('accDel').hidden = !state.account;
  showChip(s);
  $('proxyMode').value = s.proxy_mode === 'custom' ? 'custom' : 'off';
  $('proxyUrl').value = s.proxy_url || '';
  return s;
}
$('account').addEventListener('change', async () => {
  state.account = $('account').value; $('accDel').hidden = !state.account;
  showChip(await api('settings', { account: state.account }));
});
$('accAdd').addEventListener('click', () => { $('accForm').hidden = !$('accForm').hidden; });
$('accCancel').addEventListener('click', () => { $('accForm').hidden = true; });
$('accSave').addEventListener('click', async () => {
  try {
    const name = $('accName').value.trim();
    const r = await api('account_add', { name, cookies: $('accCookies').value });
    await api('settings', { account: name });
    $('accForm').hidden = true; $('accCookies').value = ''; $('accName').value = '';
    await loadSettings(); toast(`Account saved (${r.cookies} cookies)`);
  } catch (e) { toast(e.message); }
});
$('accDel').addEventListener('click', async () => {
  if (!await ask(`Remove the account "${state.account}"?`, 'Remove')) return;
  await api('account_delete', { name: state.account }); await loadSettings();
});
$('siteGo').addEventListener('click', () => api('account_login', { site: $('site').value, name: $('site').value }).catch(e => toast(e.message)));
// the Android sign-in screen reports back here
window.grabitAccountSaved = async name => { await api('settings', { account: name }); $('accForm').hidden = true; await loadSettings(); toast('Signed in. Account saved.'); };
$('proxySave').addEventListener('click', async () => {
  const mode = $('proxyMode').value, url = $('proxyUrl').value.trim();
  if (mode === 'custom' && !/^(https?|socks[45]h?):\/\/[^\s/]+/.test(url)) return toast('Enter an address like socks5://127.0.0.1:1080');
  showChip(await api('settings', { proxy_mode: mode, proxy_url: url })); toast(mode === 'custom' ? 'Proxy saved and turned on' : 'Proxy turned off');
});

/* ------------------------------------------------------------ status */
async function loadStatus() {
  const s = state.status = await api('status');
  if (s.insets) setInsets(s.insets[0], s.insets[1]);
  $('ver').textContent = `${s.app} · engine ${s.engine.active || '?'}`;
  $('folder').textContent = s.folder;
  const android = s.platform === 'android', ios = s.platform === 'ios';
  $('vShare').hidden = !(android || ios); $('vReveal').hidden = android || ios; $('vOpen').hidden = ios;
  if (ios) { $('vShare').textContent = 'Save or share'; $('paste').hidden = false; $('folder').textContent = 'Files app › On My iPhone › Grabit'; }
  $('signin').hidden = !s.sites.length;
  $('site').replaceChildren(...s.sites.map(x => h('option', { value: x }, x)));
  if (s.engine.pending) offerRestart(s.engine.pending);
}
function offerRestart(v) {
  $('update').textContent = `Engine ${v} downloaded — restart to use it`;
  $('update').onclick = () => state.status.platform === 'android' ? api('restart', {}) : toast('Close Grabit completely and open it again.');
}
$('update').onclick = async () => {
  $('update').textContent = 'Checking...';
  try {
    const e = await api('update_engine', {});
    if (e.pending) offerRestart(e.pending);
    else $('update').textContent = e.error ? 'Could not check (offline?)' : 'Everything is up to date';
  } catch (err) { $('update').textContent = 'Could not check'; }
};

setTab('video');
loadSettings().catch(() => {});
loadStatus().catch(() => {});
poll();
setTimeout(() => loadStatus().catch(() => {}), 20000);   // pick up a background engine update
