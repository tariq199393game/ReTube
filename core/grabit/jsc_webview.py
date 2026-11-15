"""Lets yt-dlp solve YouTube's JavaScript challenges with the phone's own WebView.

On a PC yt-dlp runs those scripts with Deno or Node. Phones have neither, but every
Android device ships a full JavaScript engine in its WebView, so we hand the script
to it instead. Without this, YouTube offers only a reduced set of formats.
"""
from . import host


def wrap(script):
    """The solver prints its answer with console.log; capture that as a return value."""
    return ('(function(){var __out=null;var console={log:function(s){__out=String(s);},'
            'warn:function(){},error:function(){},info:function(){},debug:function(){}};\n'
            + script + '\n;return __out;})()')


def register():
    if not host.can_eval_js():
        return False
    try:
        from yt_dlp.extractor.youtube.jsc._builtin.ejs import EJSBaseJCP
        from yt_dlp.extractor.youtube.jsc.provider import (
            JsChallengeProviderError, register_preference, register_provider)
        from yt_dlp.extractor.youtube.pot._provider import BuiltinIEContentProvider
    except Exception:
        return False  # engine layout changed; YouTube falls back to its reduced mode

    @register_provider
    class WebViewJCP(EJSBaseJCP, BuiltinIEContentProvider):
        PROVIDER_NAME = 'webview'
        JS_RUNTIME_NAME = 'webview'

        def is_available(self, /):
            return self._available

        def _run_js_runtime(self, stdin, /):
            try:
                out = host.eval_js(wrap(stdin))
            except Exception as e:
                raise JsChallengeProviderError(f'WebView could not run the solver: {e}')
            if not out:
                raise JsChallengeProviderError('WebView returned nothing')
            return out

    @register_preference(WebViewJCP)
    def _preference(provider, requests):
        return 1000

    return True
