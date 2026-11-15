"""Grabit for iPhone / iPad: a full-screen web view in front of the shared engine."""
import os
import threading
import traceback

import toga
from toga.style import Pack

DARK = '<html><body style="margin:0;background:#0b0b0d;color:#8d8d96;font:16px -apple-system;display:flex;' \
       'align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px">%s</body></html>'


class Grabit(toga.App):
    def startup(self):
        self.web = toga.WebView(style=Pack(flex=1))
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.web
        self.main_window.show()
        self._chrome()
        self.web.set_content('http://127.0.0.1/', DARK % 'Starting Grabit...')
        threading.Thread(target=self._start, daemon=True).start()

    def _chrome(self):
        """Let the page fill the screen: no title bar, dark behind the status bar, no rubber-banding."""
        try:
            native = self.web._impl.native
            native.opaque = False
            native.scrollView.bounces = False
            native.scrollView.contentInsetAdjustmentBehavior = 2     # never: the page handles safe areas itself
            native.allowsBackForwardNavigationGestures = False
        except Exception:
            traceback.print_exc()
        try:
            controller = self.main_window._impl.native.rootViewController
            if hasattr(controller, 'setNavigationBarHidden_animated_'):
                controller.setNavigationBarHidden_animated_(True, False)
            from rubicon.objc import ObjCClass
            black = ObjCClass('UIColor').colorWithRed_green_blue_alpha_(11 / 255, 11 / 255, 13 / 255, 1.0)
            self.main_window._impl.native.backgroundColor = black
            controller.view.backgroundColor = black
        except Exception:
            traceback.print_exc()

    def _start(self):
        try:
            import certifi
            os.environ.setdefault('SSL_CERT_FILE', certifi.where())     # iOS has no system certificate file
            from grabit import app as engine, ios
            ios.run_on_main = lambda fn: self.loop.call_soon_threadsafe(fn)
            home = os.path.expanduser('~')
            data = os.path.join(home, 'Library', 'Application Support', 'Grabit')
            downloads = os.path.join(home, 'Documents')      # shows up in the Files app as "Grabit"
            url = engine.launch(data, downloads, 'ios')
            print('Grabit is running at', url, flush=True)
            self.loop.call_soon_threadsafe(lambda: setattr(self.web, 'url', url))
            if os.environ.get('GRABIT_SELFTEST'):
                from grabitios import selftest
                selftest.run(downloads, url)
        except Exception:
            text = traceback.format_exc()
            print(text, flush=True)
            page = DARK % ('Grabit could not start.<br><br><small>%s</small>' % text.splitlines()[-1].replace('<', '&lt;'))
            self.loop.call_soon_threadsafe(lambda: self.web.set_content('http://127.0.0.1/', page))


def main():
    return Grabit('Grabit', 'app.grabit.grabitios')
