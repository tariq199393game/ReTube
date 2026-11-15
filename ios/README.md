# Grabit for iPhone / iPad

The same engine and interface as the Android and Windows apps (`core/grabit`), wrapped with
[Briefcase](https://briefcase.readthedocs.io) and Toga.

- `src/grabitios/app.py` – the app: a full-screen web view in front of the engine.
- `core/grabit/ios.py` – iOS versions of the platform features (AVFoundation joins video and audio,
  JavaScriptCore solves YouTube's script challenges, system share sheet).
- `.github/workflows/ios.yml` – builds on a Mac, runs the app in an iPhone simulator with a self-test,
  and publishes an **unsigned** `Grabit.ipa`.

Apple only runs signed apps. Sign `Grabit.ipa` with your own Apple ID using 3uTools, Sideloadly,
AltStore or SideStore, then install it.
