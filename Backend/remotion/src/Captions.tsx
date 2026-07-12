import React from "react";
import {
  AbsoluteFill,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Word = { word: string; startFrame: number; endFrame: number };

// New page every 4 words OR when a word ends a sentence.
const groupIntoPages = (words: Word[]): Word[][] => {
  const pages: Word[][] = [];
  let current: Word[] = [];
  for (const w of words) {
    current.push(w);
    if (current.length >= 4 || /[.!?]$/.test(w.word)) {
      pages.push(current);
      current = [];
    }
  }
  if (current.length > 0) pages.push(current);
  return pages;
};

const fontUrl = staticFile("fonts/Montserrat-Bold.ttf");

export const Captions: React.FC<{
  captions: Word[];
  accentColor: string;
  fps: number;
}> = ({ captions, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pages = React.useMemo(() => groupIntoPages(captions), [captions]);

  // Active page: the latest page that has started; hold it briefly after
  // its last word so captions don't flicker during narration pauses.
  const started = pages.filter((p) => p[0].startFrame <= frame);
  const page = started.length > 0 ? started[started.length - 1] : null;
  const holdFrames = Math.round(fps * 0.4);
  const visible =
    page !== null && frame <= page[page.length - 1].endFrame + holdFrames;

  if (!page || !visible) {
    return (
      <style>{`@font-face { font-family: 'Montserrat'; src: url('${fontUrl}') format('truetype'); font-weight: 700; }`}</style>
    );
  }

  const entrance = spring({
    frame: frame - page[0].startFrame,
    fps,
    config: { damping: 200 },
    durationInFrames: 5,
  });
  const pageScale = 0.8 + 0.2 * entrance;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
      }}
    >
      <style>{`@font-face { font-family: 'Montserrat'; src: url('${fontUrl}') format('truetype'); font-weight: 700; }`}</style>
      <div
        style={{
          marginBottom: "22%",
          background: "rgba(0,0,0,0.55)",
          borderRadius: 24,
          padding: "12px 28px",
          maxWidth: "88%",
          textAlign: "center",
          transform: `scale(${pageScale})`,
        }}
      >
        {page.map((w, i) => {
          const active = frame >= w.startFrame && frame <= w.endFrame;
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: "Montserrat, sans-serif",
                fontWeight: 700,
                fontSize: 58,
                lineHeight: 1.25,
                margin: "0 8px",
                color: active ? accentColor : "white",
                transform: active ? "scale(1.08)" : "scale(1)",
                textShadow: "0 2px 8px rgba(0,0,0,0.6)",
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};