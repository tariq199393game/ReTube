(function () {
  /* Runs inside the rendered page: lists every image the page is actually showing. */
  var out = [], seen = {};
  function add(u, w, h, alt) {
    if (!u || typeof u !== 'string' || /^(data|blob|about|javascript):/i.test(u)) return;
    try { u = new URL(u, location.href).href; } catch (e) { return; }
    if (seen[u]) return;
    seen[u] = 1;
    out.push({ url: u, w: w || 0, h: h || 0, alt: (alt || '').slice(0, 120) });
  }
  function best(srcset) {
    var top = null, score = -1;
    (srcset || '').split(/,\s+|,(?=https?:|\/)/).forEach(function (part) {
      var bits = part.trim().split(/\s+/), s = 1, m = /([\d.]+)([wx])/.exec(bits[1] || '');
      if (m) s = parseFloat(m[1]) * (m[2] === 'x' ? 1000 : 1);
      if (bits[0] && s > score) { top = bits[0]; score = s; }
    });
    return top;
  }
  function walk(root) {
    var imgs = root.querySelectorAll('img');
    for (var i = 0; i < imgs.length; i++) {
      var im = imgs[i], alt = im.alt || im.title || '';
      add(best(im.getAttribute('srcset') || im.getAttribute('data-srcset')), 0, 0, alt);
      ['data-full', 'data-original', 'data-zoom-image', 'data-large', 'data-src', 'data-lazy-src'].forEach(function (k) { add(im.getAttribute(k), 0, 0, alt); });
      add(im.currentSrc || im.src, im.naturalWidth, im.naturalHeight, alt);
    }
    var srcs = root.querySelectorAll('picture source[srcset], video[poster], a[href], meta[property="og:image"], meta[name="twitter:image"], image');
    for (var j = 0; j < srcs.length; j++) {
      var el = srcs[j], tag = el.tagName.toLowerCase();
      if (tag === 'source') add(best(el.getAttribute('srcset')));
      else if (tag === 'video') add(el.getAttribute('poster'));
      else if (tag === 'meta') add(el.getAttribute('content'));
      else if (tag === 'image') add(el.getAttribute('href') || el.getAttribute('xlink:href'));
      else if (/\.(jpe?g|png|webp|gif|avif|bmp|svg)(\?|#|$)/i.test(el.getAttribute('href') || '')) add(el.href);
    }
    var all = root.querySelectorAll('*');
    for (var k = 0; k < all.length && k < 6000; k++) {
      var node = all[k];
      if (node.shadowRoot) walk(node.shadowRoot);
      var bg = getComputedStyle(node).backgroundImage;
      if (bg && bg !== 'none') {
        var re = /url\(\s*(["']?)(.*?)\1\s*\)/g, m2;
        while ((m2 = re.exec(bg))) add(m2[2], 0, 0, '');
      }
    }
  }
  var videos = [], vseen = {};
  function addVideo(u, el) {
    if (!u || /^(blob|data|about):/i.test(u)) return;
    try { u = new URL(u, location.href).href; } catch (e) { return; }
    if (vseen[u]) return;
    vseen[u] = 1;
    videos.push({ url: u, w: el.videoWidth || 0, h: el.videoHeight || 0, poster: el.poster || '', duration: isFinite(el.duration) ? el.duration : 0 });
  }
  try {
    var vs = document.querySelectorAll('video');
    for (var v = 0; v < vs.length; v++) {
      addVideo(vs[v].currentSrc || vs[v].src || vs[v].getAttribute('data-src'), vs[v]);
      var ss = vs[v].querySelectorAll('source');
      for (var q = 0; q < ss.length; q++) addVideo(ss[q].src, vs[v]);
    }
  } catch (e) { /* none */ }
  try { walk(document); } catch (e) { /* partial result is fine */ }
  return JSON.stringify({ title: document.title || '', url: location.href, images: out.slice(0, 800), videos: videos.slice(0, 20) });
})()
