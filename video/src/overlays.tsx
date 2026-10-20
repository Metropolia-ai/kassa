import React from "react";
import { Callout, InkDot, type Zoom } from "./components";
import type { Box, ClipEvent, ClipPlan } from "./manifest";
import { C } from "./theme";
import { sec } from "./timeline";

/**
 * Manifest events -> callouts. Labels are fixed words chosen by the event text (never the raw
 * text). Positions: the event's optional `box`, else the click point, else a default box measured
 * on the recordings (1920x1080 clip coordinates).
 */
export type Mark =
  | { kind: "callout"; at: number; box: Box; label: string; color?: string }
  | { kind: "dot"; at: number; x: number; y: number };

const CALLOUT = sec(3.2); // how long a callout stays
const LEAD = sec(0.6); // click callouts start this much before the click, so the circle is there when it happens

const side = (e: ClipEvent) => (/\(left\)/.test(e.what) ? 0 : 960);
const around = (x: number, y: number, w: number, h: number): Box => [Math.max(4, Math.min(1916 - w, x - w / 2)), Math.max(4, Math.min(1076 - h, y - h / 2)), w, h];
const toastBox = (e: ClipEvent): Box => [side(e) + 22, 984, 466, 78];
const rowBox = (e: ClipEvent, y: number): Box => [side(e) + 18, y - 38, 924, 76];

type Rule = { re: RegExp; label: string; click?: boolean; color?: string; box: (e: ClipEvent, scene: string) => Box | null };

// Row heights of the bills that change, measured on the recordings.
const ROW_Y: Record<string, Record<string, number>> = {
  scene3: { refused: 504, withdrawn: 710, resent: 710 },
  scene2: { withdrawn: 544 },
};

const RULES: Rule[] = [
  { re: /click.*Send invoice/, label: "Mika presses Send", click: true, box: (e) => around(e.x!, e.y!, 190, 74) },
  { re: /toast.*New bill/, label: "the invoice arrives", box: toastBox },
  { re: /click bill row|drawer open/, label: "Erik opens the bill", click: true, box: (e) => (e.x !== undefined ? rowBox(e, e.y!) : null) },
  { re: /card under|card appears/, label: "Erik's decision", color: C.amber, box: () => [978, 266, 924, 232] },
  { re: /click Pay 1/, label: "one click", click: true, box: (e) => around(e.x!, e.y!, 330, 70) },
  { re: /re-sent/, label: "re-sent by their system", box: (e, sc) => (/toast/.test(e.what) ? toastBox(e) : rowBox(e, ROW_Y[sc]?.resent ?? 700)) },
  { re: /Refused/, label: "refused", box: (e, sc) => rowBox(e, ROW_Y[sc]?.refused ?? 504) },
  { re: /Withdrawn/, label: "withdrawn", box: (e, sc) => rowBox(e, ROW_Y[sc]?.withdrawn ?? 600) },
  { re: /answer appears/, label: "the answer", color: C.green, box: () => [1556, 200, 354, 520] },
];

export type Marked = { marks: Mark[]; zooms: Zoom[] };

export function marksFor(scene: string, events: ClipEvent[], plan: ClipPlan): Marked {
  const marks: Mark[] = [];
  const zooms: Zoom[] = [];
  const shown: Record<string, number> = {};
  for (const e of events) {
    const at = plan.at(e.t);
    if (at === null) continue; // cut out of the scene
    const hasXY = e.x !== undefined && e.y !== undefined;
    if (/^click/.test(e.what) && hasXY) marks.push({ kind: "dot", at, x: e.x!, y: e.y! });
    if (/^message:/.test(e.what)) continue; // only advances the step chips
    const rule = RULES.find((r) => r.re.test(e.what));
    if (!rule) continue;
    if (shown[rule.label] !== undefined && at - shown[rule.label] < sec(1.5)) continue; // same thing twice (click + drawer open)
    const box = e.box ?? rule.box(e, scene);
    if (!box) continue;
    shown[rule.label] = at;
    const start = Math.max(0, rule.click ? at - LEAD : at);
    marks.push({ kind: "callout", at: start, box, label: rule.label, color: rule.color });
    // focus move on callouts that have a point (clicks), and on the chat answer
    const zx = hasXY ? e.x! : rule.label === "the answer" ? box[0] + box[2] / 2 : undefined;
    const zy = hasXY ? e.y! : rule.label === "the answer" ? box[1] + box[3] / 2 : undefined;
    if (zx !== undefined && zy !== undefined) zooms.push({ at: start, until: start + CALLOUT, x: zx, y: zy, z: 1.35 });
  }
  return { marks, zooms };
}

/** While the bill drawer is open on the right window: hold 1.25x on its lower part (the messages). */
export function drawerZoom(events: ClipEvent[], plan: ClipPlan, sceneFrames: number): Zoom[] {
  const out: Zoom[] = [];
  const opens = events.filter((e) => /drawer open/.test(e.what));
  for (const o of opens) {
    const at = plan.at(o.t);
    if (at === null) continue;
    const close = events.find((e) => e.t > o.t && /drawer closed/.test(e.what));
    const until = close ? plan.at(close.t) ?? sceneFrames : sceneFrames;
    out.push({ at, until: Math.min(until, sceneFrames), x: 1440, y: 1080, z: 1.25 });
  }
  return out;
}

export const Marks: React.FC<{ marks: Mark[]; s: number; areaW: number; areaH: number }> = ({ marks, s, areaW, areaH }) => (
  <>
    {marks.map((m, i) =>
      m.kind === "dot" ? (
        <InkDot key={i} at={m.at} x={m.x} y={m.y} s={s} />
      ) : (
        <Callout key={i} at={m.at} box={m.box} label={m.label} s={s} color={m.color} areaW={areaW} areaH={areaH} dur={CALLOUT} />
      ),
    )}
  </>
);

/** Fixed step words per scene, lit at the matching manifest event. */
export const STEPS: Record<string, { word: string; re: RegExp }[]> = {
  scene1: [
    { word: "asked", re: /asked/ },
    { word: "explained", re: /message: explained/ },
    { word: "agreed", re: /message: agreed/ },
    { word: "paid", re: /message: paid/ },
    { word: "confirmed", re: /message: confirmed|Settled/ },
  ],
  scene2: [
    { word: "checked", re: /Checking|Being checked/ },
    { word: "your turn", re: /card under|card appears/ },
    { word: "one click", re: /click Pay/ },
    { word: "reissued", re: /reissued/ },
    { word: "paid", re: /Settled in|Paid/ },
  ],
  scene3: [
    { word: "arrives", re: /toast.*re-sent|Another bill/ },
    { word: "asked", re: /asked/ },
    { word: "withdrawn", re: /Withdrawn|withdrawn/ },
  ],
};

export function stepsFor(scene: string, events: ClipEvent[], plan: ClipPlan): { word: string; at: number | null }[] {
  const list = STEPS[scene] ?? [];
  let after = -Infinity; // each step after the previous one
  return list.map((st) => {
    const e = events.find((x) => x.t >= after && st.re.test(x.what) && plan.atOrStart(x.t) !== null);
    if (e) after = e.t;
    return { word: st.word, at: e ? plan.atOrStart(e.t) : null };
  });
}
