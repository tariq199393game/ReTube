"""Keeps the download engine (yt-dlp) fresh without reinstalling the app.

Sites change constantly; a frozen engine is the main reason downloads stop working.
A newer engine is fetched from PyPI into the app's data folder and put in front of
the bundled one on the next start. Must be imported before yt_dlp.
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
import zipfile

from . import config

state = {'active': '', 'bundled': '', 'pending': '', 'checking': False, 'error': ''}


def _vt(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:4])


def _engine_dir():
    return os.path.join(config.data_dir, 'engine')


def _bundled_version():
    try:  # works where sources are compiled away (Android)
        from importlib.metadata import version
        return version('yt-dlp')
    except Exception:
        pass
    try:
        spec = importlib.util.find_spec('yt_dlp')
        path = os.path.join(os.path.dirname(spec.origin), 'version.py')
        try:
            text = spec.loader.get_data(path).decode()
        except Exception:
            with open(path, encoding='utf-8') as f:
                text = f.read()
        return re.search(r"__version__\s*=\s*'([^']+)'", text).group(1)
    except Exception:
        return ''


def activate():
    """Put the newest downloaded engine on sys.path if it beats the bundled one."""
    state['bundled'] = _bundled_version()
    state['active'] = state['bundled']
    try:
        with open(os.path.join(_engine_dir(), 'current.json'), encoding='utf-8') as f:
            cur = json.load(f)
        path = os.path.join(_engine_dir(), cur['dir'])
        if os.path.isdir(os.path.join(path, 'yt_dlp')) and _vt(cur['version']) > _vt(state['bundled']):
            sys.path.insert(0, path)
            state['active'] = cur['version']
        # remove engines that are no longer used
        for name in os.listdir(_engine_dir()):
            full = os.path.join(_engine_dir(), name)
            if os.path.isdir(full) and name != cur['dir']:
                shutil.rmtree(full, ignore_errors=True)
    except (OSError, ValueError, KeyError):
        pass


def _opener():
    proxy = config.proxy()
    if proxy and proxy.startswith('http'):
        return urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    return urllib.request.build_opener()


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Grabit'})
    with _opener().open(req, timeout=30) as r:
        return r.read()


def _wheel(meta):
    for f in meta['urls']:
        if f['packagetype'] == 'bdist_wheel' and f['filename'].endswith('-none-any.whl'):
            return f
    raise RuntimeError('no wheel published')


def _install(meta, dest):
    f = _wheel(meta)
    data = _get(f['url'])
    if hashlib.sha256(data).hexdigest() != f['digests']['sha256']:
        raise RuntimeError('download was corrupted')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.startswith('/') or '..' in n.split('/'):
                raise RuntimeError('bad archive')
        z.extractall(dest)


def check(force=False):
    """Look for a newer engine; download it if there is one. Returns state."""
    if state['checking']:
        return state
    stamp = os.path.join(_engine_dir(), 'checked')
    try:
        if not force and time.time() - os.path.getmtime(stamp) < 12 * 3600:
            return state
    except OSError:
        pass
    state.update(checking=True, error='')
    try:
        os.makedirs(_engine_dir(), exist_ok=True)
        meta = json.loads(_get('https://pypi.org/pypi/yt-dlp/json'))
        latest = meta['info']['version']
        if _vt(latest) > _vt(state['pending'] or state['active']):
            dirname = 'v' + re.sub(r'[^0-9.]', '', latest)
            dest = os.path.join(_engine_dir(), dirname)
            tmp = dest + '.tmp'
            shutil.rmtree(tmp, ignore_errors=True)
            _install(meta, tmp)
            # the YouTube solver scripts are pinned to an exact companion version
            for req in meta['info'].get('requires_dist') or []:
                m = re.match(r'yt-dlp-ejs\s*==\s*([0-9.]+)', req)
                if m:
                    _install(json.loads(_get(f'https://pypi.org/pypi/yt-dlp-ejs/{m.group(1)}/json')), tmp)
                    break
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(tmp, dest)
            with open(os.path.join(_engine_dir(), 'current.json'), 'w', encoding='utf-8') as f:
                json.dump({'dir': dirname, 'version': latest}, f)
            state['pending'] = latest
        with open(stamp, 'w') as f:
            f.write(str(time.time()))
    except Exception as e:  # offline etc. - never fatal
        state['error'] = str(e)[:200]
    finally:
        state['checking'] = False
    return state


def check_in_background():
    threading.Thread(target=check, daemon=True).start()
