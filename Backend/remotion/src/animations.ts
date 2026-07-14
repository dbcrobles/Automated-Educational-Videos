/**
 * animations.ts — overlay entrance presets for the LongVideo composition.
 *
 * An ElementCue's `animation` string (from beats.json) is looked up here by
 * name; unknown or missing names fall back to `fade`. Adding a preset later
 * means adding one entry to PRESETS — nothing else changes.
 */
import type { CSSProperties } from "react";
import { Easing, interpolate, spring } from "remotion";

export type AnimationPreset = (frame: number, fps: number) => CSSProperties;

const clamp = {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
} as const;

const PRESETS: Record<string, AnimationPreset> = {
  fade: (frame, fps) => ({
    opacity: interpolate(frame, [0, fps * 0.3], [0, 1], clamp),
  }),
  pop_in: (frame, fps) => ({
    opacity: interpolate(frame, [0, fps * 0.15], [0, 1], clamp),
    scale: String(spring({ frame, fps, config: { damping: 12, stiffness: 200 } })),
  }),
  slide_up: (frame, fps) => ({
    opacity: interpolate(frame, [0, fps * 0.25], [0, 1], clamp),
    translate: `0px ${interpolate(frame, [0, fps * 0.35], [70, 0], {
      ...clamp,
      easing: Easing.bezier(0.16, 1, 0.3, 1),
    })}px`,
  }),
  shake: (frame, fps) => ({
    opacity: interpolate(frame, [0, 4], [0, 1], clamp),
    translate: `${
      frame < fps * 0.6 ? Math.sin(frame * 2.4) * 9 * (1 - frame / (fps * 0.6)) : 0
    }px 0px`,
  }),
};

export const getAnimation = (name?: string | null): AnimationPreset =>
  PRESETS[name ?? "fade"] ?? PRESETS.fade;