"""Checks run inside the iOS simulator by the build, so problems show up before a phone ever sees the app.
Results go to Documents/selftest.txt."""
import json
import os
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def run(folder, url, app=None):
    lines = []

    def check(name, fn):
        started = time.time()
        try:
            detail = fn()
            lines.append('ok   %s (%.1fs) %s' % (name, time.time() - started, detail or ''))
        except Exception as e:
            lines.append('FAIL %s (%.1fs) %s: %s' % (name, time.time() - started, type(e).__name__, e))
            lines.append('     ' + traceback.format_exc().strip().splitlines()[-3].strip())
        with open(os.path.join(folder, 'selftest.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    from grabit import config, engine, host, jsc_webview, net

    def api(name, body=None):
        req = urllib.request.Request(url + 'api/' + name, data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    def ui():
        with urllib.request.urlopen(url, timeout=20) as r:
            page = r.read().decode()
        assert 'Grabit' in page
        return api('status')

    def javascript():
        assert host.eval_js('(function(){return String(6*7)})()') == '42'
        assert host.eval_js(jsc_webview.wrap('console.log(JSON.stringify({a:[1,2,3].map(function(x){return x*2})}))')) == '{"a":[2,4,6]}'
        return 'JavaScriptCore works'

    def join():
        out = os.path.join(folder, 'selftest-joined.mp4')
        host.mux([os.path.join(HERE, 'v.mp4'), os.path.join(HERE, 'a.m4a')], out)
        size = os.path.getsize(out)
        assert size > 20000, size
        return '%d bytes' % size

    def audio_only():
        out = os.path.join(folder, 'selftest-audio.m4a')
        host.mux([os.path.join(HERE, 'both.mp4')], out, True)
        size = os.path.getsize(out)
        assert 5000 < size < os.path.getsize(os.path.join(HERE, 'both.mp4')), size
        return '%d bytes' % size

    def https():
        page = net.fetch('https://pypi.org/simple/yt-dlp/')
        assert len(page.body) > 1000
        return 'certificates ok'

    def split_download():
        # separate video and audio files, the way YouTube serves them: must come out as one playable MP4
        import functools
        import http.server
        import threading
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(
            type('Q', (http.server.SimpleHTTPRequestHandler,), {'log_message': lambda *a: None}), directory=HERE))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:%d' % httpd.server_address[1]
        info = {'id': 'selftest', 'title': 'Self test clip', '_type': 'video', 'extractor': 't', 'extractor_key': 'T', 'webpage_url': base,
                'formats': [
                    {'format_id': 'a', 'url': base + '/a.m4a', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2', 'protocol': 'https'},
                    {'format_id': 'v', 'url': base + '/v.mp4', 'ext': 'mp4', 'height': 720, 'vcodec': 'avc1.64001f', 'acodec': 'none', 'protocol': 'https'}]}
        plan = engine.choose(info, 'best')
        assert [p['format_id'] for p in plan['parts']] == ['v', 'a'], plan
        final = engine._download({'id': 1}, info, 'best', None, '')
        lib = api('library')
        assert any(i['name'] == os.path.basename(final) and i['kind'] == 'video' for i in lib), lib
        return '%s, %d bytes' % (os.path.basename(final), os.path.getsize(final))

    def youtube():
        info = engine.describe(engine.resolve('https://www.youtube.com/watch?v=jNQXAC9IVRw'))
        return json.dumps(info['options'])[:300]

    def layout():
        import asyncio
        js = ('JSON.stringify({sat:getComputedStyle(document.documentElement).getPropertyValue("--sat"),'
              'inline:document.documentElement.getAttribute("style"),top:document.querySelector(".top").getBoundingClientRect().toJSON(),'
              'hero:document.querySelector(".hero").getBoundingClientRect().toJSON(),scrollY:window.scrollY,inner:[innerWidth,innerHeight],'
              'vv:[visualViewport.offsetTop,visualViewport.height],href:location.href.replace(/\\/[\\w-]{10,}\\//,"/T/"),'
              'css:[...document.styleSheets[0].cssRules].find(r=>r.selectorText==".top").cssText})')
        time.sleep(4)
        async def ask():
            return await app.web.evaluate_javascript(js)

        page = asyncio.run_coroutine_threadsafe(ask(), app.loop).result(15)
        native = app.web._impl.native
        from grabit.ios import _get
        frame = _get(native, 'frame')
        scroll = _get(native, 'scrollView')
        facts = {}
        for name in ('contentOffset', 'contentInset', 'adjustedContentInset', 'safeAreaInsets'):
            try:
                v = _get(scroll if name != 'safeAreaInsets' else native, name)
                facts[name] = [round(float(getattr(v, f[0])), 1) for f in v._fields_]
            except Exception as e:
                facts[name] = repr(e)
        try:
            facts['frame'] = [[round(float(getattr(part, f[0])), 1) for f in part._fields_] for part in (getattr(frame, frame._fields_[0][0]), getattr(frame, frame._fields_[1][0]))]
        except Exception as e:
            facts['frame'] = repr(e)
        def rect(r):
            return [[round(float(getattr(part, f[0])), 1) for f in part._fields_]
                    for part in (getattr(r, r._fields_[0][0]), getattr(r, r._fields_[1][0]))]

        try:
            facts['in_window'] = rect(native.convertRect_toView_(_get(native, 'bounds'), None))
            chain, view = [], native
            for _ in range(8):
                view = _get(view, 'superview')
                if view is None:
                    break
                chain.append([str(_get(view, 'class').name) if hasattr(_get(view, 'class'), 'name') else str(view)[:40], rect(_get(view, 'frame'))])
            facts['parents'] = chain
        except Exception as e:
            facts['in_window'] = repr(e)
        return '%s | native %s' % (page, facts)

    check('engine and page', ui)
    if app is not None:
        check('page layout', layout)
    check('javascript engine', javascript)
    check('join video + audio', join)
    check('audio only from a video', audio_only)
    check('https', https)
    check('download split streams end to end', split_download)
    check('clipboard', lambda: repr(host.clipboard())[:40])

    def insets():
        from grabit import ios
        return 'top/bottom = %s' % (ios.safe_area(),)

    check('safe area', insets)
    check('youtube (may be refused on build servers)', youtube)
    lines.append('DONE platform=%s folder=%s' % (config.platform, folder))
    with open(os.path.join(folder, 'selftest.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
