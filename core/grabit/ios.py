"""iPhone / iPad implementations of the host features, using Apple's own frameworks.

There is no ffmpeg and no Node on iOS, so streams are joined with AVFoundation and
YouTube's JavaScript challenges are solved with JavaScriptCore.
"""
import os
import threading

run_on_main = None      # set by the app: schedules a function on the UI thread
web_view = None         # set by the app: the native view that shows the page
_libs = {}


def _objc(framework=None):
    from rubicon.objc import ObjCClass
    from rubicon.objc.runtime import load_library
    if framework and framework not in _libs:
        _libs[framework] = load_library(framework)
    return ObjCClass


def _get(obj, name):
    """Read an Objective-C value that the bridge may expose as a property or as a method."""
    value = getattr(obj, name)
    return value() if callable(value) else value


def _field(struct, name, index):
    return getattr(struct, name) if hasattr(struct, name) else getattr(struct, 'field_%d' % index)


def safe_area():
    """(top, bottom) in points: the parts of the screen taken by the notch and the home bar."""
    ObjCClass = _objc()
    app = _get(ObjCClass('UIApplication'), 'sharedApplication')
    window = _get(app, 'keyWindow') or _get(_get(app, 'windows'), 'firstObject')
    insets = _get(window, 'safeAreaInsets')
    top, bottom = float(_field(insets, 'top', 0)), float(_field(insets, 'bottom', 2))
    if web_view is not None:
        # The page's view does not always start at the top of the screen (the app framework can
        # place it higher). Measure where it really is, so the page clears what is hidden plus the notch.
        try:
            rect = web_view.convertRect_toView_(_get(web_view, 'bounds'), None)
            origin = getattr(rect, rect._fields_[0][0])
            size = getattr(rect, rect._fields_[1][0])
            y = float(getattr(origin, origin._fields_[1][0]))
            height = float(getattr(size, size._fields_[1][0]))
            screen = _get(window, 'bounds')
            screen_size = getattr(screen, screen._fields_[1][0])
            screen_height = float(getattr(screen_size, screen_size._fields_[1][0]))
            top = max(0.0, top - y)
            bottom = max(0.0, bottom - (screen_height - (y + height)))
        except Exception:
            pass
    return top, bottom


def eval_js(script):
    """Run a script and return its value as a string."""
    ObjCClass = _objc('JavaScriptCore')
    context = ObjCClass('JSContext').alloc().init()
    value = context.evaluateScript_(script)
    error = _get(context, 'exception')
    if error is not None:
        raise RuntimeError(str(_get(error, 'toString')))
    if value is None or _get(value, 'isNull') or _get(value, 'isUndefined'):
        raise RuntimeError('script returned nothing')
    return str(_get(value, 'toString'))


def mux(inputs, out, audio_only=False):
    """Join the video and audio streams of `inputs` into one MP4/M4A without re-encoding."""
    ObjCClass = _objc('AVFoundation')
    from rubicon.objc import Block
    NSURL = ObjCClass('NSURL')
    composition = ObjCClass('AVMutableComposition').composition()
    have = set()
    for path in inputs:
        asset = ObjCClass('AVURLAsset').URLAssetWithURL_options_(NSURL.fileURLWithPath_(path), None)
        for kind in (('soun',) if audio_only else ('vide', 'soun')):
            if kind in have:
                continue
            tracks = asset.tracksWithMediaType_(kind)
            if tracks is None or len(tracks) == 0:     # the bridge presents NSArray as a Python list
                continue
            source = tracks[0]
            span = _get(source, 'timeRange')                       # CMTimeRange of the whole track
            start = type(_field(span, 'start', 0))(0, 600, 1, 0)   # CMTime zero: value, timescale, valid flag, epoch
            track = composition.addMutableTrackWithMediaType_preferredTrackID_(kind, 0)
            if not track.insertTimeRange_ofTrack_atTime_error_(span, source, start, None):
                raise RuntimeError('could not read the %s stream' % ('audio' if kind == 'soun' else 'video'))
            if kind == 'vide':
                track.preferredTransform = _get(source, 'preferredTransform')
            have.add(kind)
    if not have:
        raise RuntimeError('no usable streams')
    if os.path.exists(out):
        os.remove(out)
    session = ObjCClass('AVAssetExportSession').exportSessionWithAsset_presetName_(composition, 'AVAssetExportPresetPassthrough')
    if session is None:
        raise RuntimeError('this video format cannot be joined on iOS')
    session.outputURL = NSURL.fileURLWithPath_(out)
    session.outputFileType = 'com.apple.m4a-audio' if audio_only else 'public.mpeg-4'
    session.shouldOptimizeForNetworkUse = True
    done = threading.Event()

    def finished() -> None:
        done.set()

    handler = Block(finished, None)
    session.exportAsynchronouslyWithCompletionHandler_(handler)
    if not done.wait(1800):
        session.cancelExport()
        raise RuntimeError('joining took too long')
    if int(_get(session, 'status')) != 3:        # AVAssetExportSessionStatusCompleted
        error = _get(session, 'error')
        raise RuntimeError(str(_get(error, 'localizedDescription')) if error is not None else 'export failed')


def clipboard():
    ObjCClass = _objc()
    text = _get(_get(ObjCClass('UIPasteboard'), 'generalPasteboard'), 'string')
    return str(text) if text is not None else ''


def share(path):
    """The system share sheet: Save Video, Save to Files, open in another app, AirDrop..."""
    ObjCClass = _objc()

    def show():
        url = ObjCClass('NSURL').fileURLWithPath_(path)
        items = ObjCClass('NSArray').arrayWithObject_(url)
        sheet = ObjCClass('UIActivityViewController').alloc().initWithActivityItems_applicationActivities_(items, None)
        app = _get(ObjCClass('UIApplication'), 'sharedApplication')
        window = _get(app, 'keyWindow') or _get(_get(app, 'windows'), 'firstObject')
        root = _get(window, 'rootViewController')
        while _get(root, 'presentedViewController') is not None:
            root = _get(root, 'presentedViewController')
        popover = _get(sheet, 'popoverPresentationController')      # iPad shows the sheet as a popover
        if popover is not None:
            popover.sourceView = _get(root, 'view')
        root.presentViewController_animated_completion_(sheet, True, None)

    if run_on_main is None:
        raise RuntimeError('not ready')
    run_on_main(show)
