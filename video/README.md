# Kassa demo video (Remotion)

Script: `../docs/video-script.md`. Look, pipeline and clip manifest contract: `../docs/video-production.md`.
Output: `out/kassa-demo.mp4`, 1920x1080, 30 fps, H.264 + AAC, voice-over only (no music).

## Commands
```bash
npm run audio     # voice-over: one mp3 per scene (edge-tts, en-GB-RyanNeural, -5 %) + src/audioConfig.ts
npm run render    # full video -> out/kassa-demo.mp4 (17 min on the hub, 20 Oct)
npm run still -- --frame=1500   # one frame -> out/still.png
npm run studio    # live preview in the browser
npm run sheet     # contact sheet of the render -> out/sheet.png (one frame every 5 s)
```
All render commands use the system Chrome (`--browser-executable=/usr/bin/google-chrome`).

## Clips and the manifest
- Render only when the recorder is done: a clip deleted or rewritten during a render makes it fail (404).
- The recordings go to `video/clips/` with `video/clips/manifest.json` (contract in docs/video-production.md).
- `public/clips` is a symlink to `video/clips`. It must point to an **absolute** path, because Remotion copies
  `public/` into a temporary bundle and keeps symlinks as they are. `scripts/link-clips.mjs` creates it and runs
  automatically before `render`, `still` and `studio` (npm `pre*` scripts). The link is in `.gitignore`.
- The manifest is read **at render time** in the browser (`calculateMetadata` in `src/Root.tsx` ->
  `loadMedia()` in `src/manifest.ts`): `fetch(staticFile("clips/manifest.json"))`, then every file it lists is
  probed (video duration and size, image size). So new clips need no code change: drop them in, `npm run render`.
- A clip that is missing renders as a grey window frame labelled `clip: <id>`; a missing still as `still: <id>`.
  No manifest at all: the default file names (`intro.mp4`, `limits.mp4`, `scene1.mp4` ... `paypal-paid.png`,
  `paypal-cancelled.png`) are tried, with no events. No events = no callouts; stamps then fall back to fixed
  times that follow the voice-over.

Scene -> clip: intro -> `intro`, rules -> `limits`, scene1/2/3 -> `scene1/2/3` (split), chat -> `chat`,
stills `paypal-paid` (end of scene1) and `paypal-cancelled` (end of scene3). The closing card has no clip.

### Which part of a clip is shown
From 1.5 s before the first event to 3 s after the last one (the whole clip if there are no events). If that is
longer than the scene, the clip plays faster, up to 3x; if the clip is too short, it starts earlier and then
holds its last frame. See `planClip()` in `src/manifest.ts`.

### How events become callouts (`src/overlays.tsx`)
Events are matched by words in `what`:
- `click ...` with `x`,`y`: an ink dot at the point; in scene1 and rules also a circle (a wide one for `row`).
- `toast ...`: circle around the toast (bottom-left of the window named by `(left)`/`(right)`).
- the first `message: ...` in scene1: a frame around the drawer; every `message: <word>` lights a step chip.
- `card ...` (scene2), `Refused`/`Withdrawn` (scene3), `answer` (chat): circle with a label.
- scene1 `outcome`/`settled`: the SETTLED stamp; the number of seconds is taken from the first `<n> s` in any
  event text, else 14. scene2: YOUR TURN at `card`, PAID at the last event mentioning `paid`. scene3: WITHDRAWN
  at the last `withdrawn` event.
Optional extension of the contract: an event may carry `"box": [x, y, w, h]` (1920x1080 clip coordinates) to
place the circle exactly; without it the position comes from `x`,`y` or from defaults that match the Kassa layout.

## Durations
Scene length = max(voice-over + 0.6 s, the scene minimum from the script's timecodes), computed in
`src/timeline.ts` from `src/audioConfig.ts`. Transitions are a paper wipe of 8 frames out and 8 in, inside the
scenes, so the total is exactly the sum of the scenes. Voice-over timings for the animations come from the
sentence cues edge-tts writes next to each mp3 (`public/audio/<scene>.srt`).

## Files
- `src/Root.tsx`: compositions `KassaDemo` (and the old `Smoke` test).
- `src/KassaDemo.tsx`: the scene series, one `<Audio>` per scene.
- `src/scenes/*`: Intro, Rules, Split (scene1, scene2, scene3), Chat, Closing.
- `src/components.tsx`: paper, caption chip, paper wipe, stamp, window frame + clip, callout, ink dot, PiP.
- `src/theme.ts`: Kassa colours; Schibsted Grotesk from `public/fonts/*.woff2` (downloaded from Google Fonts,
  bundled locally so the render does not depend on the network).
- `scripts/make_audio.py`: voice-over from the script table (texts taken verbatim from the Voice-over column).
