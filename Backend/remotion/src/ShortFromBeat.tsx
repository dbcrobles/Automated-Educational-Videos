/**
 * ShortFromBeat — Phase 8 short-form composition (1080×1920, 30fps).
 *
 * Renders a single beat's narration + elements as a vertical short.
 * Created by `short_from_beat.py`, fed via `comp_short.json` props.
 * Reuses: ChartOverlay (vertical layout), Captions, ComplianceOverlay,
 * animations.ts.
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
  interpolate,
  spring,
} from "remotion";
import { z } from "zod";
import { Captions } from "./Captions";
import { ChartOverlay, VERTICAL_CHART_SIZES } from "./ChartOverlay";
import { ComplianceOverlay } from "./ComplianceOverlay";
import { getAnimation } from "./animations";

// ─── Schema: mirrors comp_short.json ─────────────────────────────────────────

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
  start_offset_sec: z.number().default(0),
  duration_sec: z.number().nullable().optional(),
  position: z.string().default("full"),
  animation: z.string().nullable().optional(),
  src: z.string().nullable().optional(),
  chart: chartSchema.nullable().optional(),
});

const introCardSchema = z.object({
  text: z.string(),
  durationInFrames: z.number(),
});

export const shortFromBeatSchema = z.object({
  fps: z.number().default(30),
  width: z.number().default(1080),
  height: z.number().default(1920),
  durationInFrames: z.number(),
  assetBase: z.string(),
  introCard: introCardSchema,
  voiceoverSrc: z.string(),
  captions: z.array(z.object({ word: z.string(), start: z.number(), end: z.number() })),
  elements: z.array(elementSchema),
  layoutMode: z.string().default("vertical"),
  accentColor: z.string().default("#FFD447"),
  compliance: z.object({ text: z.string(), fullDuration: z.boolean() }),
});

export type ShortFromBeatProps = z.infer<typeof shortFromBeatSchema>;
type ElementT = z.infer<typeof elementSchema>;

// ─── Position map (vertical-safe, Python already remapped) ───────────────────

const POSITION_STYLE: Record<string, React.CSSProperties> = {
  full: { inset: 0 },
  lower_third: { left: "4%", right: "4%", bottom: "4%", height: "22%" },
  upper_third: { left: "4%", right: "4%", top: "4%", height: "22%" },
  center: { left: "12%", right: "12%", top: "25%", bottom: "25%" },
  top_left: { left: "3%", top: "4%", width: "42%", height: "30%" },
  top_right: { right: "3%", top: "4%", width: "42%", height: "30%" },
  bottom_left: { left: "3%", bottom: "6%", width: "42%", height: "30%" },
  bottom_right: { right: "3%", bottom: "6%", width: "42%", height: "30%" },
};

const isVideoFile = (src: string) => /\.(mp4|mov|webm|m4v)$/i.test(src);

// ─── Sub-components ──────────────────────────────────────────────────────────

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

const OverlayElement: React.FC<{ element: ElementT; base: string; accentColor: string }> = ({
  element,
  base,
  accentColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const body = element.src ? (
    <OverlayMedia src={`${base}/${element.src}`} />
  ) : null;
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
  base: string;
  durationInFrames: number;
}> = ({ element, base, durationInFrames }) => {
  if (element?.kind === "chart" && element.chart) {
    return (
      <ChartOverlay
        chart={{ ...element.chart, display_mode: "full_screen" }}
        durationInFrames={durationInFrames}
        sizes={VERTICAL_CHART_SIZES}
        layoutMode="vertical"
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
    <AbsoluteFill style={{ background: "#08131F" }} />
  );
};

const IntroCard: React.FC<{ text: string; durationInFrames: number; totalFrames: number }> = ({
  text,
  durationInFrames,
  totalFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame >= totalFrames) return null;
  const visible = frame < durationInFrames;
  if (!visible) return null;

  // Fade out over the last 10 frames
  const fadeOutStart = Math.max(0, durationInFrames - 10);
  const opacity = frame < fadeOutStart
    ? 1
    : interpolate(frame, [fadeOutStart, durationInFrames], [1, 0], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background: "rgba(8,19,31,0.8)",
        opacity,
      }}
    >
      <div
        style={{
          color: "white",
          fontFamily: "Montserrat, sans-serif",
          fontWeight: 700,
          fontSize: 68,
          textAlign: "center",
          maxWidth: "85%",
          lineHeight: 1.2,
          textShadow: "0 4px 16px rgba(0,0,0,0.5)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

// ─── Composition ─────────────────────────────────────────────────────────────

export const ShortFromBeat: React.FC<ShortFromBeatProps> = ({
  fps,
  durationInFrames,
  assetBase,
  introCard,
  voiceoverSrc,
  captions,
  elements,
  accentColor,
  compliance,
}) => {
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

  const primary = elements.find((el) => el.role === "primary") ?? null;
  const overlays = elements.filter((el) => el.role === "overlay");

  return (
    <AbsoluteFill style={{ backgroundColor: "#08131F" }}>
      {/* Audio from frame 0 */}
      <Audio src={staticFile(voiceoverSrc)} />

      {/* Primary element for the whole duration */}
      <Sequence name="Primary" from={0} durationInFrames={durationInFrames}>
        <PrimaryElement element={primary} base={assetBase} durationInFrames={durationInFrames} />
      </Sequence>

      {/* Overlay elements with start_offset / duration windows */}
      {overlays.map((el, j) => {
        const oFrom = Math.round(el.start_offset_sec * fps);
        const oFrames = el.duration_sec
          ? Math.round(el.duration_sec * fps)
          : durationInFrames - oFrom;
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

      {/* Intro card overlay on top of everything for first N frames */}
      <IntroCard
        text={introCard.text}
        durationInFrames={introCard.durationInFrames}
        totalFrames={durationInFrames}
      />

      {/* Captions in lower third, phone-readable size */}
      <Captions captions={captionWords} accentColor={accentColor} fps={fps} />

      {/* Compliance overlay (AI-Assisted badge) full duration */}
      <ComplianceOverlay
        text={compliance.text}
        fullDuration={compliance.fullDuration}
        fps={fps}
        totalFrames={durationInFrames}
      />
    </AbsoluteFill>
  );
};

/** Metadata is derived directly from props — no calculation needed beyond
 * passing through what short_from_beat.py already computed. */
export const calculateShortFromBeatMetadata = ({ props }: { props: ShortFromBeatProps }) => ({
  fps: props.fps,
  width: props.width,
  height: props.height,
  durationInFrames: props.durationInFrames,
});