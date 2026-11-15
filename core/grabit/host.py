"""Things only the host platform can do (Android bridge / iOS frameworks / desktop fallbacks)."""
import json
import os
import subprocess
import sys
import threading

from . import config

_bridge = None


def bridge():
    """The Kotlin Bridge object on Android, else None."""
    global _bridge
    if config.platform != 'android':
        return None
    if _bridge is None:
        from java import jclass  # provided by Chaquopy
        _bridge = jclass('app.grabit.Bridge')
    return _bridge


def _ios():
    if config.platform != 'ios':
        return None
    from . import ios
    return ios


def can_mux():
    return bool(config.ffmpeg) or config.platform in ('android', 'ios')


def mux(inputs, out, audio_only=False):
    """Combine the streams of `inputs` into one MP4/M4A without re-encoding."""
    b = bridge()
    if b is not None:
        err = b.mux(list(inputs), out, bool(audio_only))
        if err:
            raise RuntimeError(str(err))
        return
    if _ios():
        return _ios().mux(list(inputs), out, bool(audio_only))
    cmd = [config.ffmpeg, '-y', '-loglevel', 'error']
    for i in inputs:
        cmd += ['-i', i]
    for n in range(len(inputs)):
        cmd += ['-map', f'{n}:a?'] if audio_only else ['-map', f'{n}:v?', '-map', f'{n}:a?']
    cmd += ['-c', 'copy', '-movflags', '+faststart', out]
    r = subprocess.run(cmd, capture_output=True, text=True, **_noconsole())
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:] or 'ffmpeg failed')


def can_eval_js():
    return config.platform in ('android', 'ios')


def eval_js(script):
    """Run JavaScript in the hidden WebView and return what it returns (a string)."""
    if _ios():
        return _ios().eval_js(script)
    out = bridge().evalJs(script)
    if out is None:
        raise RuntimeError('WebView did not answer')
    return json.loads(str(out))


def can_render():
    return config.platform == 'android'


_render_lock = threading.Lock()


def render_page(url, collector, min_seconds=8, max_seconds=90):
    """Open the page in a real (hidden) browser view, let its scripts run and keep scrolling
    until it runs dry, render_stop() is called, or max_seconds pass.
    Returns {'dom': {...}, 'net': [image urls it requested]}."""
    with _render_lock:
        out = bridge().renderPage(url, collector, int(min_seconds * 1000), int(max_seconds * 1000))
    if out is None:
        raise RuntimeError('page did not load')
    data = json.loads(str(out))
    dom = data.get('dom')
    while isinstance(dom, str):   # evaluateJavascript hands back JSON-encoded text
        dom = json.loads(dom) if dom else {}
    return {'dom': dom or {}, 'net': data.get('net') or [], 'media': data.get('media') or []}


def render_stop():
    b = bridge()
    if b is not None:
        b.renderStop()


def render_count():
    b = bridge()
    return int(b.renderCount()) if b is not None else 0


def file_ready(path):
    """Tell the system a new file exists (Android gallery / media index)."""
    b = bridge()
    if b is not None:
        try:
            b.scanFile(path)
        except Exception:
            pass


def set_busy(busy, text=''):
    """Keep the app alive while downloads are running (Android foreground service)."""
    b = bridge()
    if b is not None:
        try:
            b.setBusy(bool(busy), text)
        except Exception:
            pass


def open_external(path):
    b = bridge()
    if _ios():
        _ios().share(path)
    elif b is not None:
        b.openFile(path)
    elif sys.platform == 'win32':
        os.startfile(path)  # noqa
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def show_in_folder(path):
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
    elif config.platform == 'desktop':
        open_external(os.path.dirname(path))


def share(path):
    b = bridge()
    if _ios():
        _ios().share(path)
    elif b is not None:
        b.shareFile(path)


def clipboard():
    return _ios().clipboard() if _ios() else ''


def login(site_url, name):
    b = bridge()
    if b is None:
        raise RuntimeError('Sign-in window is only available in the Android app')
    b.login(site_url, name)


def restart():
    b = bridge()
    if b is not None:
        b.restart()


def _noconsole():
    if sys.platform == 'win32':
        return {'creationflags': 0x08000000}
    return {}
