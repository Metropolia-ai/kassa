import React from "react";
import { useCurrentFrame } from "remotion";
import { Caption, ClipStage, STD, fadeIn } from "../components";
import { eventsOf, planClip, type DemoProps } from "../manifest";
import { Marks, marksFor } from "../overlays";
import { C } from "../theme";

export const Chat: React.FC<DemoProps & { frames: number }> = ({ manifest, media, frames }) => {
  const f = useCurrentFrame();
  const events = eventsOf(manifest, "chat");
  const plan = planClip("chat", media.chat, events, frames);
  const marks = marksFor(events, plan, false, ["answer"]);
  return (
    <>
      <ClipStage rect={STD} plan={plan} panes={[{ label: "Frappua · Erik's Kassa · Ask Kassa", color: C.green }]} opacity={fadeIn(f, 0, 8)}>
        {(s) => <Marks marks={marks} s={s} areaW={STD.w} areaH={STD.h} />}
      </ClipStage>
      <Caption text="Every decision, with its reason" />
    </>
  );
};
