import { Composition } from "remotion";
import { ShortVideo } from "./ShortVideo";
import { z } from "zod";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ShortVideo"
      component={ShortVideo}
      schema={z.object({
        fps: z.number(),
        width: z.number(),
        height: z.number(),
        durationInFrames: z.number(),
        intro: z
          .object({
            src: z.string(),
            durationInFrames: z.number(),
          })
          .nullable(),
        scenes: z.array(
          z.object({
            src: z.string(),
            durationInFrames: z.number(),
            sceneIndex: z.number(),
            pacingStyle: z.string(),
            transitionAfter: z
              .object({
                type: z.string(),
                durationInFrames: z.number(),
              })
              .nullable(),
          })
        ),
        voiceoverSrc: z.string(),
        captions: z.array(
          z.object({
            word: z.string(),
            startFrame: z.number(),
            endFrame: z.number(),
          })
        ),
        music: z
          .object({
            src: z.string(),
            volumeDb: z.number(),
            fadeOutSec: z.number(),
          })
          .nullable(),
        compliance: z.object({
          text: z.string(),
          fullDuration: z.boolean(),
        }),
        accentColor: z.string(),
      })}
      defaultProps={{
        fps: 30,
        width: 1080,
        height: 1920,
        durationInFrames: 300,
        intro: null,
        scenes: [],
        voiceoverSrc: "",
        captions: [],
        music: null,
        compliance: { text: "AI-Assisted", fullDuration: false },
        accentColor: "#FFD447",
      }}
      calculateMetadata={({ props }) => ({
        fps: props.fps,
        width: props.width,
        height: props.height,
        durationInFrames: props.durationInFrames,
      })}
    />
  );
};