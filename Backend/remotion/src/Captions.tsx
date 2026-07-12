import React from "react";
import {
  AbsoluteFill,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Word = { word: string; startFrame: number; endFrame: number; style: string };

// Compact styles show 4 words; full_text can hold a complete short sentence.
const groupIntoPages = (words: Word[]): Word[][] => {
  const pages: Word[][] = [];
  let current: Word[] = [];
  for (const w of words) {
    current.push(w);
    const styleChanges = current.length > 1 && current[current.length - 2].style !== w.style;
    if (styleChanges) {
      const changed = current.pop() as Word;
      pages.push(current);
      current = [changed];
    }
    const pageLimit = w.style === "full_text" ? 12 : 4;
    if (current.length >= pageLimit || /[.!?]$/.test(w.word)) {
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
  const captionStyle = page[0].style || "bottom_center";
  const topLeft = captionStyle === "top_left";
  const fullText = captionStyle === "full_text";
  const keywordEmerge = captionStyle === "keyword_emerge";

  return (
    <AbsoluteFill
      style={{
        justifyContent: topLeft ? "flex-start" : "flex-end",
        alignItems: topLeft ? "flex-start" : "center",
      }}
    >
      <style>{`@font-face { font-family: 'Montserrat'; src: url('${fontUrl}') format('truetype'); font-weight: 700; }`}</style>
      <div
        style={{
          marginTop: topLeft ? "16%" : undefined,
          marginLeft: topLeft ? "7%" : undefined,
          marginBottom: topLeft ? undefined : "22%",
          background: keywordEmerge ? "transparent" : "rgba(0,0,0,0.55)",
          borderRadius: 24,
          padding: "12px 28px",
          maxWidth: topLeft ? "72%" : "88%",
          textAlign: topLeft ? "left" : "center",
          transform: `scale(${pageScale})`,
          transformOrigin: topLeft ? "top left" : "center",
        }}
      >
        {page.map((w, i) => {
          const active = frame >= w.startFrame && frame <= w.endFrame;
          const wordEntrance = spring({
            frame: frame - w.startFrame,
            fps,
            config: { damping: 160 },
            durationInFrames: 6,
          });
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: "Montserrat, sans-serif",
                fontWeight: 700,
                fontSize: fullText ? 50 : keywordEmerge ? 66 : 58,
                lineHeight: 1.25,
                margin: "0 8px",
                color: !fullText && active ? accentColor : "white",
                opacity: keywordEmerge ? wordEntrance : 1,
                transform: keywordEmerge
                  ? `translateY(${(1 - wordEntrance) * 18}px) scale(${0.85 + wordEntrance * 0.15})`
                  : active && !fullText ? "scale(1.08)" : "scale(1)",
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