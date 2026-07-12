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
import { ChartOverlay, ChartSpec } from "./ChartOverlay";

const ZOOM_AMT: Record<string, number> = {
  rapid: 0,
  standard: 0.04,
  slow_pan: 0.08,
};

type SceneProps = {
  clips: string[];
  durationInFrames: number;
  sceneIndex: number;
  pacingStyle: string;
  cameraMovement: string;
  colorGradeHint: string;
  audioEmphasis: string;
  soundEffect: "none" | "impact" | "whoosh" | "chime";
  captionStyle: string;
  chart: ChartSpec | null;
  mediaDisplayMode: string | null;
  sourceAudio: boolean;
  sourceCredit: string | null;
  transitionAfter: { type: string; durationInFrames: number } | null;
};

const DirectedClip: React.FC<{
  src: string;
  durationInFrames: number;
  sceneIndex: number;
  pacingStyle: string;
  cameraMovement: string;
  sourceAudio: boolean;
  sourceAudioEndFrame: number;
  fadeIn: boolean;
  fadeOut: boolean;
}> = ({ src, durationInFrames, sceneIndex, pacingStyle, cameraMovement, sourceAudio, sourceAudioEndFrame, fadeIn, fadeOut }) => {
  const frame = useCurrentFrame();
  const zoomAmt = ZOOM_AMT[pacingStyle] ?? 0.04;
  const directedZoom = Math.max(zoomAmt, 0.04);
  const progress = Math.min(1, frame / Math.max(1, durationInFrames));
  const scale = cameraMovement === "static"
    ? 1
    : cameraMovement === "shake"
      ? 1.03
    : cameraMovement === "slow_zoom_out"
      ? 1 + directedZoom * (1 - progress)
      : 1 + directedZoom * progress;
  const shake = cameraMovement === "shake" ? Math.sin(frame * 2.6) * 7 : 0;
  const fadeFrames = 6;
  const opacityIn = fadeIn ? interpolate(frame, [0, fadeFrames], [0, 1], { extrapolateRight: "clamp" }) : 1;
  const opacityOut = fadeOut
    ? interpolate(frame, [durationInFrames - fadeFrames, durationInFrames], [1, 0], { extrapolateLeft: "clamp" })
    : 1;

  return (
    <AbsoluteFill style={{ opacity: Math.min(opacityIn, opacityOut) }}>
      <AbsoluteFill style={{ transform: `translateX(${shake}px) scale(${scale})` }}>
        <OffthreadVideo
          src={staticFile(src)}
          muted={!sourceAudio}
          volume={(f) => sourceAudio && f < sourceAudioEndFrame ? 1 : 0}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const DirectedScene: React.FC<SceneProps & { containerDurationInFrames: number }> = (scene) => {
  const fadeFrames = 6;
  const clipDuration = Math.ceil(scene.containerDurationInFrames / scene.clips.length);
  const pictureInPicture = scene.mediaDisplayMode === "picture_in_picture";

  return (
    <AbsoluteFill style={pictureInPicture ? { background: "#08131F" } : undefined}>
      {scene.clips.map((src, i) => {
        const from = Math.max(0, i * clipDuration - (i > 0 ? fadeFrames : 0));
        const until = Math.min(
          scene.containerDurationInFrames,
          (i + 1) * clipDuration + (i < scene.clips.length - 1 ? fadeFrames : 0)
        );
        return (
          <Sequence
            key={src}
            from={from}
            durationInFrames={Math.max(1, until - from)}
            style={pictureInPicture ? { inset: "16% 7% 30%", borderRadius: 28, overflow: "hidden", boxShadow: "0 14px 50px rgba(0,0,0,0.5)" } : undefined}
          >
            <DirectedClip
              src={src}
              durationInFrames={Math.max(1, until - from)}
              sceneIndex={scene.sceneIndex}
              pacingStyle={scene.pacingStyle}
              cameraMovement={scene.cameraMovement}
              sourceAudio={scene.sourceAudio && i === 0}
              sourceAudioEndFrame={scene.durationInFrames}
              fadeIn={i > 0}
              fadeOut={i < scene.clips.length - 1}
            />
          </Sequence>
        );
      })}
      {scene.chart && <ChartOverlay chart={scene.chart} durationInFrames={scene.durationInFrames} />}
      {scene.soundEffect !== "none" && (
        <Audio src={staticFile(`sfx/${scene.soundEffect}.wav`)} volume={0.22} />
      )}
      {scene.sourceCredit && (
        <div style={{ position: "absolute", left: 34, bottom: 34, zIndex: 2, padding: "10px 16px", borderRadius: 10, background: "rgba(0,0,0,0.72)", color: "white", fontFamily: "sans-serif", fontSize: 22 }}>
          Source: {scene.sourceCredit}
        </div>
      )}
    </AbsoluteFill>
  );
};

export const ShortVideo: React.FC<{
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  intro: { src: string; durationInFrames: number } | null;
  scenes: SceneProps[];
  voiceoverSrc: string;
  captions: { word: string; startFrame: number; endFrame: number; style: string }[];
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
    const contentFrame = Math.max(0, f - introOffset);
    let sceneStart = 0;
    const scene = scenes.find((candidate) => {
      const inScene = contentFrame >= sceneStart && contentFrame < sceneStart + candidate.durationInFrames;
      sceneStart += candidate.durationInFrames;
      return inScene;
    });
    if (scene?.sourceAudio) return 0;
    const emphasisDb = scene?.audioEmphasis === "music_pedestal"
      ? -18
      : scene?.audioEmphasis === "sfx_drop" ? -30 : music.volumeDb;
    const base = scene?.audioEmphasis === "voiceonly" ? 0 : Math.pow(10, emphasisDb / 20);
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
                  <DirectedScene {...scene} containerDurationInFrames={paddedDuration} />
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