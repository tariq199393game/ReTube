"""iPhone / iPad implementations of the host features, using Apple's own frameworks.

There is no ffmpeg and no Node on iOS, so streams are joined with AVFoundation and
YouTube's JavaScript challenges are solved with JavaScriptCore.
"""
import os
import threading

run_on_main = None      # set by the app: schedules a function on the UI thread
_libs = {}


def _objc(framework=None):
    from rubicon.objc import ObjCClass
    from rubicon.objc.runtime import load_library
    if framework and framework not in _libs:
        _libs[framework] = load_library(framework)
    return ObjCClass


def eval_js(script):
    """Run a script and return its value as a string."""
    ObjCClass = _objc('JavaScriptCore')
    context = ObjCClass('JSContext').alloc().init()
    value = context.evaluateScript_(script)
    error = context.exception
    if error is not None:
        raise RuntimeError(str(error.toString()))
    if value is None or value.isNull() or value.isUndefined():
        raise RuntimeError('script returned nothing')
    return str(value.toString())


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
            if not tracks or tracks.count == 0:
                continue
            source = tracks.objectAtIndex_(0)
            span = source.timeRange                       # CMTimeRange of the whole track
            start = type(span.field_0)(0, 600, 1, 0)      # CMTime zero: value, timescale, valid flag, epoch
            track = composition.addMutableTrackWithMediaType_preferredTrackID_(kind, 0)
            if not track.insertTimeRange_ofTrack_atTime_error_(span, source, start, None):
                raise RuntimeError('could not read the %s stream' % ('audio' if kind == 'soun' else 'video'))
            if kind == 'vide':
                track.preferredTransform = source.preferredTransform
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
    if int(session.status) != 3:        # AVAssetExportSessionStatusCompleted
        error = session.error
        raise RuntimeError(str(error.localizedDescription) if error is not None else 'export failed')


def clipboard():
    ObjCClass = _objc()
    text = ObjCClass('UIPasteboard').generalPasteboard.string
    return str(text) if text is not None else ''


def share(path):
    """The system share sheet: Save Video, Save to Files, open in another app, AirDrop..."""
    ObjCClass = _objc()

    def show():
        url = ObjCClass('NSURL').fileURLWithPath_(path)
        items = ObjCClass('NSArray').arrayWithObject_(url)
        sheet = ObjCClass('UIActivityViewController').alloc().initWithActivityItems_applicationActivities_(items, None)
        app = ObjCClass('UIApplication').sharedApplication
        window = app.keyWindow or app.windows.firstObject()
        root = window.rootViewController
        while root.presentedViewController is not None:
            root = root.presentedViewController
        popover = sheet.popoverPresentationController      # iPad shows the sheet as a popover
        if popover is not None:
            popover.sourceView = root.view
        root.presentViewController_animated_completion_(sheet, True, None)

    if run_on_main is None:
        raise RuntimeError('not ready')
    run_on_main(show)
