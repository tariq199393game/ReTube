"""Entry point used by both host apps."""
from . import bootstrap, config


def launch(data_dir, download_dir, platform='desktop', ffmpeg=None, js_runtimes=None, port=0):
    """Configure and start Grabit. Returns the local URL of the UI."""
    config.setup(data_dir, download_dir, platform)
    config.ffmpeg = ffmpeg
    config.js_runtimes = js_runtimes or {}
    bootstrap.activate()          # must run before the engine is imported
    from . import jsc_webview, server
    import yt_dlp.version
    bootstrap.state['active'] = yt_dlp.version.__version__   # what is really loaded
    bootstrap.state['bundled'] = bootstrap.state['bundled'] or bootstrap.state['active']
    jsc_webview.register()
    url = server.start(port)
    bootstrap.check_in_background()
    return url
