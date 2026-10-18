export type Quality = "high" | "low";

/**
 * Pick a quality tier for this device: phones, tablets and low-memory
 * machines get a lower render resolution.
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
