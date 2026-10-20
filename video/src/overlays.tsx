import React from "react";
import { Callout, InkDot } from "./components";
import type { Box, ClipEvent, ClipPlan } from "./manifest";
import { C } from "./theme";

/**
 * Turns manifest events into callouts. Positions come from the event's optional `box` [x,y,w,h]
 * or `x`,`y` (clip coordinates, 1920x1080); otherwise from defaults that match the Kassa layout
 * (toast bottom-left of a window, drawer centred in a window, "Ask Kassa" column on the right).
 */
export type Mark =
  | { kind: "callout"; at: number; box: Box; label?: string; color?: string }
  | { kind: "dot"; at: number; x: number; y: number };

const lc = (e: ClipEvent) => e.what.toLowerCase();
export const has = (e: ClipEvent, re: RegExp) => re.test(lc(e));

function halfX(e: ClipEvent, split: boolean): number {
  if (!split) return 0;
  if (/\(left\)|left:|mika|pixelforge side/.test(lc(e))) return 0;
  if (e.x !== undefined) return e.x >= 960 ? 960 : 0;
  return 960;
}
const winW = (split: boolean) => (split ? 960 : 1920);

function around(x: number, y: number, w: number, h: number): Box {
  return [Math.max(4, Math.min(1916 - w, x - w / 2)), Math.max(4, Math.min(1076 - h, y - h / 2)), w, h];
}

export function boxFor(e: ClipEvent, kind: string, split: boolean): Box {
  if (e.box) return e.box;
  const hx = halfX(e, split);
  const ww = winW(split);
  const hasXY = e.x !== undefined && e.y !== undefined;
  switch (kind) {
    case "toast":
      return hasXY ? around(e.x!, e.y!, 480, 110) : [hx + 24, 950, 470, 100];
    case "drawer":
      return split ? [hx + 70, 30, 820, 1020] : [(ww - 820) / 2, 30, 820, 1020];
    case "row":
      return hasXY ? [hx + 30, e.y! - 34, (split ? ww : ww - 380) - 70, 68] : [hx + 30, 420, (split ? ww : ww - 380) - 70, 68];
    case "card":
      return hasXY ? around(e.x!, e.y!, Math.min(860, ww - 40), 230) : [hx + 30, 220, Math.min(880, ww - 60), 230];
    case "answer":
      return hasXY ? around(e.x!, e.y!, 360, 420) : [1550, 300, 350, 560];
    default:
      return hasXY ? around(e.x!, e.y!, 150, 84) : [hx + ww / 2 - 200, 480, 400, 120];
  }
}

const clickLabel = (e: ClipEvent) => {
  const t = e.what.replace(/^click\s*/i, "").replace(/\s*\((left|right)\)\s*/gi, " ").trim();
  if (/row/i.test(t)) return "the bill";
  return t.length > 22 ? t.slice(0, 22) + "…" : t;
};

/** Default reading of events for a scene. `wanted` lists what kinds of callout the scene shows. */
export function marksFor(events: ClipEvent[], plan: ClipPlan, split: boolean, wanted: string[]): Mark[] {
  const out: Mark[] = [];
  let drawerShown = false;
  for (const e of events) {
    const at = plan.at(e.t);
    const isClick = has(e, /^click/) && e.x !== undefined && e.y !== undefined;
    if (isClick) out.push({ kind: "dot", at, x: e.x!, y: e.y! });
    if (isClick && wanted.includes("click")) {
      const kind = has(e, /row/) ? "row" : "click";
      out.push({ kind: "callout", at, box: boxFor(e, kind, split), label: clickLabel(e) });
      continue;
    }
    if (isClick) continue;
    if (has(e, /toast/) && wanted.includes("toast")) {
      const label = e.what.replace(/^toast\s*/i, "").replace(/\s*\((left|right)\)\s*/gi, "").trim() || "new bill";
      out.push({ kind: "callout", at, box: boxFor(e, "toast", split), label: label.length > 22 ? "re-sent bill" : label });
    } else if (has(e, /^message/) && wanted.includes("drawer") && !drawerShown) {
      drawerShown = true;
      out.push({ kind: "callout", at, box: boxFor(e, "drawer", split), label: "the two bookkeepers", color: C.purple });
    } else if (has(e, /card/) && wanted.includes("card")) {
      out.push({ kind: "callout", at, box: boxFor(e, "card", split), label: "Needs you", color: C.amber });
    } else if (has(e, /refused/) && wanted.includes("refused")) {
      out.push({ kind: "callout", at, box: boxFor(e, "row", split), label: "Refused" });
    } else if (has(e, /withdrawn/) && wanted.includes("withdrawn")) {
      out.push({ kind: "callout", at, box: boxFor({ ...e, what: e.what.includes("(") ? e.what : e.what + " (left)" }, "row", split), label: "Withdrawn" });
    } else if (has(e, /answer/) && wanted.includes("answer")) {
      out.push({ kind: "callout", at, box: boxFor(e, "answer", split), label: "the answer", color: C.green });
    }
  }
  return out;
}

export const Marks: React.FC<{ marks: Mark[]; s: number; areaW: number; areaH: number }> = ({ marks, s, areaW, areaH }) => (
  <>
    {marks.map((m, i) =>
      m.kind === "dot" ? (
        <InkDot key={i} at={m.at} x={m.x} y={m.y} s={s} />
      ) : (
        <Callout key={i} at={m.at} box={m.box} label={m.label} s={s} color={m.color} areaW={areaW} areaH={areaH} />
      ),
    )}
  </>
);
