import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

export const ComplianceOverlay: React.FC<{
  text: string;
  fullDuration: boolean;
  fps: number;
  totalFrames: number;
}> = ({ text, fullDuration, fps, totalFrames }) => {
  const frame = useCurrentFrame();
  const visibleFrames = fullDuration ? totalFrames : 3 * fps;
  const isVisible = frame < visibleFrames;

  if (!isVisible) return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "flex-start",
        padding: "24px",
      }}
    >
      <div
        style={{
          background: "rgba(0,0,0,0.6)",
          borderRadius: "8px",
          padding: "8px 16px",
          color: "white",
          fontSize: "28px",
          fontFamily: "sans-serif",
          fontWeight: 600,
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};