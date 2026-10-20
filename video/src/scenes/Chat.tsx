import React from "react";
import { useCurrentFrame } from "remotion";
import { Caption, ClipStage, FULL, fadeIn } from "../components";
import { eventsOf, planPieces, segmentsFor, type DemoProps } from "../manifest";
import { Marks, marksFor } from "../overlays";
import { C } from "../theme";
import { FPS } from "../timeline";

export const Chat: React.FC<DemoProps & { frames: number }> = ({ manifest, media, frames }) => {
  const f = useCurrentFrame();
  const events = eventsOf(manifest, "chat");
  const plan = planPieces("chat", media.chat, segmentsFor("chat", events, media.chat, frames / FPS), frames);
  const { marks, zooms } = marksFor("chat", events, plan);
  // hold the zoom on the answer until the Activity tab is clicked
  const act = events.find((e) => /click Activity/.test(e.what));
  const actAt = act ? plan.at(act.t) : null;
  const z = zooms.map((zm) => (actAt !== null ? { ...zm, until: Math.max(zm.until, actAt - 14) } : zm));
  return (
    <>
      <ClipStage rect={FULL} plan={plan} panes={[{ label: "Frappua · Erik's Kassa · Ask Kassa", color: C.green }]} opacity={fadeIn(f, 0, 8)} zooms={z}>
        {(s) => <Marks marks={marks} s={s} areaW={FULL.w} areaH={FULL.h} />}
      </ClipStage>
      <Caption text="Every decision, with its reason" />
    </>
  );
};
