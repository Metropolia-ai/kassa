import { AUDIO, FPS } from "./audioConfig";

export { FPS };
export type SceneId = "intro" | "rules" | "scene1" | "scene2" | "scene3" | "chat" | "closing";

/** Scene length = max(voice-over + 0.6 s, the minimum from the script's timecodes). */
export const SCENES = AUDIO.map((a) => ({
  ...a,
  id: a.id as SceneId,
  frames: Math.ceil(Math.max(a.durationSeconds + 0.6, a.minSeconds) * FPS),
}));

export const TOTAL_FRAMES = SCENES.reduce((s, x) => s + x.frames, 0);

export const sec = (s: number) => Math.round(s * FPS);

/** Transition length (paper wipe in/out), frames. */
export const WIPE = 8;
