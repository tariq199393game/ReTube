"""Facebook fallback extractor.

Used when yt-dlp cannot handle a Facebook link. Facebook embeds the direct video
addresses in the page as JSON; several layouts exist, so we look for all of them
and try a few different ways of asking for the page.
"""
import html
import json
import re
from urllib.parse import quote, urlparse

HOSTS = ('facebook.com', 'fb.watch', 'fb.com', 'fb.gg')

# (regex over the raw page, label, nominal height)
_URL_KEYS = [
    ('browser_native_hd_url', 'HD', 720),
    ('playable_url_quality_hd', 'HD', 720),
    ('hd_src_no_ratelimit', 'HD', 720),
    ('hd_src', 'HD', 720),
    ('browser_native_sd_url', 'SD', 360),
    ('playable_url', 'SD', 360),
    ('sd_src_no_ratelimit', 'SD', 360),
    ('sd_src', 'SD', 360),
]


def is_facebook(url):
    host = (urlparse(url).hostname or '').lower()
    return any(host == h or host.endswith('.' + h) for h in HOSTS)


def _unescape(s):
    """Turn a JSON-escaped string body (\\/ , \\u0025 ...) into a normal string."""
    try:
        s = json.loads('"' + s + '"')
    except ValueError:
        s = s.replace('\\/', '/').replace('\\u0025', '%').replace('\\u0026', '&')
    return html.unescape(s)


def _meta(page, prop):
    m = (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(prop), page)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(prop), page))
    return html.unescape(m.group(1)) if m else None


def parse(page):
    """Pull video addresses out of a Facebook page. Returns a list of format dicts."""
    found, seen = [], set()

    def add(url, label, height):
        if not url or not url.startswith('http') or url in seen:
            return
        seen.add(url)
        found.append({'url': url, 'label': label, 'height': height})

    # newest layout: "progressive_urls":[{"progressive_url":"...","failure_reason":null,"metadata":{"quality":"HD"}}]
    for m in re.finditer(r'"progressive_url"\s*:\s*"((?:[^"\\]|\\.)+)"(?:(?!"progressive_url").){0,200}?"quality"\s*:\s*"(\w+)"',
                         page, re.S):
        q = m.group(2).upper()
        add(_unescape(m.group(1)), q, 720 if q == 'HD' else 360)
    # Threads / Instagram layout: "video_versions":[{"type":101,"url":"..."},...]; the first list is the post itself
    m = re.search(r'"video_versions"\s*:\s*\[(.*?)\]', page, re.S)
    if m:
        for n, u in enumerate(re.findall(r'"url"\s*:\s*"((?:[^"\\]|\\.)+)"', m.group(1))):
            add(_unescape(u), 'HD' if n == 0 else 'SD', 720 if n == 0 else 360)
    # embeddable player pages carry a plain <video>/<source> tag
    for m in re.finditer(r'<(?:video|source)\b[^>]*?\ssrc=["\']([^"\']+)["\']', page):
        u = html.unescape(m.group(1))
        if re.search(r'\.mp4(\?|$)', u) or 'video' in u.split('?')[0]:
            add(u, 'HD' if not found else 'SD', 720 if not found else 360)
    for key, label, height in _URL_KEYS:
        for m in re.finditer(r'(?:"%s"|\b%s)\s*:\s*"((?:[^"\\]|\\.)+)"' % (key, key), page):
            add(_unescape(m.group(1)), label, height)
    for prop in ('og:video:secure_url', 'og:video:url', 'og:video'):
        add(_meta(page, prop), 'SD', 360)
    # real pixel sizes when the page states them next to the address
    for f in found:
        m = re.search(re.escape(json.dumps(f['url'])[1:-1].replace('/', '\\/'))
                      + r'.{0,400}?"(?:original_)?height"\s*:\s*(\d{3,4})', page, re.S)
        if m:
            f['height'] = int(m.group(1))
    return found


def _title(page):
    for pat in (r'"story"\s*:\s*\{[^{}]*?"message"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.){3,300})"',
                r'"title"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.){3,300})"'):
        m = re.search(pat, page)
        if m:
            return _unescape(m.group(1)).strip().split('\n')[0][:120]
    t = _meta(page, 'og:title') or _meta(page, 'twitter:title')
    if not t:
        m = re.search(r'<title[^>]*>([^<]+)</title>', page)
        t = html.unescape(m.group(1)) if m else None
    t = re.sub(r'\s*\|\s*Facebook\s*$', '', (t or '').strip())
    return t if t and t.lower() not in ('facebook', 'log in or sign up to view', 'watch') else 'Facebook video'


def _thumb(page):
    m = re.search(r'"preferred_thumbnail"\s*:\s*\{"image"\s*:\s*\{"uri"\s*:\s*"((?:[^"\\]|\\.)+)"', page)
    return _unescape(m.group(1)) if m else _meta(page, 'og:image')


def _video_id(url, page=''):
    for pat in (r'/(?:videos|reel|reels|watch)/(?:[^/?#]+/)?(\d{6,})', r'[?&]v=(\d{6,})', r'story_fbid=(\d{6,})',
                r'/(\d{8,})/?(?:[?#]|$)'):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    m = re.search(r'"video_id"\s*:\s*"(\d{6,})"', page) or re.search(r'"videoId"\s*:\s*"(\d{6,})"', page)
    return m.group(1) if m else re.sub(r'\W+', '', urlparse(url).path)[-20:] or 'video'


def extract(url, fetch):
    """fetch(url, headers) -> Page. Returns a yt-dlp style info dict, or None."""
    url = re.sub(r'^(https?://)(?:m|mbasic|web|touch|l)\.facebook\.com', r'\1www.facebook.com', url.strip())
    attempts = [
        (url, {}),
        # crawler view: Facebook serves public posts to link-preview bots without a login wall
        (url, {'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
               'Sec-Fetch-Site': None}),
        # the embeddable player page works for public videos even when the post page wants a login
        ('https://www.facebook.com/plugins/video.php?show_text=false&href=' + quote(url, safe=''),
         {'Referer': 'https://www.facebook.com/', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Site': 'cross-site'}),
    ]
    best, final = None, url
    for target, headers in attempts:
        try:
            page = fetch(target, {k: v for k, v in headers.items() if v is not None})
        except Exception:
            continue
        text = page.text
        formats = parse(text)
        if 'plugins/video.php' not in target:
            final = page.url
            # share / fb.watch links redirect; retry the embed with the real address
            if final != url and not any(quote(final, safe='') in a[0] for a in attempts):
                attempts.append(('https://www.facebook.com/plugins/video.php?show_text=false&href='
                                 + quote(final, safe=''), attempts[2][1]))
        if formats and (not best or len(formats) > len(best[0])):
            best = (formats, text)
            if any(f['height'] >= 720 for f in formats):
                break
    if not best:
        return None
    formats, text = best
    formats.sort(key=lambda f: f['height'])
    out, used = [], set()
    for f in formats:
        fid = f['label'].lower()
        while fid in used:
            fid += 'x'
        used.add(fid)
        out.append({'format_id': fid, 'url': f['url'], 'ext': 'mp4', 'height': f['height'],
                    'vcodec': 'avc1', 'acodec': 'mp4a', 'protocol': 'https', 'format_note': f['label'],
                    'http_headers': {'Referer': 'https://www.facebook.com/'}})
    return {'id': _video_id(final, text), 'title': _title(text), 'thumbnail': _thumb(text), 'formats': out,
            'webpage_url': final, 'original_url': url, 'extractor': 'grabit:facebook',
            'extractor_key': 'GrabitFacebook', '_type': 'video'}


# ---------------------------------------------------------------- Threads / Instagram (same company, same page format)

SOCIAL_HOSTS = ('threads.com', 'threads.net', 'instagram.com')


def is_social(url):
    host = (urlparse(url).hostname or '').lower()
    return any(host == h or host.endswith('.' + h) for h in SOCIAL_HOSTS)


def extract_social(url, fetch):
    """Threads and Instagram posts. Returns a yt-dlp style info dict, or None."""
    clean = url.strip().split('?')[0].split('#')[0].rstrip('/')
    host = (urlparse(clean).hostname or '').lower()
    site = 'Instagram' if 'instagram' in host else 'Threads'
    m = re.search(r'/(?:post|p|reel|reels|tv)/([\w-]+)', clean)
    post_id = m.group(1) if m else re.sub(r'\W+', '', urlparse(clean).path)[-20:] or 'post'
    embed = clean + ('/embed/captioned' if site == 'Instagram' else '/embed')
    crawler = {'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)'}
    attempts = [(clean + '/', {}), (embed, {'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Site': 'cross-site'}), (clean + '/', crawler)]
    if 'threads.com' in host:   # the older address still serves the same posts
        attempts.append((clean.replace('threads.com', 'threads.net') + '/', {}))
    best = None
    for target, headers in attempts:
        try:
            text = fetch(target, headers).text
        except Exception:
            continue
        formats = parse(text)
        if formats and (not best or len(formats) > len(best[0])):
            best = (formats, text)
            if len(formats) > 1:
                break
    if not best:
        return None
    formats, text = best
    formats.sort(key=lambda f: f['height'])
    out = [{'format_id': f'v{i}', 'url': f['url'], 'ext': 'mp4', 'height': f['height'], 'vcodec': 'avc1', 'acodec': 'mp4a',
            'protocol': 'https', 'format_note': f['label'], 'http_headers': {'Referer': f'https://{host}/'}}
           for i, f in enumerate(formats)]
    title = _meta(text, 'og:title') or _meta(text, 'og:description') or ''
    title = re.sub(r'\s+', ' ', title).strip()[:120] or f'{site} video'
    return {'id': post_id, 'title': title, 'thumbnail': _meta(text, 'og:image'), 'formats': out, 'webpage_url': clean,
            'original_url': url, 'extractor': 'grabit:' + site.lower(), 'extractor_key': 'Grabit' + site, '_type': 'video'}
