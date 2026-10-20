import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Caption, ClipStage, FULL, Pip, Stamp, clamp, fadeIn } from "../components";
import { eventsOf, planPieces, segmentsFor, type ClipEvent, type DemoProps } from "../manifest";
import { Marks, drawerZoom, marksFor, stepsFor } from "../overlays";
import { C } from "../theme";
import { FPS, sec } from "../timeline";

const PANES = [
  { label: "Pixelforge Oy · Mika's Kassa", color: C.purple },
  { label: "Frappua · Erik's Kassa", color: C.green },
];
const RIGHT_CX = FULL.x + FULL.w * 0.75;
const LEFT_CX = FULL.x + FULL.w * 0.25;
const MID_Y = FULL.y + FULL.h * 0.5;
const PIP_FRAMES = sec(2.5) + 8;

const clampAt = (at: number, frames: number) => Math.max(sec(0.5), Math.min(at, frames - sec(2.2)));
const find = (ev: ClipEvent[], re: RegExp) => ev.find((e) => re.test(e.what));
const secondsIn = (e: ClipEvent | undefined) => e?.what.match(/in (\d+) s\b/)?.[1];

/** Fixed step words; each lights up at its manifest event. Bottom left, under the caption. */
const Steps: React.FC<{ steps: { at: number | null; word: string }[] }> = ({ steps }) => {
  const f = useCurrentFrame();
  if (!steps.length) return null;
  return (
    <div style={{ position: "absolute", left: 56, bottom: 22, display: "flex", gap: 8, alignItems: "center", zIndex: 45 }}>
      {steps.map((s, i) => {
        const on = s.at === null ? 0 : interpolate(f, [s.at, s.at + 6], [0, 1], clamp);
        const lit = on > 0.5;
        return (
          <React.Fragment key={i}>
            {i > 0 ? <span style={{ width: 18, height: 3, background: lit ? C.purple : C.pencil, opacity: lit ? 1 : 0.5 }} /> : null}
            <span style={{ fontSize: 28, fontWeight: 700, padding: "4px 16px 6px", borderRadius: 999, border: `2px solid ${lit ? C.purple : C.rule}`, color: lit ? C.purple : C.pencil, background: lit ? "#ECE4F5" : C.sheet, boxShadow: `0 3px 10px ${C.shade}` }}>
              {s.word}
            </span>
          </React.Fragment>
        );
      })}
    </div>
  );
};

type Ctx = { events: ClipEvent[]; at: (t: number) => number | null };

const SplitBase: React.FC<DemoProps & { frames: number; clip: "scene1" | "scene2" | "scene3"; caption: string; children: (ctx: Ctx) => React.ReactNode }> = ({
  manifest, media, frames, clip, caption, children,
}) => {
  const f = useCurrentFrame();
  const events = eventsOf(manifest, clip);
  const plan = planPieces(clip, media[clip], segmentsFor(clip, events, media[clip], frames / FPS), frames);
  const { marks, zooms } = marksFor(clip, events, plan);
  const allZooms = [...zooms, ...drawerZoom(events, plan, frames)];
  return (
    <>
      <ClipStage rect={FULL} plan={plan} split panes={PANES} opacity={fadeIn(f, 0, 8)} zooms={allZooms}>
        {(s) => <Marks marks={marks} s={s} areaW={FULL.w} areaH={FULL.h} />}
      </ClipStage>
      {children({ events, at: plan.at })}
      <Caption text={caption} bottom={78} />
      <Steps steps={stepsFor(clip, events, plan)} />
    </>
  );
};

export const Scene1: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} clip="scene1" caption="Two bookkeepers, one invoice">
    {({ events, at }) => {
      const fin = find(events, /outcome|Settled by/) ?? events[events.length - 1];
      const num = secondsIn(fin) ?? events.map(secondsIn).find(Boolean) ?? "14";
      const stampAt = clampAt((fin ? at(fin.t) : null) ?? sec(31.3), p.frames);
      return (
        <>
          <Stamp at={stampAt} text="Settled" sub={`${num} s · 0 PEOPLE`} color={C.green} size={120} x={LEFT_CX + 20} y={FULL.y + 270} />
          <Pip at={p.frames - PIP_FRAMES} info={p.media["paypal-paid"]} id="paypal-paid" cx={RIGHT_CX - 20} cy={MID_Y} w={900} label="PayPal sandbox · invoice paid" />
        </>
      );
    }}
  </SplitBase>
);

export const Scene3: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} clip="scene3" caption="A duplicate, caught">
    {({ events, at }) => {
      const w = [...events].reverse().find((e) => /Withdrawn/.test(e.what));
      const stampAt = clampAt((w ? at(w.t) : null) ?? sec(13.3), p.frames);
      return (
        <>
          <Stamp at={stampAt} text="Withdrawn" sub="0 PEOPLE" color={C.red} size={110} x={RIGHT_CX} y={FULL.y + FULL.h * 0.76} />
          <Pip at={p.frames - PIP_FRAMES} info={p.media["paypal-cancelled"]} id="paypal-cancelled" cx={LEFT_CX + 20} cy={MID_Y - 40} w={900} label="PayPal sandbox · invoice cancelled" />
        </>
      );
    }}
  </SplitBase>
);

export const Scene2: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} clip="scene2" caption="People only when it matters">
    {({ events, at }) => {
      const card = find(events, /card under|card appears/);
      const paid = find(events, /Settled in/) ?? [...events].reverse().find((e) => /Paid/.test(e.what));
      const turnAt = clampAt((card ? at(card.t) : null) ?? sec(11.0), p.frames);
      const paidAt = Math.max(turnAt + sec(3), clampAt((paid ? at(paid.t) : null) ?? p.frames - sec(5), p.frames));
      return (
        <>
          <Stamp at={turnAt} text="Your turn" color={C.amber} size={92} x={RIGHT_CX} y={FULL.y + FULL.h * 0.74} hideAt={turnAt + sec(4)} />
          <Stamp at={paidAt} text="Paid" sub="1 decision by a person" color={C.green} size={130} x={LEFT_CX + 40} y={MID_Y - 60} />
        </>
      );
    }}
  </SplitBase>
);
