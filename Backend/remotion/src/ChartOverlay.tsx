import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type ChartSpec = {
  chart_type: "pie" | "bar" | "line";
  display_mode: "overlay" | "full_screen";
  title: string;
  unit: string;
  points: { label: string; value: number }[];
  highlight: string;
  source_url: string;
  source_label: string;
};

const COLORS = ["#FFD447", "#48CAE4", "#FF6B6B", "#7BD389", "#B79CED"];

// Sizes are props-driven so LongVideo can pass a 16:9 layout (and Phase 8 a
// vertical one) without touching the renderers. Defaults = original 9:16 look.
export type ChartSizes = {
  padding: string;
  titlePx: number;
  legendPx: number;
  piePx: number;
  barAreaPx: number;      // bar chart column area height
  barMaxPx: number;       // tallest bar in px
  barValuePx: number;
  barLabelPx: number;
  barRowPx: number;       // total width budget for all bars
  lineWidthPx: number;
  lineHeightPx: number;
  highlightPx: number;
  sourcePx: number;
};

export const PORTRAIT_CHART_SIZES: ChartSizes = {
  padding: "130px 70px 100px", titlePx: 58, legendPx: 27, piePx: 390,
  barAreaPx: 430, barMaxPx: 300, barValuePx: 34, barLabelPx: 28, barRowPx: 650,
  lineWidthPx: 720, lineHeightPx: 450, highlightPx: 36, sourcePx: 23,
};

export const LANDSCAPE_CHART_SIZES: ChartSizes = {
  padding: "50px 140px", titlePx: 62, legendPx: 30, piePx: 430,
  barAreaPx: 500, barMaxPx: 360, barValuePx: 36, barLabelPx: 30, barRowPx: 1150,
  lineWidthPx: 1240, lineHeightPx: 520, highlightPx: 38, sourcePx: 24,
};

/** Sizes for vertical 1080×1920 shorts — fonts ×1.4 vs LANDSCAPE, chart area
 * uses the full 1080 width minus vertical padding. */
export const VERTICAL_CHART_SIZES: ChartSizes = {
  padding: "80px 60px 140px", titlePx: 87, legendPx: 42, piePx: 400,
  barAreaPx: 460, barMaxPx: 340, barValuePx: 50, barLabelPx: 42, barRowPx: 920,
  lineWidthPx: 920, lineHeightPx: 520, highlightPx: 53, sourcePx: 34,
};

const formatValue = (value: number, unit: string) =>
  unit === "%" ? `${value}%` : `${value.toLocaleString()}${unit ? ` ${unit}` : ""}`;

export const ChartOverlay: React.FC<{
  chart: ChartSpec;
  durationInFrames: number;
  sizes?: ChartSizes;
  layoutMode?: "horizontal" | "vertical";
}> = ({ chart, durationInFrames, sizes = PORTRAIT_CHART_SIZES, layoutMode = "horizontal" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({ frame, fps, durationInFrames: Math.min(durationInFrames, fps), config: { damping: 160 } });
  const values = chart.points.map((point) => point.value);
  const max = Math.max(...values, 1);
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const full = chart.display_mode === "full_screen";

  const pie = () => {
    let offset = 0;
    const isVertical = layoutMode === "vertical";
    return (
      <div style={{ display: "flex", flexDirection: isVertical ? "column" : "row", alignItems: "center", justifyContent: "center", gap: isVertical ? 32 : 42 }}>
        <svg viewBox="0 0 220 220" style={{ width: sizes.piePx, height: sizes.piePx, transform: `rotate(-90deg) scale(${progress})` }}>
          {chart.points.map((point, i) => {
            const share = point.value / total;
            const segment = `${share * 100 * progress} ${100 - share * 100 * progress}`;
            const circle = <circle key={point.label} cx="110" cy="110" r="82" fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="52" pathLength="100" strokeDasharray={segment} strokeDashoffset={-offset * 100} />;
            offset += share;
            return circle;
          })}
        </svg>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: isVertical ? 20 : 12, textAlign: isVertical ? "center" : "left", maxWidth: isVertical ? "100%" : undefined }}>
          {chart.points.map((point, i) => (
            <div key={point.label} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: sizes.legendPx, marginBottom: 16 }}>
              <span style={{ width: 22, height: 22, borderRadius: 6, background: COLORS[i % COLORS.length] }} />
              <span>{point.label}: <b>{formatValue(point.value, chart.unit)}</b></span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const bars = () => (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 28, height: sizes.barAreaPx }}>
      {chart.points.map((point, i) => (
        <div key={point.label} style={{ width: `${Math.min(180, sizes.barRowPx / chart.points.length)}px`, textAlign: "center" }}>
          <div style={{ fontSize: sizes.barValuePx, fontWeight: 800, marginBottom: 10 }}>{formatValue(point.value, chart.unit)}</div>
          <div style={{ height: `${Math.max(8, point.value / max * sizes.barMaxPx * progress)}px`, background: COLORS[i % COLORS.length], borderRadius: "18px 18px 4px 4px" }} />
          <div style={{ fontSize: sizes.barLabelPx, marginTop: 12 }}>{point.label}</div>
        </div>
      ))}
    </div>
  );

  const line = () => {
    const width = sizes.lineWidthPx;
    const viewH = sizes.lineHeightPx - 30;
    const baseline = viewH - 90;
    const amplitude = baseline - 50;
    const coords = chart.points.map((point, i) => ({
      x: chart.points.length === 1 ? width / 2 : i * width / (chart.points.length - 1),
      y: baseline - point.value / max * amplitude,
    }));
    const path = coords.map((point, i) => `${i ? "L" : "M"}${point.x},${point.y}`).join(" ");
    return (
      <svg viewBox={`-40 0 ${width + 80} ${viewH}`} style={{ width: width + 40, height: sizes.lineHeightPx }}>
        <path d={path} fill="none" stroke="#FFD447" strokeWidth="12" strokeLinecap="round" pathLength="1" strokeDasharray={`${progress} 1`} />
        {coords.map((point, i) => frame >= i * Math.max(1, durationInFrames / chart.points.length) && (
          <g key={chart.points[i].label}>
            <circle cx={point.x} cy={point.y} r="13" fill={COLORS[i % COLORS.length]} />
            <text x={point.x} y={viewH - 40} fill="white" fontSize="26" textAnchor="middle">{chart.points[i].label}</text>
            <text x={point.x} y={point.y - 24} fill="white" fontSize="28" fontWeight="bold" textAnchor="middle">{formatValue(chart.points[i].value, chart.unit)}</text>
          </g>
        ))}
      </svg>
    );
  };

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", background: full ? "#08131F" : "rgba(5,14,24,0.82)", padding: sizes.padding, opacity: interpolate(frame, [0, 6], [0, 1], { extrapolateRight: "clamp" }) }}>
      <div style={{ color: "white", width: "100%", textAlign: "center", fontFamily: "Montserrat, sans-serif" }}>
        <div style={{ fontSize: sizes.titlePx, fontWeight: 800, lineHeight: 1.1, marginBottom: 45 }}>{chart.title}</div>
        {chart.chart_type === "pie" ? pie() : chart.chart_type === "bar" ? bars() : line()}
        <div style={{ color: "#FFD447", fontSize: sizes.highlightPx, fontWeight: 700, marginTop: 32 }}>{chart.highlight}</div>
        <div style={{ color: "#B8C4D0", fontSize: sizes.sourcePx, marginTop: 28 }}>Source: {chart.source_label}</div>
      </div>
    </AbsoluteFill>
  );
};