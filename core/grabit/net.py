"""yt-dlp session factory and a small page fetcher that shares its proxy/cookies."""
import os

import yt_dlp
from yt_dlp.networking import Request

from . import accounts, config

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')
BROWSER_HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}


class _Quiet:
    def __init__(self):
        self.warnings = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        pass


def ydl(account=None, **extra):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'logger': _Quiet(),
        'socket_timeout': 25,
        'retries': 5,
        'fragment_retries': 8,
        'extractor_retries': 2,
        'concurrent_fragment_downloads': 4,
        'windowsfilenames': True,
        'noplaylist': True,
        'cachedir': os.path.join(config.data_dir, 'cache'),
        'js_runtimes': dict(config.js_runtimes),
        'color': 'never',
    }
    proxy = config.proxy()
    if proxy:
        opts['proxy'] = proxy
    cookie = accounts.path(account if account is not None else config.settings()['account'])
    if cookie:
        opts['cookiefile'] = cookie
    if config.ffmpeg:
        opts['ffmpeg_location'] = config.ffmpeg
    opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


class Page:
    def __init__(self, url, ctype, body):
        self.url, self.ctype, self.body = url, ctype, body

    @property
    def text(self):
        return self.body.decode('utf-8', 'replace')


def fetch(url, headers=None, account=None, limit=12 * 1024 * 1024, session=None):
    """GET a URL the way a browser would. Returns a Page."""
    own = session is None
    session = session or ydl(account)
    try:
        h = dict(BROWSER_HEADERS)
        h.update(headers or {})
        resp = session.urlopen(Request(url, headers=h))
        try:
            body = resp.read(limit)
            return Page(resp.url, (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower(), body)
        finally:
            resp.close()
    finally:
        if own:
            session.close()


def open_stream(url, headers=None, account=None):
    """Open a URL for streaming; caller must close both returned objects."""
    session = ydl(account)
    h = dict(BROWSER_HEADERS)
    h['Accept'] = '*/*'
    h['Sec-Fetch-Dest'] = 'image'
    h['Sec-Fetch-Mode'] = 'no-cors'
    h['Sec-Fetch-Site'] = 'cross-site'
    h.pop('Sec-Fetch-User', None)
    h.pop('Upgrade-Insecure-Requests', None)
    h.update(headers or {})
    try:
        return session, session.urlopen(Request(url, headers=h))
    except Exception:
        session.close()
        raise
