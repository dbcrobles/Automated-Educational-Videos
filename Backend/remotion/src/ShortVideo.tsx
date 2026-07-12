import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { Captions } from "./Captions";
import { ComplianceOverlay } from "./ComplianceOverlay";

const ZOOM_AMT: Record<string, number> = {
  rapid: 0,
  standard: 0.04,
  slow_pan: 0.08,
};

const KenBurnsScene: React.FC<{
  src: string;
  durationInFrames: number;
  sceneIndex: number;
  pacingStyle: string;
}> = ({ src, durationInFrames, sceneIndex, pacingStyle }) => {
  const frame = useCurrentFrame();
  const zoomAmt = ZOOM_AMT[pacingStyle] ?? 0.04;
  const scale = interpolate(
    frame,
    [0, durationInFrames],
    sceneIndex % 2 === 0 ? [1, 1 + zoomAmt] : [1 + zoomAmt, 1]
  );

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${scale})` }}>
        <OffthreadVideo src={staticFile(src)} muted />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const ShortVideo: React.FC<{
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  intro: { src: string; durationInFrames: number } | null;
  scenes: {
    src: string;
    durationInFrames: number;
    sceneIndex: number;
    pacingStyle: string;
    transitionAfter: { type: string; durationInFrames: number } | null;
  }[];
  voiceoverSrc: string;
  captions: { word: string; startFrame: number; endFrame: number }[];
  music: { src: string; volumeDb: number; fadeOutSec: number } | null;
  compliance: { text: string; fullDuration: boolean };
  accentColor: string;
}> = ({
  fps,
  durationInFrames,
  intro,
  scenes,
  voiceoverSrc,
  captions,
  music,
  compliance,
  accentColor,
}) => {
  const introOffset = intro?.durationInFrames ?? 0;

  const musicVolume = (f: number) => {
    if (!music) return 0;
    const base = Math.pow(10, music.volumeDb / 20);
    const fadeStart = durationInFrames - music.fadeOutSec * fps;
    return f < fadeStart
      ? base
      : base * Math.max(0, (durationInFrames - f) / (music.fadeOutSec * fps));
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {music && (
        <Audio src={staticFile(music.src)} loop volume={(f) => musicVolume(f)} />
      )}

      {intro && (
        <Sequence from={0} durationInFrames={intro.durationInFrames}>
          <OffthreadVideo src={staticFile(intro.src)} />
        </Sequence>
      )}

      <Sequence from={introOffset}>
        <Audio src={staticFile(voiceoverSrc)} />

        <TransitionSeries>
          {scenes.map((scene, i) => {
            const isLast = i === scenes.length - 1;
            const trans = scene.transitionAfter;
            const paddedDuration = isLast
              ? scene.durationInFrames
              : scene.durationInFrames + (trans?.durationInFrames ?? 0);

            return (
              <React.Fragment key={i}>
                <TransitionSeries.Sequence durationInFrames={paddedDuration}>
                  <KenBurnsScene
                    src={scene.src}
                    durationInFrames={scene.durationInFrames}
                    sceneIndex={scene.sceneIndex}
                    pacingStyle={scene.pacingStyle}
                  />
                </TransitionSeries.Sequence>
                {!isLast && trans && (
                  <TransitionSeries.Transition
                    presentation={trans.type === "whip_pan" ? slide() : fade()}
                    timing={linearTiming({ durationInFrames: trans.durationInFrames })}
                  />
                )}
              </React.Fragment>
            );
          })}
        </TransitionSeries>

        <Captions captions={captions} accentColor={accentColor} fps={fps} />
      </Sequence>

      <ComplianceOverlay
        text={compliance.text}
        fullDuration={compliance.fullDuration}
        fps={fps}
        totalFrames={durationInFrames}
      />
    </AbsoluteFill>
  );
};