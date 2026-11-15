"""Find media inside an ordinary web page - the way a download manager sniffs it.

Works on the page source: meta tags, <video>/<source>/<img> tags, JSON blobs,
escaped URLs inside scripts, CSS backgrounds and embedded player frames.
"""
import html
import json
import re
from urllib.parse import urljoin, urlparse, unquote

VIDEO_EXT = ('mp4', 'm4v', 'webm', 'mov', 'mkv', 'flv', 'm3u8', 'mpd')
IMAGE_EXT = ('jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'svg', 'bmp', 'ico', 'tif', 'tiff', 'heic')
IMAGE_MIME = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif',
              'image/avif': 'avif', 'image/svg+xml': 'svg', 'image/bmp': 'bmp', 'image/x-icon': 'ico',
              'image/vnd.microsoft.icon': 'ico', 'image/tiff': 'tif', 'image/heic': 'heic'}

_URL_CHARS = r'[^\s"\'<>\\^`{|}]'


def ext_of(url):
    path = urlparse(url).path.lower()
    m = re.search(r'\.([a-z0-9]{2,5})$', path)
    return m.group(1) if m else ''


def image_type(url):
    e = ext_of(url)
    if e in IMAGE_EXT:
        return {'jpeg': 'jpg', 'tiff': 'tif'}.get(e, e)
    m = re.search(r'[?&](?:format|fm|ext|type)=(jpe?g|png|webp|gif|avif)\b', url, re.I)
    return m.group(1).lower().replace('jpeg', 'jpg') if m else ''


def _loosen(text):
    """Undo the escaping used inside JSON / JS strings so URLs become visible."""
    return (text.replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')
            .replace('\\u0026', '&').replace('\\u003D', '=').replace('\\u003d', '=').replace('&amp;', '&'))


def _attrs(tag):
    return {m.group(1).lower(): html.unescape(m.group(3) if m.group(3) is not None else m.group(4) or '')
            for m in re.finditer(r'([\w:-]+)\s*=\s*(?:(["\'])(.*?)\2|([^\s>]+))', tag, re.S)}


def _title(text):
    for pat in (r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
                r'<title[^>]*>([^<]+)</title>'):
        m = re.search(pat, text, re.I)
        if m and m.group(1).strip():
            return re.sub(r'\s+', ' ', html.unescape(m.group(1))).strip()[:150]
    return ''


def _metas(text, names):
    out = []
    for m in re.finditer(r'<meta\b[^>]*>', text, re.I):
        a = _attrs(m.group(0))
        key = (a.get('property') or a.get('name') or a.get('itemprop') or '').lower()
        if key in names and a.get('content'):
            out.append(a['content'])
    return out


def _abs(base, u):
    u = (u or '').strip()
    if not u or u.startswith(('data:', 'javascript:', 'blob:', 'about:', '#')):
        return None
    full = urljoin(base, u)
    return full if full.startswith(('http://', 'https://')) else None


# ---------------------------------------------------------------- videos

def video_candidates(text, base):
    """Returns (direct media URLs, embedded player page URLs), best guesses first."""
    direct, frames = [], []

    def add(u, where=direct):
        u = _abs(base, u)
        if u and u not in where:
            where.append(u)

    for u in _metas(text, ('og:video:secure_url', 'og:video:url', 'og:video', 'twitter:player:stream')):
        (add(u) if ext_of(u) in VIDEO_EXT else add(u, frames))
    for m in re.finditer(r'<(?:video|source)\b[^>]*>', text, re.I):
        a = _attrs(m.group(0))
        if m.group(0).lower().startswith('<source') and a.get('type', '').startswith(('image/', 'audio/')):
            continue
        for k in ('src', 'data-src', 'data-video-src', 'data-hls', 'data-mp4'):
            if a.get(k) and (ext_of(a[k]) in VIDEO_EXT or a.get('type', '').startswith(('video/', 'application/'))
                             or m.group(0).lower().startswith('<video')):
                add(a[k])
    loose = _loosen(text)
    for m in re.finditer(r'"(?:contentUrl|embedUrl|video_url|videoUrl|file|src|hls|hlsUrl|mp4|stream_url|playbackUrl)"'
                         r'\s*:\s*"(https?://%s+)"' % _URL_CHARS, loose):
        u = m.group(1)
        if ext_of(u) in VIDEO_EXT:
            add(u)
        elif 'embedUrl' in m.group(0):
            add(u, frames)
    for m in re.finditer(r'https?://%s+?\.(?:%s)(?:\?%s*)?(?=["\'\s<>\\]|$)' % (_URL_CHARS, '|'.join(VIDEO_EXT), _URL_CHARS),
                         loose, re.I):
        add(m.group(0))
    for m in re.finditer(r'<(?:iframe|embed)\b[^>]*>', text, re.I):
        a = _attrs(m.group(0))
        u = a.get('src') or a.get('data-src')
        if u and not re.search(r'(googletagmanager|doubleclick|google\.com/recaptcha|facebook\.com/plugins/like|/ads?/)', u):
            add(u, frames)
    # adaptive manifests first, they carry every quality
    direct.sort(key=lambda u: 0 if ext_of(u) in ('m3u8', 'mpd') else 1)
    return direct[:12], frames[:6]


# ---------------------------------------------------------------- images

def _srcset_best(value):
    best, score = None, -1
    for part in re.split(r',\s+(?=\S)|,(?=https?:|/)', value or ''):
        bits = part.strip().split()
        if not bits:
            continue
        s = 1.0
        if len(bits) > 1:
            m = re.match(r'([\d.]+)([wx])', bits[-1])
            if m:
                s = float(m.group(1)) * (1000 if m.group(2) == 'x' else 1)
        if s > score:
            best, score = bits[0], s
    return best


def image_candidates(text, base):
    """Every image address mentioned by the page, in page order, de-duplicated."""
    seen, out = set(), []

    def add(u, alt='', w=0, h=0, sure=False):
        u = _abs(base, u)
        if not u:
            return
        key = u.split('#')[0]
        if key in seen:
            return
        t = image_type(u)
        if not t and not sure:
            return
        seen.add(key)
        out.append({'url': key, 'type': t, 'alt': alt[:120], 'w': w, 'h': h})

    def num(v):
        m = re.match(r'\d+', v or '')
        return int(m.group(0)) if m else 0

    for u in _metas(text, ('og:image', 'og:image:url', 'og:image:secure_url', 'twitter:image', 'twitter:image:src',
                           'image', 'thumbnailurl')):
        add(u, sure=True)
    for m in re.finditer(r'<(img|source|a|link|video|input)\b[^>]*>', text, re.I):
        tag, a = m.group(1).lower(), _attrs(m.group(0))
        if tag == 'img' or (tag == 'input' and a.get('type') == 'image'):
            alt, w, h = a.get('alt') or a.get('title') or '', num(a.get('width')), num(a.get('height'))
            big = _srcset_best(a.get('srcset') or a.get('data-srcset') or a.get('data-lazy-srcset'))
            if big:
                add(big, alt, sure=True)
            for k in ('data-full', 'data-original', 'data-zoom-image', 'data-large', 'data-src', 'data-lazy-src',
                      'data-lazy', 'data-url', 'src'):
                if a.get(k):
                    add(a[k], alt, w, h, sure=True)
        elif tag == 'source':
            if not a.get('type', '').startswith(('video/', 'audio/')) and (a.get('srcset') or a.get('data-srcset')):
                add(_srcset_best(a.get('srcset') or a.get('data-srcset')), sure=a.get('type', '').startswith('image/'))
        elif tag == 'a':
            add(a.get('href'), a.get('title') or '')
        elif tag == 'link':
            if re.search(r'icon|image_src|apple-touch', a.get('rel', ''), re.I) or a.get('as') == 'image':
                add(a.get('href'), sure=True)
        elif tag == 'video':
            add(a.get('poster'), sure=True)
    for m in re.finditer(r'url\(\s*(["\']?)([^)"\']+)\1\s*\)', text):
        add(html.unescape(m.group(2)))
    loose = _loosen(text)
    for m in re.finditer(r'(?:https?:)?//%s+?\.(?:%s)(?:\?%s*)?(?=["\'\s<>\\)]|$)' % (_URL_CHARS, '|'.join(IMAGE_EXT), _URL_CHARS),
                         loose, re.I):
        add(m.group(0))
    # image addresses kept in page data under well-known names, with or without a file extension
    for m in re.finditer(r'"(?:display_url|thumbnail_src|image_url|imageUrl|image_src|thumbnailUrl|thumbnail_url|'
                         r'original_url|full_url|large_url|media_url_https|poster)"\s*:\s*"(https?://%s+)"' % _URL_CHARS, loose):
        add(m.group(1), sure=True)
    return out[:600]


def merge_rendered(result, rendered, base):
    """Put what the real browser view saw in front of what the page source listed."""
    dom = rendered.get('dom') or {}
    seen, merged = set(), []

    def add(u, alt='', w=0, h=0, sure=True):
        u = _abs(dom.get('url') or base, u)
        if not u:
            return
        key = u.split('#')[0]
        t = image_type(key)
        if key in seen or (not t and not sure):
            return
        seen.add(key)
        merged.append({'url': key, 'type': t, 'alt': (alt or '')[:120], 'w': int(w or 0), 'h': int(h or 0)})

    for i in dom.get('images') or []:
        if isinstance(i, dict):
            add(i.get('url'), i.get('alt'), i.get('w'), i.get('h'))
    for u in rendered.get('net') or []:
        add(u)
    for i in result.get('images') or []:
        add(i['url'], i.get('alt'), i.get('w'), i.get('h'), sure=True)
    result['images'] = merged[:800]
    if dom.get('title') and (not result.get('title') or result['title'] == urlparse(base).hostname):
        result['title'] = re.sub(r'\s+', ' ', dom['title']).strip()[:150]
    return result


def find_images(url, fetch):
    """fetch(url, headers) -> Page. Returns {'title', 'page', 'images': [...]}."""
    page = fetch(url, {})
    if page.ctype.startswith('image/'):
        name = unquote(urlparse(page.url).path.rsplit('/', 1)[-1]) or 'image'
        return {'title': name.rsplit('.', 1)[0], 'page': page.url,
                'images': [{'url': page.url, 'type': IMAGE_MIME.get(page.ctype, image_type(page.url)), 'alt': '', 'w': 0, 'h': 0}]}
    text = page.text
    return {'title': _title(text) or urlparse(page.url).hostname or 'Images', 'page': page.url,
            'images': image_candidates(text, page.url)}


def jsonld_names(text):
    """Video title from JSON-LD, if the page has one."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', text, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and 'VideoObject' in str(item.get('@type')) and item.get('name'):
                return str(item['name'])
    return ''
