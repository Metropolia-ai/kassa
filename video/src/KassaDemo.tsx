import React from "react";
import { Audio, Series, staticFile } from "remotion";
import { Paper, PaperWipe } from "./components";
import type { DemoProps } from "./manifest";
import { SCENES, type SceneId } from "./timeline";
import { Intro } from "./scenes/Intro";
import { Rules } from "./scenes/Rules";
import { Scene1, Scene2, Scene3 } from "./scenes/Split";
import { Chat } from "./scenes/Chat";
import { Closing } from "./scenes/Closing";

const BODY: Record<SceneId, React.FC<DemoProps & { frames: number }>> = {
  intro: Intro, rules: Rules, scene1: Scene1, scene2: Scene2, scene3: Scene3, chat: Chat, closing: Closing,
};

export const KassaDemo: React.FC<DemoProps> = (props) => (
  <Paper>
    <Series>
      {SCENES.map((sc, i) => {
        const Body = BODY[sc.id];
        return (
          <Series.Sequence key={sc.id} durationInFrames={sc.frames} name={sc.id}>
            <Paper>
              <Body {...props} frames={sc.frames} />
              <PaperWipe frames={sc.frames} wipeIn={i > 0} wipeOut={i < SCENES.length - 1} />
            </Paper>
            <Audio src={staticFile(sc.file)} />
          </Series.Sequence>
        );
      })}
    </Series>
  </Paper>
);
