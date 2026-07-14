/**
 * LongVideo — Phase 6 long-form composition (1920×1080, 30fps).
 *
 * Props mirror Backend/assets/{id}/beats.json exactly as written by Phases
 * 4–5 (realization keys included), plus voiceoverSrc / captions / music that
 * node4 adds at render time. It never requires fields those phases don't
 * produce.
 *
 * Owner Studio workflow: `npm run dev` → open LongVideo → paste a real
 * video's beats.json contents into the `beats` prop (or edit
 * Backend/assets/{id}/beats.json directly); the pipeline renders from that
 * same file.
 */
import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";
import { Captions } from "./Captions";
import { ChartOverlay, LANDSCAPE_CHART_SIZES } from "./ChartOverlay";
import { getAnimation } from "./animations";

// ─── Schema: mirrors beats.json ──────────────────────────────────────────────

const chartSchema = z.object({
  chart_type: z.enum(["pie", "bar", "line"]),
  display_mode: z.enum(["overlay", "full_screen"]),
  title: z.string(),
  unit: z.string(),
  points: z.array(z.object({ label: z.string(), value: z.number() })),
  highlight: z.string(),
  source_url: z.string(),
  source_label: z.string(),
});

const elementSchema = z.object({
  kind: z.string(),
  role: z.enum(["primary", "overlay"]),
  ref: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  start_offset_sec: z.number().default(0),
  duration_sec: z.number().nullable().optional(),
  position: z.string().default("full"),
  animation: z.string().nullable().optional(),
  realized: z.boolean().optional(),
  src: z.string().nullable().optional(),
  candidates: z.array(z.string()).optional(),
  chart: chartSchema.nullable().optional(),
});

const beatSchema = z.object({
  section: z.string(),
  order: z.number(),
  spoken_text: z.string(),
  target_duration_sec: z.number(),
  hook_label: z.string(),
  music_cue: z.string(),
  start: z.number().optional(),
  end: z.number().optional(),
  elements: z.array(elementSchema),
});

export const longVideoSchema = z.object({
  fps: z.number().default(30),
  width: z.number().default(1920),
  height: z.number().default(1080),
  assetBase: z.string(), // staticFile prefix — node4's per-video public symlink
  beats: z.array(beatSchema),
  voiceoverSrc: z.string(),
  captions: z.array(z.object({ word: z.string(), start: z.number(), end: z.number() })),
  music: z
    .object({ src: z.string(), volumeDb: z.number(), fadeOutSec: z.number() })
    .nullable(),
  accentColor: z.string().default("#FFD447"),
});

export type LongVideoProps = z.infer<typeof longVideoSchema>;
type BeatT = z.infer<typeof beatSchema>;
type ElementT = z.infer<typeof elementSchema>;

// ─── Timing ──────────────────────────────────────────────────────────────────

/** Continuous beat windows in seconds: narration start→next start when
 * aligned (Phase 5), cumulative target durations otherwise (Studio preview
 * of a pre-narration beats.json). */
export const beatWindowsSec = (beats: BeatT[]): { from: number; until: number }[] => {
  const aligned =
    beats.length > 0 &&
    beats.every((b) => typeof b.start === "number" && typeof b.end === "number");
  if (aligned) {
    const lastEnd = (beats[beats.length - 1].end as number) + 0.4;
    return beats.map((b, i) => ({
      from: i === 0 ? 0 : (b.start as number),
      until: i + 1 < beats.length ? (beats[i + 1].start as number) : lastEnd,
    }));
  }
  let cursor = 0;
  return beats.map((b) => {
    const from = cursor;
    cursor += b.target_duration_sec;
    return { from, until: cursor };
  });
};

export const calculateLongVideoMetadata = ({ props }: { props: LongVideoProps }) => {
  const windows = beatWindowsSec(props.beats);
  const total = windows.length > 0 ? windows[windows.length - 1].until : 10;
  return {
    fps: props.fps,
    width: props.width,
    height: props.height,
    durationInFrames: Math.max(1, Math.round(total * props.fps)),
  };
};

// ─── Layers ──────────────────────────────────────────────────────────────────

const POSITION_STYLE: Record<string, React.CSSProperties> = {
  full: { inset: 0 },
  lower_third: { left: "4%", right: "4%", bottom: "5%", height: "26%" },
  upper_third: { left: "4%", right: "4%", top: "5%", height: "26%" },
  center: { left: "22%", right: "22%", top: "28%", bottom: "28%" },
  top_left: { left: "3%", top: "5%", width: "28%", height: "34%" },
  top_right: { right: "3%", top: "5%", width: "28%", height: "34%" },
  bottom_left: { left: "3%", bottom: "7%", width: "28%", height: "34%" },
  bottom_right: { right: "3%", bottom: "7%", width: "28%", height: "34%" },
};

const isVideoFile = (src: string) => /\.(mp4|mov|webm|m4v)$/i.test(src);

const OverlayMedia: React.FC<{ src: string }> = ({ src }) =>
  isVideoFile(src) ? (
    <OffthreadVideo
      muted
      src={staticFile(src)}
      style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 18 }}
    />
  ) : (
    <Img src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
  );

const TextCallout: React.FC<{ text: string; accentColor: string }> = ({ text, accentColor }) => (
  <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
    <div
      style={{
        background: "rgba(5,14,24,0.85)",
        borderLeft: `10px solid ${accentColor}`,
        borderRadius: 16,
        padding: "26px 44px",
        color: "white",
        fontFamily: "Montserrat, sans-serif",
        fontWeight: 700,
        fontSize: 44,
        textAlign: "center",
        maxWidth: "92%",
      }}
    >
      {text}
    </div>
  </div>
);

const OverlayElement: React.FC<{ element: ElementT; base: string; accentColor: string }> = ({
  element,
  base,
  accentColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const body = element.src ? (
    <OverlayMedia src={`${base}/${element.src}`} />
  ) : element.kind === "text_callout" && element.description ? (
    <TextCallout text={element.description} accentColor={accentColor} />
  ) : null; // unrealized non-text overlays are skipped, never crash the render
  if (!body) return null;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          ...(POSITION_STYLE[element.position] ?? POSITION_STYLE.full),
          ...getAnimation(element.animation)(frame, fps),
        }}
      >
        {body}
      </div>
    </AbsoluteFill>
  );
};

const PrimaryElement: React.FC<{
  element: ElementT | null;
  beat: BeatT;
  base: string;
  durationInFrames: number;
}> = ({ element, beat, base, durationInFrames }) => {
  if (element?.kind === "chart" && element.chart) {
    return (
      <ChartOverlay
        chart={{ ...element.chart, display_mode: "full_screen" }}
        durationInFrames={durationInFrames}
        sizes={LANDSCAPE_CHART_SIZES}
      />
    );
  }
  if (element?.src) {
    return (
      <OffthreadVideo
        muted
        src={staticFile(`${base}/${element.src}`)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    );
  }
  return (
    <AbsoluteFill style={{ background: "#08131F", alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          color: "white",
          fontFamily: "Montserrat, sans-serif",
          fontWeight: 700,
          fontSize: 56,
          maxWidth: "80%",
          textAlign: "center",
        }}
      >
        {beat.hook_label}
      </div>
    </AbsoluteFill>
  );
};

// ─── Composition ─────────────────────────────────────────────────────────────

export const LongVideo: React.FC<LongVideoProps> = ({
  fps,
  beats,
  assetBase,
  voiceoverSrc,
  captions,
  music,
  accentColor,
}) => {
  const windows = beatWindowsSec(beats);
  const totalFrames = windows.length
    ? Math.round(windows[windows.length - 1].until * fps)
    : 1;

  const captionWords = React.useMemo(
    () =>
      captions.map((w) => ({
        word: w.word,
        startFrame: Math.round(w.start * fps),
        endFrame: Math.round(w.end * fps),
        style: "bottom_center",
      })),
    [captions, fps]
  );

  const musicVolume = (f: number) => {
    if (!music) return 0;
    const base = Math.pow(10, music.volumeDb / 20);
    const fadeStart = totalFrames - music.fadeOutSec * fps;
    return f < fadeStart
      ? base
      : base * Math.max(0, (totalFrames - f) / (music.fadeOutSec * fps));
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#08131F" }}>
      {music && <Audio src={staticFile(music.src)} loop volume={(f) => musicVolume(f)} />}
      <Audio src={staticFile(voiceoverSrc)} />
      {beats.map((beat, i) => {
        const from = Math.round(windows[i].from * fps);
        const frames = Math.max(1, Math.round(windows[i].until * fps) - from);
        const primary = beat.elements.find((el) => el.role === "primary") ?? null;
        return (
          <Sequence
            key={i}
            name={`Beat ${beat.order}: ${beat.hook_label}`}
            from={from}
            durationInFrames={frames}
          >
            <PrimaryElement element={primary} beat={beat} base={assetBase} durationInFrames={frames} />
            {beat.elements
              .filter((el) => el.role === "overlay")
              .map((el, j) => {
                const oFrom = Math.round(el.start_offset_sec * fps);
                const oFrames = el.duration_sec
                  ? Math.round(el.duration_sec * fps)
                  : frames - oFrom;
                return (
                  <Sequence
                    key={j}
                    name={`Overlay ${el.kind}`}
                    from={oFrom}
                    durationInFrames={Math.max(1, oFrames)}
                  >
                    <OverlayElement element={el} base={assetBase} accentColor={accentColor} />
                  </Sequence>
                );
              })}
          </Sequence>
        );
      })}
      <Captions captions={captionWords} accentColor={accentColor} fps={fps} />
    </AbsoluteFill>
  );
};