"""Everything Grabit has downloaded, for the in-app player and viewer."""
import os

from . import config, engine

VIDEO = ('mp4', 'mkv', 'webm', 'mov', 'm4v', 'ts', 'flv', 'avi', '3gp')
AUDIO = ('mp3', 'm4a', 'aac', 'opus', 'ogg', 'wav', 'flac', 'weba')
IMAGE = ('jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'svg', 'bmp', 'ico', 'tif', 'tiff', 'heic')
MIME = {'mp4': 'video/mp4', 'm4v': 'video/mp4', 'mkv': 'video/x-matroska', 'webm': 'video/webm', 'mov': 'video/quicktime',
        'ts': 'video/mp2t', 'flv': 'video/x-flv', 'avi': 'video/x-msvideo', '3gp': 'video/3gpp',
        'mp3': 'audio/mpeg', 'm4a': 'audio/mp4', 'aac': 'audio/aac', 'opus': 'audio/ogg', 'ogg': 'audio/ogg',
        'wav': 'audio/wav', 'flac': 'audio/flac', 'weba': 'audio/webm',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif',
        'avif': 'image/avif', 'svg': 'image/svg+xml', 'bmp': 'image/bmp', 'ico': 'image/x-icon', 'tif': 'image/tiff',
        'tiff': 'image/tiff', 'heic': 'image/heic'}


def kind_of(name):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return 'video' if ext in VIDEO else 'audio' if ext in AUDIO else 'image' if ext in IMAGE else ''


def mime_of(name):
    return MIME.get(name.rsplit('.', 1)[-1].lower(), 'application/octet-stream')


def resolve(rel):
    """Map a library-relative path to a real file, refusing anything outside the folder."""
    root = os.path.realpath(config.dl_dir)
    full = os.path.realpath(os.path.join(root, *[p for p in rel.replace('\\', '/').split('/') if p]))
    if full != root and not full.startswith(root + os.sep):
        raise PermissionError(rel)
    return full


def listing():
    items = []
    for base, dirs, files in os.walk(config.dl_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in files:
            kind = kind_of(name)
            if not kind or name.startswith('.'):
                continue
            full = os.path.join(base, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, config.dl_dir).replace(os.sep, '/')
            folder = os.path.dirname(rel)
            items.append({'rel': rel, 'name': name, 'kind': kind, 'size': st.st_size, 'time': int(st.st_mtime),
                          'folder': folder.split('/', 1)[1] if '/' in folder else '',
                          'thumb': kind == 'video' and os.path.exists(engine.thumb_path(full))})
    items.sort(key=lambda i: -i['time'])
    return items


def delete(rel):
    full = resolve(rel)
    if os.path.isfile(full):
        os.remove(full)
        try:
            os.remove(engine.thumb_path(full))
        except OSError:
            pass
        parent = os.path.dirname(full)
        try:  # tidy empty album folders, never the top-level ones
            root = os.path.realpath(config.dl_dir)
            if os.path.realpath(os.path.dirname(parent)) != root and os.path.realpath(parent) != root \
                    and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass
