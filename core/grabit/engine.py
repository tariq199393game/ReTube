"""Resolve a link to a video, choose formats, download it."""
import copy
import hashlib
import os
import re
import shutil
import threading
import time

from yt_dlp.utils import DownloadCancelled

from . import config, facebook, host, net, sniff

HEIGHTS = (4320, 2160, 1440, 1080, 720, 480, 360, 240, 144)
_cache, _cache_lock = {}, threading.Lock()


class GrabError(Exception):
    pass


def friendly(err):
    """Turn an engine error into one plain sentence."""
    msg = re.sub(r'\x1b\[[0-9;]*m', '', str(err))
    msg = re.sub(r'^(ERROR:\s*)?(\[[^\]]+\]\s*)?([\w-]+:\s)?', '', msg).strip()
    low = msg.lower()
    if 'sign in to confirm' in low or 'not a bot' in low:
        return 'The site wants proof you are not a bot. Add an account (sign in) under Account and try again.'
    if any(k in low for k in ('login required', 'log in', 'sign in', 'cookies', 'registered users', 'private',
                              'members only', 'authentication')):
        return 'This video needs you to be signed in. Add an account under Account, select it and try again.'
    if 'unsupported url' in low or 'no video' in low or 'no media' in low:
        return 'No video was found at this link.'
    if 'geo' in low or 'not available in your country' in low or 'your location' in low:
        return 'This video is blocked in your region. Turn on a VPN or set a proxy and try again.'
    if 'drm' in low:
        return 'This video is DRM-protected and cannot be downloaded.'
    if any(k in low for k in ('timed out', 'getaddrinfo', 'name or service', 'connection', 'network is unreachable',
                              'tunnel', 'proxy')):
        return 'Could not reach the site. Check your connection or proxy setting.'
    if 'http error 404' in low:
        return 'That page does not exist (error 404). Check the link.'
    if 'http error 403' in low or 'http error 429' in low:
        return 'The site refused the request. Try again later, or with an account or a proxy.'
    if 'is not a valid url' in low:
        return 'That does not look like a link.'
    return msg.split('\n')[0][:220] or 'Something went wrong.'


# ---------------------------------------------------------------- resolve

def _extract(url, account, **opts):
    with net.ydl(account, **opts) as y:
        return y.sanitize_info(y.extract_info(url, download=False))


def _first_video(info):
    """A playlist-shaped answer in single-video mode: use its first playable entry."""
    if not info:
        return None
    if info.get('_type') == 'playlist':
        ents = [e for e in info.get('entries') or [] if e and e.get('_type', 'video') == 'video']
        files = [(e.get('formats') or [e])[0] for e in ents if len(e.get('formats') or [e]) == 1]
        if len(ents) > 1 and len(files) == len(ents) and all(
                e.get('extractor_key') == 'Generic' for e in ents) and all(f.get('url') for f in files):
            # a plain page offering one clip as several files: treat them as quality choices
            heights = [f.get('height') or _guess_height(f['url']) for f in files]
            if len(set(heights)) == len(heights) and all(heights):
                merged = dict(ents[heights.index(max(heights))])
                merged['title'] = info.get('title') or merged.get('title')
                merged['formats'] = [dict(f, format_id=f'file{i}', height=h) for i, (h, f) in
                                     enumerate(sorted(zip(heights, files), key=lambda x: x[0]))]
                merged.pop('url', None)
                return merged
        for e in info.get('entries') or []:
            v = _first_video(e)
            if v:
                return v
        return None
    return info if info.get('formats') or info.get('url') else None


def _real_video(info):
    """Drop answers that are really just a picture (a post's preview image, for example)."""
    if not info:
        return None
    fmts = info.get('formats') or ([info] if info.get('url') else [])
    keep = [f for f in fmts if sniff.ext_of(f.get('url') or '') not in sniff.IMAGE_EXT and f.get('ext') not in sniff.IMAGE_EXT]
    if not keep:
        return None
    if info.get('formats'):
        info['formats'] = keep
    return info


def _guess_height(url):
    m = re.search(r'(?<!\d)(2160|1440|1080|720|540|480|360|240)p?(?!\d)', url)
    return int(m.group(1)) if m else 0


def _sniff(url, account):
    page = net.fetch(url, account=account)
    if page.ctype.startswith('video/'):
        direct, frames, text = [page.url], [], ''
    else:
        text = page.text
        direct, frames = sniff.video_candidates(text, page.url)
    title = (sniff.jsonld_names(text) or sniff._title(text) or os.path.basename(page.url.split('?')[0])
             or 'video')
    ref = {'Referer': page.url}
    for u in [d for d in direct if sniff.ext_of(d) in ('m3u8', 'mpd')] + frames:
        try:
            if facebook.is_facebook(u):
                info = facebook.extract(u, lambda t, h: net.fetch(t, h, account))
            else:
                info = _first_video(_extract(u, account, http_headers=ref))
            if info:
                if not info.get('title') or info.get('extractor_key') == 'Generic':
                    info['title'] = title
                return info
        except Exception:
            continue
    files = [d for d in direct if sniff.ext_of(d) not in ('m3u8', 'mpd')][:6]
    if not files:
        return None
    files.sort(key=_guess_height)
    return {'id': hashlib.md5(page.url.encode()).hexdigest()[:10], 'title': title, '_type': 'video',
            'webpage_url': page.url, 'extractor': 'grabit:sniff', 'extractor_key': 'GrabitSniff',
            'formats': [{'format_id': f'file{i}', 'url': u, 'ext': sniff.ext_of(u) or 'mp4', 'height': _guess_height(u) or None,
                         'protocol': 'https', 'http_headers': ref} for i, u in enumerate(files)]}


def _render_sniff(url, account):
    """Last resort on phones: open the page in the hidden browser view and take the video it plays."""
    import pkgutil
    collector = pkgutil.get_data('grabit', 'web/collect.js').decode()
    seen = host.render_page(url, collector, min_seconds=5, max_seconds=18)
    dom = seen.get('dom') or {}
    page = dom.get('url') or url
    ref = {'Referer': page}
    found, poster = [], ''
    for v in dom.get('videos') or []:
        if isinstance(v, dict) and str(v.get('url', '')).startswith('http'):
            found.append((v['url'], int(v.get('h') or 0)))
            poster = poster or v.get('poster') or ''
    for u in seen.get('media') or []:
        if u.startswith('http') and u not in [f[0] for f in found]:
            found.append((u, 0))
    title = re.sub(r'\s+', ' ', dom.get('title') or '').strip()[:120] or 'video'
    for u, _ in found:
        if sniff.ext_of(u) in ('m3u8', 'mpd'):
            try:
                info = _first_video(_extract(u, account, http_headers=ref))
                if info:
                    info['title'] = title
                    return info
            except Exception:
                continue
    # byte-range pieces of one file share a path: keep one address per file, without the range
    files, paths = [], set()
    for u, h in found:
        if sniff.ext_of(u) in ('m3u8', 'mpd'):
            continue
        base, _, query = u.partition('?')
        keep = [q for q in query.split('&') if q and q.split('=')[0] not in ('bytestart', 'byteend', 'range')]
        clean = base + ('?' + '&'.join(keep) if keep else '')
        path = clean.split('?')[0]
        if path not in paths:
            paths.add(path)
            files.append((clean, h or _guess_height(clean)))
    if not files:
        return None
    files = sorted(files[:6], key=lambda f: f[1])
    return {'id': hashlib.md5(page.encode()).hexdigest()[:10], 'title': title, '_type': 'video', 'thumbnail': poster or None,
            'webpage_url': page, 'extractor': 'grabit:browser', 'extractor_key': 'GrabitBrowser',
            'formats': [{'format_id': f'file{i}', 'url': u, 'ext': sniff.ext_of(u) or 'mp4', 'height': h or None,
                         'protocol': 'https', 'http_headers': ref} for i, (u, h) in enumerate(files)]}


def resolve(url, account=None, fresh=False):
    """Returns a yt-dlp style info dict for one video. Raises GrabError."""
    url = (url or '').strip()
    if not re.match(r'https?://', url):
        if re.match(r'[\w-]+(\.[\w-]+)+(/|$)', url):
            url = 'https://' + url
        else:
            raise GrabError('That does not look like a link.')
    key = (url, account or '')
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not fresh and time.time() - hit[0] < 1200:
            return hit[1]
    first_error, info = None, None
    threads = facebook.is_social(url) and 'threads.' in url
    if threads:   # the general engine has no Threads support and may mistake the preview picture for the video
        try:
            info = facebook.extract_social(url, lambda t, h: net.fetch(t, h, account))
        except Exception as e:
            first_error = e
    if not info:
        try:
            info = _real_video(_first_video(_extract(url, account)))
        except Exception as e:
            first_error = first_error or e
    if not info and facebook.is_facebook(url):
        try:
            info = facebook.extract(url, lambda t, h: net.fetch(t, h, account))
        except Exception as e:
            first_error = first_error or e
    if not info and facebook.is_social(url) and not threads:
        try:
            info = facebook.extract_social(url, lambda t, h: net.fetch(t, h, account))
        except Exception as e:
            first_error = first_error or e
    if not info:
        try:
            info = _sniff(url, account)
        except Exception as e:
            first_error = first_error or e
    if not info and host.can_render():
        try:
            info = _render_sniff(url, account)
        except Exception as e:
            first_error = first_error or e
    if not info:
        if facebook.is_social(url):
            raise GrabError('This post did not show a video without a login. Sign in under Settings > Account, '
                            'select the account and try again.')
        if facebook.is_facebook(url) and (not first_error or 'unsupported' in str(first_error).lower()):
            raise GrabError('Facebook did not show this video without a login. Add your Facebook account '
                            'under Account, select it and try again.')
        raise GrabError(friendly(first_error) if first_error else 'No video was found at this link.')
    if not info.get('formats') and info.get('url'):
        info['formats'] = [{'format_id': '0', 'url': info['url'], 'ext': info.get('ext') or 'mp4',
                            'http_headers': info.get('http_headers') or {}}]
    with _cache_lock:
        _cache[key] = (time.time(), info)
        for k in [k for k, v in _cache.items() if time.time() - v[0] > 1800]:
            _cache.pop(k, None)
    return info


def _entry(e):
    link = e.get('webpage_url') or e.get('url') or ''
    if not link.startswith('http'):
        if e.get('ie_key') == 'Youtube' and (e.get('id') or link):
            link = 'https://www.youtube.com/watch?v=' + (e.get('id') or link)
        else:
            return None
    thumbs = e.get('thumbnails') or []
    return {'url': link, 'title': e.get('title') or link, 'duration': e.get('duration') or 0,
            'thumb': e.get('thumbnail') or (thumbs[0].get('url') if thumbs else '') or ''}


def _playlist_lazy(url, account, ctl):
    """Walk the list page by page so a long channel can be stopped part-way."""
    with net.ydl(account, noplaylist=False, extract_flat='in_playlist', lazy_playlist=True) as y:
        info = y.extract_info(url, download=False, process=False)
        for _ in range(4):   # follow redirects such as channel -> its videos tab
            if info and info.get('_type') in ('url', 'url_transparent') and info.get('url'):
                info = y.extract_info(info['url'], download=False, process=False)
        if not info or info.get('_type') != 'playlist':
            return None
        out = []
        for e in info.get('entries') or []:
            if ctl.stopped:
                break
            if not e:
                continue
            if e.get('_type') == 'playlist':   # nested lists are handled by the full pass
                return None
            item = _entry(e)
            if item:
                out.append(item)
                ctl.found = len(out)
        return {'title': info.get('title') or 'Playlist', 'entries': out} if out else None


def playlist(url, account=None, ctl=None):
    url = url.strip()
    if ctl is not None:
        try:
            res = _playlist_lazy(url, account, ctl)
            if res:
                return res
        except Exception:
            pass
        if ctl.stopped:
            raise GrabError('Search stopped.')
    try:
        info = _extract(url, account, noplaylist=False, extract_flat='in_playlist')
    except Exception as e:
        raise GrabError(friendly(e))
    entries = [info] if info.get('_type') != 'playlist' else [e for e in info.get('entries') or [] if e]
    out = [x for x in map(_entry, entries) if x]
    if not out:
        raise GrabError('No videos were found in this playlist.')
    return {'title': info.get('title') or 'Playlist', 'entries': out}


# ---------------------------------------------------------------- choosing formats

def _has_v(f):
    return f.get('vcodec') != 'none'


def _has_a(f):
    return f.get('acodec') != 'none'


def _usable(f, ffmpeg):
    if f.get('ext') == 'mhtml' or (not _has_v(f) and not _has_a(f)) or f.get('has_drm'):
        return False
    if ffmpeg:
        return True
    proto = f.get('protocol') or 'https'
    return proto in ('https', 'http', 'm3u8_native', 'http_dash_segments')


def _muxable_v(f, ffmpeg):
    """Can the host put this video stream into an MP4 together with separate audio?"""
    if ffmpeg:
        return True
    vc = (f.get('vcodec') or '').lower()
    return not vc.startswith(('vp', 'av01', 'theora')) and f.get('ext') in ('mp4', 'm4v', 'mov', 'ts', None)


def _muxable_a(f, ffmpeg):
    if ffmpeg:
        return True
    ac = (f.get('acodec') or '').lower()
    return not ac.startswith(('opus', 'vorbis', 'flac')) and f.get('ext') in ('m4a', 'mp4', 'aac', 'ts', None)


def _groups(info):
    ffmpeg = bool(config.ffmpeg)
    fmts = [dict(f, _i=i) for i, f in enumerate(info.get('formats') or []) if _usable(f, ffmpeg)]
    prog = [f for f in fmts if _has_v(f) and _has_a(f)]
    vonly = [f for f in fmts if _has_v(f) and not _has_a(f) and _muxable_v(f, ffmpeg)]
    aonly = [f for f in fmts if _has_a(f) and not _has_v(f)]
    amux = [f for f in aonly if _muxable_a(f, ffmpeg)]
    if not host.can_mux() or not amux:
        vonly = []
    return prog, vonly, aonly, amux


def _vkey(f):
    vc = (f.get('vcodec') or '').lower()
    compat = 2 if vc.startswith(('avc', 'h264')) else 1 if vc.startswith(('hev', 'hvc', 'h265')) else 0
    plain = 1 if (f.get('protocol') or 'https') in ('https', 'http') else 0
    return (f.get('height') or 0, min(f.get('fps') or 30, 60), compat, f.get('tbr') or 0, plain, f['_i'])


def _akey(f):
    ac = (f.get('acodec') or '').lower()
    # original language track first, then quality
    return (f.get('language_preference') or 0, 1 if ac.startswith('mp4a') else 0, f.get('abr') or f.get('tbr') or 0, f['_i'])


def _size(f):
    return f.get('filesize') or f.get('filesize_approx') or 0


def choose(info, quality):
    """quality: 'best', 'audio' or a height like '720'. Returns a plan dict."""
    prog, vonly, aonly, amux = _groups(info)
    if quality == 'audio':
        pool = aonly or prog
        if not pool:
            raise GrabError('This link has no audio track.')
        if not config.ffmpeg:
            m4a = [f for f in pool if _muxable_a(f, False) and not _has_v(f)]
            pool = m4a or pool
        a = max(pool, key=_akey)
        if _has_v(a):  # only combined files exist: fetch the smallest and keep just its sound
            a = min(pool, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0, f['_i']))
        return {'kind': 'audio', 'parts': [a], 'size': 0 if _has_v(a) else _size(a), 'height': 0}
    limit = int(quality) if str(quality).isdigit() else 10 ** 6

    if not any((f.get('height') or 0) <= limit for f in prog + vonly) and prog + vonly:
        limit = min(f.get('height') or 0 for f in prog + vonly)  # nothing that small: take the smallest there is

    def best(pool):
        ok = [f for f in pool if (f.get('height') or 0) <= limit]
        return max(ok, key=_vkey) if ok else None

    p, v = best(prog), best(vonly)
    if v and (not p or (v.get('height') or 0) > (p.get('height') or 0)):
        a = max(amux, key=_akey)
        return {'kind': 'video', 'parts': [v, a], 'size': (_size(v) + _size(a)) if _size(v) else 0,
                'height': v.get('height') or 0}
    if p:
        return {'kind': 'video', 'parts': [p], 'size': _size(p), 'height': p.get('height') or 0}
    if aonly:
        return choose(info, 'audio')
    raise GrabError('No downloadable format was found for this video.')


def describe(info):
    """What the UI needs to show a video and its quality choices."""
    prog, vonly, aonly, amux = _groups(info)
    heights = sorted({f.get('height') for f in prog + vonly if f.get('height')}, reverse=True)
    options = []
    try:
        top = choose(info, 'best')
        if top['kind'] == 'video':
            options.append({'id': 'best', 'label': 'Best quality' + (f" ({top['height']}p)" if top['height'] else ''),
                            'size': top['size']})
            seen = {top['height']}
            for h in HEIGHTS:
                if (top['height'] and h >= top['height']) or not any(x <= h for x in heights):
                    continue
                plan = choose(info, str(h))
                if plan['height'] and plan['height'] not in seen:
                    seen.add(plan['height'])
                    options.append({'id': str(plan['height']), 'label': f"{plan['height']}p", 'size': plan['size']})
    except GrabError:
        pass
    if aonly or prog:
        try:
            a = choose(info, 'audio')
            options.append({'id': 'audio', 'label': 'Audio only (MP3)' if config.ffmpeg else 'Audio only',
                            'size': a['size']})
        except GrabError:
            pass
    if not options:
        raise GrabError('No downloadable format was found for this video.')
    thumbs = info.get('thumbnails') or []
    return {'title': info.get('title') or 'video', 'thumb': info.get('thumbnail') or (thumbs[-1].get('url') if thumbs else '') or '',
            'duration': info.get('duration') or 0, 'uploader': info.get('uploader') or info.get('channel') or '',
            'site': (info.get('extractor_key') or '').replace('Grabit', '').replace('Sniff', 'Web page').replace('Browser', 'Web page') or 'Web',
            'url': info.get('webpage_url') or info.get('original_url') or '', 'options': options}


# ---------------------------------------------------------------- downloading

def safe_name(name, limit=110):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', name or '')
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name.encode('utf-8')[:limit].decode('utf-8', 'ignore').strip(' .') or 'video'


def free_path(folder, stem, ext):
    path, n = os.path.join(folder, f'{stem}.{ext}'), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f'{stem} ({n}).{ext}')
    return path


def thumb_path(file_path):
    d = os.path.join(config.data_dir, 'thumbs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, hashlib.sha1(os.path.abspath(file_path).encode('utf-8', 'replace')).hexdigest() + '.jpg')


class _Progress:
    def __init__(self, job, plan, span=(0.0, 1.0)):
        self.job, self.done = job, {}
        self.expected = sum(_size(p) for p in plan['parts']) if all(_size(p) for p in plan['parts']) else 0
        self.nparts, self.span = len(plan['parts']), span

    def __call__(self, d):
        if self.job.get('cancel'):
            raise DownloadCancelled('cancelled')
        name = d.get('filename') or ''
        got = d.get('downloaded_bytes') or 0
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        self.done[name] = (got, total if d['status'] != 'finished' else got)
        have = sum(g for g, _ in self.done.values())
        if self.expected:
            frac = have / max(self.expected, have)
        else:
            fracs = [g / t if t else 0 for g, t in self.done.values()]
            frac = sum(fracs) / max(self.nparts, len(fracs))
        lo, hi = self.span
        self.job.update(progress=round(100 * (lo + (hi - lo) * min(frac, 1.0)), 1), speed=d.get('speed') or 0,
                        eta=d.get('eta') or 0, size=self.expected or have)


def _run(info, fmt, outtmpl, account, hook, **extra):
    with net.ydl(account, format=fmt, outtmpl={'default': outtmpl}, progress_hooks=[hook], overwrites=True, **extra) as y:
        res = y.process_ie_result(copy.deepcopy(info), download=True)
        dl = res.get('requested_downloads') or [{}]
        return dl[0].get('filepath') or dl[0].get('_filename')


def _save_thumb(info, final, account):
    url = info.get('thumbnail')
    if not url:
        return
    try:
        page = net.fetch(url, {'Accept': 'image/*', 'Referer': info.get('webpage_url') or url}, account, limit=3 * 1024 * 1024)
        if page.ctype.startswith('image/') and page.body:
            with open(thumb_path(final), 'wb') as f:
                f.write(page.body)
    except Exception:
        pass


def download(job, url, quality, account=None, subdir=''):
    """Download one video for a job dict. Returns the final file path."""
    last = None
    for attempt in (0, 1):
        try:
            info = resolve(url, account, fresh=bool(attempt))
            return _download(job, info, quality, account, subdir)
        except DownloadCancelled:
            raise
        except GrabError:
            raise
        except Exception as e:  # links expire; one fresh try
            last = e
            if job.get('cancel'):
                raise DownloadCancelled('cancelled')
    raise GrabError(friendly(last))


def _download(job, info, quality, account, subdir):
    plan = choose(info, quality)
    job.update(title=info.get('title') or job.get('title') or 'video', status='running')
    folder = os.path.join(config.dl_dir, 'Audio' if plan['kind'] == 'audio' else 'Videos', safe_name(subdir) if subdir else '')
    os.makedirs(folder, exist_ok=True)
    stem = safe_name(info.get('title'))
    parts, ffmpeg = plan['parts'], bool(config.ffmpeg)
    work = os.path.join(folder, f'.grabit-{job["id"]}')
    os.makedirs(work, exist_ok=True)
    tmpl = os.path.join(work, 'part').replace('%', '%%') + '.%(format_id)s.%(ext)s'
    try:
        if ffmpeg:
            hook = _Progress(job, plan)
            if plan['kind'] == 'audio':
                got = _run(info, parts[0]['format_id'], tmpl, account, hook, postprocessors=[
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}])
            else:
                got = _run(info, '+'.join(p['format_id'] for p in parts), tmpl, account, hook, merge_output_format='mp4/mkv')
            if not got or not os.path.exists(got):
                got = _only_file(work)
        else:
            files = []
            for i, p in enumerate(parts):
                share = 0.92 if len(parts) == 1 else (0.86 if i == 0 else 0.10)
                lo = 0.0 if i == 0 else 0.86
                one = {'parts': [p]}
                f = _run(info, p['format_id'], tmpl, account, _Progress(job, one, (lo, lo + share)))
                files.append(f if f and os.path.exists(f) else _only_file(work, exclude=files))
            streamed = any((p.get('protocol') or 'https') not in ('https', 'http') for p in parts)
            strip = plan['kind'] == 'audio' and _has_v(parts[0])
            if len(files) > 1 or ((streamed or strip) and host.can_mux()):
                job.update(status='finishing')
                got = os.path.join(work, 'out.' + ('m4a' if plan['kind'] == 'audio' else 'mp4'))
                try:
                    host.mux(files, got, plan['kind'] == 'audio')
                except Exception as e:
                    if len(files) > 1:
                        raise GrabError('Could not combine video and audio: ' + str(e)[:120])
                    got = files[0]  # keep the raw stream; most players cope
            else:
                got = files[0]
        if job.get('cancel'):
            raise DownloadCancelled('cancelled')
        ext = os.path.splitext(got)[1].lstrip('.') or 'mp4'
        final = free_path(folder, stem, ext)
        os.replace(got, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if plan['kind'] == 'video':
        _save_thumb(info, final, account)
    host.file_ready(final)
    job.update(progress=100, size=os.path.getsize(final))
    return final


def _only_file(folder, exclude=()):
    files = [os.path.join(folder, f) for f in os.listdir(folder)
             if not f.endswith(('.part', '.ytdl')) and os.path.join(folder, f) not in exclude]
    if not files:
        raise GrabError('The download produced no file.')
    return max(files, key=os.path.getsize)
