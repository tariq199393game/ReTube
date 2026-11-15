"""Runtime configuration shared by every module. The host app fills this in."""
import json
import os
import threading

data_dir = ''        # private app data (settings, accounts, engine updates)
dl_dir = ''          # where finished downloads go
platform = 'desktop'  # 'desktop' or 'android'
ffmpeg = None        # path to ffmpeg binary, or None
js_runtimes = {}     # yt-dlp js_runtimes dict (desktop: deno/node)

_lock = threading.Lock()
_DEFAULTS = {'proxy_mode': 'off', 'proxy_url': '', 'account': ''}


def setup(data, downloads, plat='desktop'):
    global data_dir, dl_dir, platform
    data_dir, dl_dir, platform = data, downloads, plat
    for d in (data_dir, dl_dir):
        os.makedirs(d, exist_ok=True)


def _path():
    return os.path.join(data_dir, 'settings.json')


def settings():
    with _lock:
        try:
            with open(_path(), encoding='utf-8') as f:
                return {**_DEFAULTS, **json.load(f)}
        except (OSError, ValueError):
            return dict(_DEFAULTS)


def save_settings(new):
    cur = settings()
    cur.update({k: v for k, v in new.items() if k in _DEFAULTS and isinstance(v, str)})
    with _lock:
        tmp = _path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cur, f)
        os.replace(tmp, _path())
    return cur


def proxy():
    """None = use the device's normal connection; otherwise a proxy URL."""
    s = settings()
    if s['proxy_mode'] == 'custom' and s['proxy_url'].strip():
        return s['proxy_url'].strip()
    return None
