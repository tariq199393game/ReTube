"""Download queue: a few worker threads and a list of job dicts the UI polls."""
import itertools
import os
import queue
import re
import threading
import time
from urllib.parse import unquote, urlparse

from yt_dlp.utils import DownloadCancelled

from . import config, engine, host, net, sniff

_jobs, _lock = [], threading.Lock()
_queue, _ids = queue.Queue(), itertools.count(1)
_started = False
WORKERS = 2


def _public(j):
    return {k: v for k, v in j.items() if k not in ('args', 'cancel')}


def listing():
    with _lock:
        return [_public(j) for j in reversed(_jobs)]


def _new(kind, title, args):
    job = {'id': next(_ids), 'kind': kind, 'title': title or 'video', 'status': 'queued', 'progress': 0,
           'speed': 0, 'eta': 0, 'size': 0, 'file': '', 'error': '', 'added': time.time(), 'args': args, 'cancel': False}
    with _lock:
        _jobs.append(job)
    _ensure_workers()
    _queue.put(job)
    return job['id']


def add_video(url, title, quality, account, subdir=''):
    return _new('audio' if quality == 'audio' else 'video', title or url, (url, quality, account, subdir))


def add_images(page, title, urls, account):
    return _new('images', title or 'Images', (page, title, list(urls), account))


def cancel(job_id):
    with _lock:
        for j in _jobs:
            if j['id'] == job_id and j['status'] in ('queued', 'running', 'finishing'):
                j['cancel'] = True
                if j['status'] == 'queued':
                    j['status'] = 'cancelled'


def clear():
    with _lock:
        _jobs[:] = [j for j in _jobs if j['status'] in ('queued', 'running', 'finishing')]


def _active():
    with _lock:
        return sum(1 for j in _jobs if j['status'] in ('queued', 'running', 'finishing'))


def _ensure_workers():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    for _ in range(WORKERS):
        threading.Thread(target=_worker, daemon=True).start()


def _worker():
    while True:
        job = _queue.get()
        if job['cancel'] or job['status'] == 'cancelled':
            job['status'] = 'cancelled'
            continue
        job['status'] = 'running'
        host.set_busy(True, job['title'])
        try:
            if job['kind'] == 'images':
                path = _images(job, *job['args'])
            else:
                path = engine.download(job, *job['args'])
            job.update(status='done', progress=100, file=os.path.relpath(path, config.dl_dir).replace(os.sep, '/'))
        except DownloadCancelled:
            job['status'] = 'cancelled'
        except engine.GrabError as e:
            job.update(status='error', error=str(e))
        except Exception as e:
            job.update(status='error', error=engine.friendly(e))
        finally:
            job.update(speed=0, eta=0)
            if not _active():
                host.set_busy(False)


def _images(job, page, title, urls, account):
    folder = os.path.join(config.dl_dir, 'Images', engine.safe_name(title or urlparse(page).hostname or 'Images', 80))
    os.makedirs(folder, exist_ok=True)
    saved, total, first = 0, 0, ''
    for i, url in enumerate(urls):
        if job['cancel']:
            raise DownloadCancelled('cancelled')
        try:
            session, resp = net.open_stream(url, {'Referer': page or url}, account)
        except Exception:
            job['progress'] = round(100 * (i + 1) / len(urls), 1)
            continue
        try:
            ctype = (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            ext = sniff.IMAGE_MIME.get(ctype) or sniff.image_type(resp.url) or sniff.image_type(url)
            if not ext or (ctype and not ctype.startswith(('image/', 'application/octet-stream', 'binary/'))):
                continue
            stem = unquote(urlparse(url).path.rsplit('/', 1)[-1]).rsplit('.', 1)[0]
            stem = engine.safe_name(re.sub(r'[%&=?]+', ' ', stem), 70)
            if stem == 'video':
                stem = f'image-{i + 1}'
            path = engine.free_path(folder, stem, ext)
            with open(path + '.part', 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
            os.replace(path + '.part', path)
            host.file_ready(path)
            saved += 1
            first = first or path
        except Exception:
            pass
        finally:
            resp.close()
            session.close()
            job.update(progress=round(100 * (i + 1) / len(urls), 1), size=total)
    if not saved:
        raise engine.GrabError('None of the selected images could be downloaded.')
    job['title'] = f'{title} — {saved} image' + ('s' if saved != 1 else '')
    return first if saved == 1 else folder
