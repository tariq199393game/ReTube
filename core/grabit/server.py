"""Local web server: serves the UI and exposes the engine to it. Bound to 127.0.0.1 only."""
import itertools
import json
import os
import pkgutil
import secrets
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, accounts, bootstrap, config, engine, host, jobs, library, net, sniff

TOKEN = secrets.token_urlsafe(16)
STATIC = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
          'style.css': 'text/css; charset=utf-8', 'icon.svg': 'image/svg+xml', 'art-video.svg': 'image/svg+xml',
          'art-images.svg': 'image/svg+xml', 'art-library.svg': 'image/svg+xml', 'art-settings.svg': 'image/svg+xml'}
LOGIN_SITES = {'YouTube / Google': 'https://accounts.google.com/ServiceLogin?service=youtube&continue=https://m.youtube.com/',
               'Facebook': 'https://m.facebook.com/login/', 'Instagram': 'https://www.instagram.com/accounts/login/',
               'X (Twitter)': 'https://x.com/i/flow/login', 'TikTok': 'https://www.tiktok.com/login'}


def _status():
    return {'app': __version__, 'platform': config.platform, 'engine': bootstrap.state, 'ffmpeg': bool(config.ffmpeg),
            'folder': config.dl_dir, 'sites': list(LOGIN_SITES) if config.platform == 'android' else []}


class Search:
    """One running lookup: the UI polls `found` and may set `stopped`."""

    def __init__(self, kind):
        self.kind, self.stopped, self.found, self.done, self.result, self.error = kind, False, 0, False, None, ''


_searches, _search_ids = {}, itertools.count(1)


def find_images(url, account, ctl=None):
    url = url.strip()
    if not url.startswith('http'):
        url = 'https://' + url
    res, err = {'title': '', 'page': url, 'images': []}, None
    try:
        res = sniff.find_images(url, lambda u, h: net.fetch(u, h, account))
    except Exception as e:
        err = e
    if ctl:
        ctl.found = len(res['images'])
    direct = len(res['images']) == 1 and res['images'][0]['url'] == res['page']
    if host.can_render() and not direct and not (ctl and ctl.stopped):
        # most modern pages build their content with scripts: look at the page as a browser shows it
        try:
            collector = pkgutil.get_data('grabit', 'web/collect.js').decode()
            res = sniff.merge_rendered(res, host.render_page(res['page'] or url, collector), res['page'] or url)
            err = None
        except Exception as e:
            err = err or e
    if err and not res['images']:
        raise engine.GrabError(engine.friendly(err))
    if not res['images'] and not (ctl and ctl.stopped):
        try:  # social posts: fall back to what the video engine knows about the post
            info = engine.resolve(url, account)
            thumbs = sorted(info.get('thumbnails') or [], key=lambda t: (t.get('width') or 0))
            if thumbs:
                res['images'] = [{'url': thumbs[-1]['url'], 'type': sniff.image_type(thumbs[-1]['url']), 'alt': '',
                                  'w': thumbs[-1].get('width') or 0, 'h': thumbs[-1].get('height') or 0}]
        except Exception:
            pass
    if not res['images']:
        raise engine.GrabError('No images were found on this page.')
    return res


def _search_start(kind, url, account):
    ctl = Search(kind)
    sid = next(_search_ids)
    _searches[sid] = ctl
    for old in [k for k in _searches if k < sid - 20]:
        _searches.pop(old, None)

    def run():
        try:
            if kind == 'playlist':
                ctl.result = engine.playlist(url, account, ctl)
            elif kind == 'images':
                ctl.result = find_images(url, account, ctl)
            else:
                ctl.result = engine.describe(engine.resolve(url, account))
        except engine.GrabError as e:
            ctl.error = str(e)
        except Exception as e:
            ctl.error = engine.friendly(e)
        ctl.done = True

    threading.Thread(target=run, daemon=True).start()
    return sid


def _search_poll(sid):
    ctl = _searches.get(sid)
    if not ctl:
        return {'done': True, 'error': 'Search expired. Try again.'}
    found = ctl.found
    if ctl.kind == 'images' and not ctl.done:
        try:
            found = max(found, host.render_count())
        except Exception:
            pass
    out = {'done': ctl.done, 'found': found, 'stopped': ctl.stopped}
    if ctl.done:
        out.update(result=ctl.result, error=ctl.error)
        _searches.pop(sid, None)
    return out


def _api(name, q):
    """POST endpoints. q is the decoded JSON body; returns a JSON-able object."""
    account = q.get('account')
    if name == 'info':
        return engine.describe(engine.resolve(q.get('url', ''), account))
    if name == 'playlist':
        return engine.playlist(q.get('url', ''), account)
    if name == 'images':
        return find_images(q.get('url', ''), account)
    if name == 'search':
        return {'id': _search_start(q.get('kind', 'video'), q.get('url', ''), account)}
    if name == 'search_stop':
        ctl = _searches.get(q.get('id'))
        if ctl:
            ctl.stopped = True
            if ctl.kind == 'images':
                host.render_stop()
        return {'ok': True}
    if name == 'download':
        ids = [jobs.add_video(i['url'], i.get('title', ''), q.get('quality', 'best'), account, q.get('folder', ''))
               for i in q.get('items', []) if i.get('url')]
        return {'jobs': ids}
    if name == 'download_images':
        urls = [u for u in q.get('urls', []) if isinstance(u, str) and u.startswith('http')]
        if not urls:
            raise engine.GrabError('Select at least one image.')
        return {'jobs': [jobs.add_images(q.get('page', ''), q.get('title', ''), urls, account)]}
    if name == 'cancel':
        jobs.cancel(int(q.get('id', 0)))
    elif name == 'clear':
        jobs.clear()
    elif name == 'delete':
        library.delete(q.get('rel', ''))
    elif name == 'open':
        host.open_external(library.resolve(q.get('rel', '')))
    elif name == 'reveal':
        host.show_in_folder(library.resolve(q.get('rel', '')))
    elif name == 'share':
        host.share(library.resolve(q.get('rel', '')))
    elif name == 'settings':
        return config.save_settings(q)
    elif name == 'account_add':
        return {'cookies': accounts.add(q.get('name', ''), q.get('cookies', ''))}
    elif name == 'account_delete':
        accounts.delete(q.get('name', ''))
        if config.settings()['account'] == q.get('name'):
            config.save_settings({'account': ''})
    elif name == 'account_login':
        site = q.get('site', '')
        host.login(LOGIN_SITES.get(site) or site, q.get('name') or site)
    elif name == 'update_engine':
        return bootstrap.check(force=True)
    elif name == 'restart':
        host.restart()
    else:
        raise KeyError(name)
    return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Grabit'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        if 'Cache-Control' not in (extra or {}):
            self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _route(self):
        u = urlparse(self.path)
        parts = u.path.split('/', 2)
        if len(parts) < 3 or not secrets.compare_digest(parts[1], TOKEN):
            self._send(403, {'error': 'forbidden'})
            return None, None
        return parts[2], parse_qs(u.query)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            path, query = self._route()
            if path is None:
                return
            if path == '' or path in STATIC:
                name = path or 'index.html'
                cache = {'Cache-Control': 'max-age=86400'} if name.endswith('.svg') else None
                self._send(200, pkgutil.get_data('grabit', 'web/' + name), STATIC[name], cache)
            elif path == 'api/jobs':
                self._send(200, jobs.listing())
            elif path == 'api/search':
                self._send(200, _search_poll(int(query.get('id', ['0'])[0])))
            elif path == 'api/library':
                self._send(200, library.listing())
            elif path == 'api/clipboard':
                self._send(200, {'text': host.clipboard()})
            elif path == 'api/status':
                self._send(200, _status())
            elif path == 'api/settings':
                self._send(200, {**config.settings(), 'accounts': accounts.names()})
            elif path.startswith('media/'):
                self._file(library.resolve(unquote(path[6:])))
            elif path.startswith('libthumb/'):
                self._file(engine.thumb_path(library.resolve(unquote(path[9:]))), 'image/jpeg')
            elif path == 'thumb':
                self._proxy(query.get('u', [''])[0], query.get('r', [''])[0], query.get('a', [''])[0])
            else:
                self._send(404, {'error': 'not found'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, PermissionError):
            self._send(404, {'error': 'not found'})

    def do_POST(self):
        try:
            path, _ = self._route()
            if path is None:
                return
            n = int(self.headers.get('Content-Length') or 0)
            q = json.loads(self.rfile.read(n) or b'{}') if n else {}
            self._send(200, _api(path.replace('api/', '', 1), q))
        except (engine.GrabError, ValueError) as e:
            self._send(400, {'error': str(e)})
        except KeyError:
            self._send(404, {'error': 'not found'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            self._send(500, {'error': engine.friendly(e)})

    def _file(self, full, ctype=None):
        size = os.path.getsize(full)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get('Range', '')
        if rng.startswith('bytes='):
            a, _, b = rng[6:].split(',')[0].partition('-')
            if a:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            if start > end or start >= size:
                self._send(416, b'', 'text/plain', {'Content-Range': f'bytes */{size}'})
                return
            code = 206
        self.send_response(code)
        self.send_header('Content-Type', ctype or library.mime_of(full))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(full, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _proxy(self, url, referer, account):
        """Fetch a remote image for the UI (previews need the right Referer and no CORS)."""
        if not url.startswith(('http://', 'https://')):
            self._send(400, {'error': 'bad url'})
            return
        try:
            session, resp = net.open_stream(url, {'Referer': referer or url}, account or None)
        except Exception:
            self._send(502, {'error': 'unreachable'})
            return
        try:
            body = resp.read(40 * 1024 * 1024)
            ctype = (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if not ctype.startswith('image/'):
                guess = sniff.image_type(url)
                ctype = library.MIME.get(guess, '') if guess else ''
            if not ctype:
                self._send(415, {'error': 'not an image'})
                return
            # never let fetched content run as a page inside the app
            self._send(200, body, ctype, {'Cache-Control': 'max-age=3600', 'X-Content-Type-Options': 'nosniff',
                                          'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})
        finally:
            resp.close()
            session.close()


def _serve(port):
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _keep_alive(httpd):
    """iOS closes an app's listening socket while it is suspended. When the app comes
    back, notice that and listen again on the same port so the page keeps working."""
    port = httpd.server_address[1]
    while True:
        time.sleep(2)
        try:
            socket.create_connection(('127.0.0.1', port), timeout=2).close()
        except OSError:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
            try:
                httpd = _serve(port)
            except OSError:
                pass


def start(port=0):
    """Start serving in a background thread. Returns the URL of the UI."""
    httpd = _serve(port)
    if config.platform == 'ios':
        threading.Thread(target=_keep_alive, args=(httpd,), daemon=True).start()
    return f'http://127.0.0.1:{httpd.server_address[1]}/{TOKEN}/'
