import { AUDIO, FPS } from "./audioConfig";

export { FPS };
export type SceneId = "intro" | "rules" | "scene1" | "scene2" | "scene3" | "chat" | "closing";

/**
 * Order of the scenes. The duplicate (scene3) comes straight after scene1: its voice-over says
 * "A minute later", and the scene2 recording already shows the withdrawn duplicate.
 */
export const ORDER: SceneId[] = ["intro", "rules", "scene1", "scene3", "scene2", "chat", "closing"];

/**
 * Scene length in seconds where the recording sets it (the clip segment at <= 1.3x, see
 * CLIP_SEGMENTS in manifest.ts). Everywhere else: max(voice-over + 0.6 s, the script minimum).
 * Never shorter than voice-over + 0.6 s. Total must stay under 3:00.
 */
const LENGTH: Partial<Record<SceneId, number>> = { scene1: 41, scene2: 38, chat: 18.7 };

export const SCENES = ORDER.map((id) => {
  const a = AUDIO.find((x) => x.id === id)!;
  const natural = Math.max(a.durationSeconds + 0.6, a.minSeconds);
  const s = LENGTH[id] !== undefined ? Math.max(LENGTH[id]!, a.durationSeconds + 0.6) : natural;
  return { ...a, id, frames: Math.ceil(s * FPS) };
});

export const TOTAL_FRAMES = SCENES.reduce((s, x) => s + x.frames, 0);

export const sec = (s: number) => Math.round(s * FPS);

/** Transition length (paper wipe in/out), frames. */
export const WIPE = 8;

/** Most a recording is sped up. */
export const MAX_RATE = 1.3;
