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

const formatValue = (value: number, unit: string) =>
  unit === "%" ? `${value}%` : `${value.toLocaleString()}${unit ? ` ${unit}` : ""}`;

export const ChartOverlay: React.FC<{ chart: ChartSpec; durationInFrames: number }> = ({ chart, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({ frame, fps, durationInFrames: Math.min(durationInFrames, fps), config: { damping: 160 } });
  const values = chart.points.map((point) => point.value);
  const max = Math.max(...values, 1);
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const full = chart.display_mode === "full_screen";

  const pie = () => {
    let offset = 0;
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 42 }}>
        <svg viewBox="0 0 220 220" style={{ width: 390, height: 390, transform: `rotate(-90deg) scale(${progress})` }}>
          {chart.points.map((point, i) => {
            const share = point.value / total;
            const segment = `${share * 100 * progress} ${100 - share * 100 * progress}`;
            const circle = <circle key={point.label} cx="110" cy="110" r="82" fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="52" pathLength="100" strokeDasharray={segment} strokeDashoffset={-offset * 100} />;
            offset += share;
            return circle;
          })}
        </svg>
        <div style={{ textAlign: "left" }}>
          {chart.points.map((point, i) => (
            <div key={point.label} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 27, marginBottom: 16 }}>
              <span style={{ width: 22, height: 22, borderRadius: 6, background: COLORS[i % COLORS.length] }} />
              <span>{point.label}: <b>{formatValue(point.value, chart.unit)}</b></span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const bars = () => (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 28, height: 430 }}>
      {chart.points.map((point, i) => (
        <div key={point.label} style={{ width: `${Math.min(150, 650 / chart.points.length)}px`, textAlign: "center" }}>
          <div style={{ fontSize: 34, fontWeight: 800, marginBottom: 10 }}>{formatValue(point.value, chart.unit)}</div>
          <div style={{ height: `${Math.max(8, point.value / max * 300 * progress)}px`, background: COLORS[i % COLORS.length], borderRadius: "18px 18px 4px 4px" }} />
          <div style={{ fontSize: 28, marginTop: 12 }}>{point.label}</div>
        </div>
      ))}
    </div>
  );

  const line = () => {
    const width = 720;
    const coords = chart.points.map((point, i) => ({
      x: chart.points.length === 1 ? width / 2 : i * width / (chart.points.length - 1),
      y: 330 - point.value / max * 280,
    }));
    const path = coords.map((point, i) => `${i ? "L" : "M"}${point.x},${point.y}`).join(" ");
    return (
      <svg viewBox={`-40 0 ${width + 80} 420`} style={{ width: 760, height: 450 }}>
        <path d={path} fill="none" stroke="#FFD447" strokeWidth="12" strokeLinecap="round" pathLength="1" strokeDasharray={`${progress} 1`} />
        {coords.map((point, i) => frame >= i * Math.max(1, durationInFrames / chart.points.length) && (
          <g key={chart.points[i].label}>
            <circle cx={point.x} cy={point.y} r="13" fill={COLORS[i % COLORS.length]} />
            <text x={point.x} y="380" fill="white" fontSize="26" textAnchor="middle">{chart.points[i].label}</text>
            <text x={point.x} y={point.y - 24} fill="white" fontSize="28" fontWeight="bold" textAnchor="middle">{formatValue(chart.points[i].value, chart.unit)}</text>
          </g>
        ))}
      </svg>
    );
  };

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", background: full ? "#08131F" : "rgba(5,14,24,0.82)", padding: "130px 70px 100px", opacity: interpolate(frame, [0, 6], [0, 1], { extrapolateRight: "clamp" }) }}>
      <div style={{ color: "white", width: "100%", textAlign: "center", fontFamily: "Montserrat, sans-serif" }}>
        <div style={{ fontSize: 58, fontWeight: 800, lineHeight: 1.1, marginBottom: 45 }}>{chart.title}</div>
        {chart.chart_type === "pie" ? pie() : chart.chart_type === "bar" ? bars() : line()}
        <div style={{ color: "#FFD447", fontSize: 36, fontWeight: 700, marginTop: 32 }}>{chart.highlight}</div>
        <div style={{ color: "#B8C4D0", fontSize: 23, marginTop: 28 }}>Source: {chart.source_label}</div>
      </div>
    </AbsoluteFill>
  );
};