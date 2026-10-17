export type Quality = "high" | "low";

/**
 * Pick the splat build for this device: phones, tablets and low-memory
 * machines get the mobile LOD (fewer splats, no view-dependent colour).
 */
export function detectQuality(): Quality {
  if (typeof window === "undefined") return "high";
  const nav = navigator as Navigator & { deviceMemory?: number };
  const touchFirst = window.matchMedia("(pointer: coarse)").matches;
  const lowMemory = (nav.deviceMemory ?? 8) <= 4;
  const fewCores = (nav.hardwareConcurrency ?? 8) <= 4;
  return touchFirst || lowMemory || fewCores ? "low" : "high";
}

export const isTouchDevice = () =>
  typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;
