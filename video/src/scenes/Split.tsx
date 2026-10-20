import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Caption, ClipStage, Pip, STD, Stamp, clamp, fadeIn } from "../components";
import { eventsOf, planClip, type ClipEvent, type DemoProps } from "../manifest";
import { Marks, has, marksFor } from "../overlays";
import { C } from "../theme";
import { sec } from "../timeline";

const PANES = [
  { label: "Pixelforge Oy · Mika's Kassa", color: C.purple },
  { label: "Frappua · Erik's Kassa", color: C.green },
];
const RIGHT_CX = STD.x + STD.w * 0.75;
const LEFT_CX = STD.x + STD.w * 0.25;
const MID_Y = STD.y + STD.h * 0.5;
const PIP_FRAMES = sec(2.5) + 8;

const clampAt = (at: number, frames: number) => Math.max(sec(0.5), Math.min(at, frames - sec(2.2)));
const find = (ev: ClipEvent[], re: RegExp) => ev.find((e) => has(e, re));
const findLast = (ev: ClipEvent[], re: RegExp) => [...ev].reverse().find((e) => has(e, re));

/** Message steps of the drawer ("message: asked" ...) as chips that light up, bottom right. */
const Steps: React.FC<{ steps: { at: number; word: string }[] }> = ({ steps }) => {
  const f = useCurrentFrame();
  if (!steps.length) return null;
  return (
    <div style={{ position: "absolute", right: 56, bottom: 40, display: "flex", gap: 10, alignItems: "center" }}>
      {steps.map((s, i) => {
        const on = interpolate(f, [s.at, s.at + 6], [0, 1], clamp);
        return (
          <React.Fragment key={i}>
            {i > 0 ? <span style={{ width: 22, height: 3, background: on > 0.5 ? C.purple : C.rule }} /> : null}
            <span style={{ fontSize: 30, fontWeight: 700, padding: "6px 16px 8px", borderRadius: 999, border: `2px solid ${on > 0.5 ? C.purple : C.rule}`, color: on > 0.5 ? C.purple : C.pencil, background: on > 0.5 ? "#ECE4F5" : C.sheet, opacity: 0.55 + 0.45 * on }}>
              {s.word}
            </span>
          </React.Fragment>
        );
      })}
    </div>
  );
};

type Cfg = { clip: "scene1" | "scene2" | "scene3"; caption: string };

const SplitBase: React.FC<DemoProps & { frames: number; cfg: Cfg; wanted: string[]; children: (ctx: { events: ClipEvent[]; at: (t: number) => number }) => React.ReactNode; steps?: boolean }> = ({
  manifest, media, frames, cfg, wanted, children, steps,
}) => {
  const f = useCurrentFrame();
  const events = eventsOf(manifest, cfg.clip);
  const plan = planClip(cfg.clip, media[cfg.clip], events, frames);
  const marks = marksFor(events, plan, true, wanted);
  const stepList = steps
    ? events.filter((e) => has(e, /^message/)).map((e) => ({ at: plan.at(e.t), word: (e.what.split(":")[1] ?? e.what).split(",")[0].trim() }))
    : [];
  return (
    <>
      <ClipStage rect={STD} plan={plan} split panes={PANES} opacity={fadeIn(f, 0, 8)}>
        {(s) => <Marks marks={marks} s={s} areaW={STD.w} areaH={STD.h} />}
      </ClipStage>
      {children({ events, at: plan.at })}
      <Caption text={cfg.caption} />
      <Steps steps={stepList} />
    </>
  );
};

export const Scene1: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} cfg={{ clip: "scene1", caption: "Two bookkeepers, one invoice" }} wanted={["click", "toast", "drawer"]} steps>
    {({ events, at }) => {
      const fin = find(events, /outcome|settled/) ?? events[events.length - 1];
      const num = events.map((e) => e.what.match(/(\d+)\s*s\b/)).find(Boolean)?.[1] ?? "14";
      const stampAt = clampAt(fin ? at(fin.t) : sec(31.3), p.frames);
      return (
        <>
          <Stamp at={stampAt} text="Settled" sub={`${num} s · 0 PEOPLE`} color={C.green} size={120} x={RIGHT_CX} y={MID_Y - 40} />
          <Pip at={p.frames - PIP_FRAMES} info={p.media["paypal-paid"]} id="paypal-paid" cx={LEFT_CX} cy={MID_Y} w={700} label="PayPal sandbox · invoice paid" />
        </>
      );
    }}
  </SplitBase>
);

export const Scene2: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} cfg={{ clip: "scene2", caption: "People only when it matters" }} wanted={["card"]}>
    {({ events, at }) => {
      const card = find(events, /card/);
      const paid = findLast(events, /paid/);
      const turnAt = clampAt(card ? at(card.t) : sec(11.0), p.frames);
      const paidAt = Math.max(turnAt + sec(3), clampAt(paid ? at(paid.t) : p.frames - sec(5), p.frames));
      return (
        <>
          <Stamp at={turnAt} text="Your turn" color={C.amber} size={92} x={RIGHT_CX} y={STD.y + STD.h * 0.72} hideAt={turnAt + sec(4)} />
          <Stamp at={paidAt} text="Paid" color={C.green} size={140} x={RIGHT_CX} y={MID_Y} />
        </>
      );
    }}
  </SplitBase>
);

export const Scene3: React.FC<DemoProps & { frames: number }> = (p) => (
  <SplitBase {...p} cfg={{ clip: "scene3", caption: "A duplicate, caught" }} wanted={["toast", "refused", "withdrawn"]}>
    {({ events, at }) => {
      const w = findLast(events, /withdrawn/) ?? events[events.length - 1];
      const stampAt = clampAt(w ? at(w.t) : sec(13.3), p.frames);
      return (
        <>
          <Stamp at={stampAt} text="Withdrawn" sub="0 PEOPLE" color={C.red} size={110} x={RIGHT_CX} y={MID_Y - 40} />
          <Pip at={p.frames - PIP_FRAMES} info={p.media["paypal-cancelled"]} id="paypal-cancelled" cx={LEFT_CX} cy={MID_Y} w={700} label="PayPal sandbox · invoice cancelled" />
        </>
      );
    }}
  </SplitBase>
);
