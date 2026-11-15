"""Saved sign-ins. Each account is a Netscape cookies.txt file in the data folder."""
import json
import os
import re
import time

from . import config

HEADER = '# Netscape HTTP Cookie File\n'


def _dir():
    d = os.path.join(config.data_dir, 'accounts')
    os.makedirs(d, exist_ok=True)
    return d


def _safe(name):
    name = re.sub(r'[^\w .@-]', '', name or '', flags=re.U).strip()[:40]
    if not name:
        raise ValueError('Give the account a name')
    return name


def names():
    return sorted(f[:-4] for f in os.listdir(_dir()) if f.endswith('.txt'))


def path(name):
    """Cookie file for an account, or None if it does not exist."""
    if not name:
        return None
    try:
        p = os.path.join(_dir(), _safe(name) + '.txt')
    except ValueError:
        return None
    return p if os.path.isfile(p) else None


def _line(domain, name, value, path='/', secure=True, expires=None):
    domain = domain.strip()
    sub = 'TRUE' if domain.startswith('.') else 'FALSE'
    exp = int(expires or time.time() + 365 * 86400)
    return '\t'.join([domain, sub, path or '/', 'TRUE' if secure else 'FALSE', str(exp), name, value])


def _parse(text):
    """Accept cookies.txt, a JSON export from a cookie extension, or nothing else."""
    text = (text or '').strip()
    lines = []
    if text.startswith('[') or text.startswith('{'):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get('cookies') or []
        for c in data:
            if c.get('domain') and c.get('name') is not None:
                lines.append(_line(c['domain'], c['name'], str(c.get('value', '')), c.get('path', '/'),
                                   c.get('secure', True), c.get('expirationDate') or c.get('expires')))
    else:
        for ln in text.splitlines():
            raw = ln[10:] if ln.startswith('#HttpOnly_') else ln
            if raw.startswith('#') or not raw.strip():
                continue
            parts = raw.split('\t')
            if len(parts) == 7:
                lines.append(ln.rstrip('\r'))
    if not lines:
        raise ValueError('No cookies found. Paste a cookies.txt file or a JSON cookie export.')
    return lines


def add(name, text):
    lines = _parse(text)
    with open(os.path.join(_dir(), _safe(name) + '.txt'), 'w', encoding='utf-8') as f:
        f.write(HEADER + '\n'.join(lines) + '\n')
    return len(lines)


def add_from_webview(name, items_json):
    """Called by the Android sign-in screen: [{"domain": ".x.com", "cookies": "a=b; c=d"}]."""
    lines = []
    for item in json.loads(items_json):
        for pair in (item.get('cookies') or '').split(';'):
            if '=' in pair:
                k, v = pair.strip().split('=', 1)
                lines.append(_line(item['domain'], k, v))
    if not lines:
        raise ValueError('Sign-in did not produce any cookies')
    with open(os.path.join(_dir(), _safe(name) + '.txt'), 'w', encoding='utf-8') as f:
        f.write(HEADER + '\n'.join(lines) + '\n')
    return len(lines)


def delete(name):
    p = path(name)
    if p:
        os.remove(p)
