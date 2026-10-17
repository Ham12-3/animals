"use client";

import { PerformanceMonitor, Stats } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { assetUrl, fetchWithProgress, fetchZoneMeta, type ZoneMeta } from "@/lib/assets";
import { detectQuality, isTouchDevice, type Quality } from "@/lib/device";
import { type Hotspot, loadHotspots } from "@/lib/hotspots";
import { zones as configuredZones, zonesFile } from "@/lib/zones";
import { CollisionWorld } from "./collision";
import Hotspots from "./Hotspots";
import { bindKeyboard, createInput } from "./input";
import MapOverlay, { type ZoneEntry } from "./MapOverlay";
import OrbitFlyover from "./OrbitFlyover";
import TouchJoystick from "./TouchJoystick";
import WalkControls, { type Player, spawnPlayer } from "./WalkControls";
import ZoneSplat, { SparkRendererObject } from "./ZoneSplat";

type Mode = "walk" | "orbit";
const FADE_MS = 450;
const EYE_HEIGHT = 1.6;
const isDev = process.env.NODE_ENV === "development";

interface Loaded {
  key: string;
  meta: ZoneMeta;
  world: CollisionWorld | null;
  hotspots: Hotspot[];
}

function publicZones(): ZoneEntry[] {
  return configuredZones.map((z) => ({
    id: z.id,
    name: z.name,
    description: z.description,
    map: z.map,
    // In production a zone is reachable once it is published to the CDN.
    available: !isDev && z.status === "live",
  }));
}

function CameraFov({ fov }: { fov: number }) {
  const get = useThree((s) => s.get);
  useEffect(() => {
    const camera = get().camera;
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.fov = fov;
      camera.updateProjectionMatrix();
    }
  }, [get, fov]);
  return null;
}

/** Dev helper: H logs the collision point under the crosshair, for hotspots.json. */
function HotspotPicker({ world, onPick }: { world: CollisionWorld | null; onPick: (p: THREE.Vector3) => void }) {
  const get = useThree((s) => s.get);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "KeyH" || !world) return;
      const camera = get().camera;
      const dir = new THREE.Vector3();
      camera.getWorldDirection(dir);
      const hit = world.raycast(camera.position, dir, 100);
      if (hit) onPick(hit.point.clone().add(new THREE.Vector3(0, 0.3, 0)));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [get, world, onPick]);
  return null;
}

export default function Explorer({ initialZone, debug }: { initialZone?: string; debug: boolean }) {
  const [zones, setZones] = useState<ZoneEntry[]>(publicZones);
  const [zoneId, setZoneId] = useState<string | null>(initialZone ?? null);
  const [quality, setQuality] = useState<Quality>(detectQuality);
  const [mode, setMode] = useState<Mode>("walk");
  const [flying, setFlying] = useState(false);
  const [mapOpen, setMapOpen] = useState(!initialZone);
  const [helpOpen, setHelpOpen] = useState(false);
  const [openHotspot, setOpenHotspot] = useState<Hotspot | null>(null);
  const [fadeOut, setFadeOut] = useState(false);
  const [noclip, setNoclip] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [dpr, setDpr] = useState(() => Math.min(window.devicePixelRatio || 1, quality === "high" ? 1.5 : 1));

  const key = `${zoneId}|${quality}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [splatReady, setSplatReady] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ key: string; splat: number; collision: number }>({
    key: "",
    splat: 0,
    collision: 0,
  });
  const [error, setError] = useState<{ key: string; message: string } | null>(null);

  const inputRef = useRef(createInput());
  const playerRef = useRef<Player | null>(null);
  const [touch] = useState(isTouchDevice);

  // Dev: zones published on this machine (pipeline/work/*/publish).
  useEffect(() => {
    if (!isDev) return;
    fetch("/dev-assets")
      .then((r) => r.json() as Promise<{ zones: string[] }>)
      .then(({ zones: local }) => {
        setZones((prev) => [
          ...prev.map((z) => ({ ...z, available: local.includes(z.id) })),
          ...local
            .filter((id) => !prev.some((z) => z.id === id))
            .map((id) => ({ id, name: id, available: true, local: true })),
        ]);
      })
      .catch(() => {});
  }, []);

  // Metadata, collision mesh and hotspots for the current zone. The splat
  // streams in parallel inside the canvas.
  useEffect(() => {
    if (!zoneId) return;
    const ac = new AbortController();
    const k = `${zoneId}|${quality}`;
    (async () => {
      try {
        const meta = await fetchZoneMeta(zoneId, ac.signal);
        const [world, hotspots] = await Promise.all([
          meta.files.collision
            ? fetchWithProgress(
                assetUrl(zoneId, meta.files.collision),
                (p) => setProgress((prev) => ({ ...prev, key: k, collision: p })),
                ac.signal,
              ).then((buf) => CollisionWorld.fromGlb(buf))
            : Promise.resolve(null),
          loadHotspots(zoneId),
        ]);
        if (ac.signal.aborted) {
          world?.dispose();
          return;
        }
        setLoaded({ key: k, meta, world, hotspots });
      } catch (e) {
        if (!ac.signal.aborted) setError({ key: k, message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => ac.abort();
  }, [zoneId, quality]);

  // Free the previous zone's collision data.
  useEffect(() => () => loaded?.world?.dispose(), [loaded]);

  // New zone data: put the player at the spawn point.
  useEffect(() => {
    if (loaded) playerRef.current = spawnPlayer(loaded.meta, loaded.world);
  }, [loaded]);

  useEffect(() => bindKeyboard(inputRef.current), []);

  // Debug: inspect live state from the console (window.__vantara).
  useEffect(() => {
    if (debug) Object.assign(window, { __vantara: { player: playerRef, input: inputRef, world: () => loaded?.world } });
  }, [debug, loaded]);

  const ready = loaded?.key === key && splatReady === key;
  const current = loaded?.key === key ? loaded : null;
  const zoneError = error?.key === key ? error.message : null;

  const switchZone = useCallback(
    (id: string) => {
      setMapOpen(false);
      if (id === zoneId) return;
      setFadeOut(true);
      setFlying(false);
      setOpenHotspot(null);
      window.setTimeout(() => {
        setZoneId(id);
        setFadeOut(false);
        const url = new URL(window.location.href);
        url.searchParams.set("zone", id);
        window.history.replaceState(null, "", url);
      }, FADE_MS);
    },
    [zoneId],
  );

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "KeyM") setMapOpen((v) => !v);
      else if (e.code === "KeyV") setMode((m) => (m === "walk" ? "orbit" : "walk"));
      else if (e.code === "KeyF") {
        setMode("orbit");
        setFlying((f) => !f);
      } else if (e.code === "Escape") {
        setMapOpen(false);
        setHelpOpen(false);
        setOpenHotspot(null);
      } else if (e.code === "KeyN" && debug) setNoclip((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [debug]);

  const onPickPoint = useCallback((p: THREE.Vector3) => {
    const text = JSON.stringify([+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)]);
    console.info("hotspot position", text);
    navigator.clipboard?.writeText(text).catch(() => {});
    setToast(`Hotspot position ${text} (copied)`);
    window.setTimeout(() => setToast(null), 3000);
  }, []);

  const splatUrl = zoneId ? assetUrl(zoneId, quality === "low" ? `${zoneId}.mobile.spz` : `${zoneId}.spz`) : null;
  const pct =
    progress.key === key
      ? Math.round(
          100 * (current?.meta.files.collision || progress.collision > 0
            ? 0.85 * Math.max(0, progress.splat) + 0.15 * Math.max(0, progress.collision)
            : Math.max(0, progress.splat)),
        )
      : 0;
  const zoneName = zones.find((z) => z.id === zoneId)?.name ?? zoneId ?? "";

  return (
    <div className="relative h-full w-full select-none">
      <Canvas
        dpr={dpr}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        camera={{ fov: 60, near: 0.05, far: 1000, position: [0, 1.6, 0] }}
        className="touch-none"
      >
        <PerformanceMonitor
          onDecline={() => setDpr((d) => Math.max(0.5, +(d - 0.25).toFixed(2)))}
          onIncline={() => setDpr((d) => Math.min(quality === "high" ? 1.5 : 1, +(d + 0.25).toFixed(2)))}
        />
        <SparkRendererObject />
        {splatUrl && (
          <ZoneSplat
            key={key}
            url={splatUrl}
            onProgress={(p) => setProgress((prev) => ({ ...prev, key, splat: p }))}
            onReady={() => setSplatReady(key)}
            onError={(message) => setError({ key, message })}
          />
        )}
        {current && (
          <>
            <CameraFov fov={current.meta.fovY} />
            <WalkControls
              playerRef={playerRef}
              world={current.world}
              meta={current.meta}
              inputRef={inputRef}
              enabled={ready && mode === "walk"}
              noclip={noclip}
              eyeHeight={EYE_HEIGHT}
            />
            {mode === "orbit" && (
              <OrbitFlyover
                meta={current.meta}
                enabled={ready}
                flying={flying}
                onStopFlying={() => setFlying(false)}
              />
            )}
            {ready && <Hotspots hotspots={current.hotspots} world={current.world} onOpen={setOpenHotspot} />}
            {debug && <HotspotPicker world={current.world} onPick={onPickPoint} />}
          </>
        )}
        {debug && <Stats className="!left-auto !right-2 !top-14" />}
      </Canvas>

      {/* Fade + loading screen */}
      <div
        className="pointer-events-none absolute inset-0 z-20 grid place-items-center bg-black transition-opacity"
        style={{ opacity: fadeOut || !ready ? 1 : 0, transitionDuration: `${FADE_MS}ms` }}
      >
        {zoneId && !fadeOut && !ready && (
          <div className="w-72 text-center text-neutral-200">
            <div className="text-sm font-medium">{zoneName}</div>
            {zoneError ? (
              <p className="mt-3 text-xs text-red-300">{zoneError}</p>
            ) : (
              <>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div className="h-full bg-emerald-400 transition-[width]" style={{ width: `${pct}%` }} />
                </div>
                <p className="mt-2 text-xs text-neutral-400">
                  {pct < 100 ? `Downloading ${pct}%` : "Preparing scene…"}
                </p>
              </>
            )}
          </div>
        )}
      </div>

      {/* HUD */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-3 p-3">
        <div className="pointer-events-auto rounded-xl bg-black/45 px-3 py-2 text-white backdrop-blur-md">
          <div className="text-sm font-semibold">{zoneName || "Vantara 3D"}</div>
          <div className="text-[11px] text-neutral-300">{zonesFile.site.disclaimer}</div>
        </div>
        <div className="pointer-events-auto flex flex-wrap justify-end gap-1.5">
          <HudButton active={mode === "walk"} onClick={() => setMode("walk")} hint="V">
            Walk
          </HudButton>
          <HudButton active={mode === "orbit" && !flying} onClick={() => { setMode("orbit"); setFlying(false); }} hint="V">
            Orbit
          </HudButton>
          <HudButton active={flying} onClick={() => { setMode("orbit"); setFlying((f) => !f); }} hint="F">
            Flyover
          </HudButton>
          <HudButton onClick={() => setMapOpen(true)} hint="M">
            Map
          </HudButton>
          <HudButton onClick={() => setQuality((q) => (q === "high" ? "low" : "high"))}>
            {quality === "high" ? "HD" : "Lite"}
          </HudButton>
          <HudButton onClick={() => setHelpOpen((v) => !v)}>?</HudButton>
        </div>
      </div>

      {ready && mode === "walk" && !touch && (
        <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10 text-center text-xs text-white/70">
          Click to look around · WASD to move · Shift to run · Esc to free the mouse
        </div>
      )}
      {ready && mode === "walk" && touch && <TouchJoystick inputRef={inputRef} />}
      {mode === "walk" && ready && !touch && (
        <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/70" />
      )}

      {openHotspot && (
        <div className="absolute bottom-4 right-4 z-20 w-80 max-w-[calc(100%-2rem)] rounded-2xl border border-white/15 bg-neutral-950/85 p-4 text-neutral-100 shadow-2xl backdrop-blur-md">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-semibold">{openHotspot.title}</h3>
            <button onClick={() => setOpenHotspot(null)} className="text-neutral-400 hover:text-white" aria-label="Close">
              ✕
            </button>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-neutral-300">{openHotspot.body}</p>
        </div>
      )}

      {helpOpen && (
        <div className="absolute right-3 top-16 z-20 w-72 rounded-2xl border border-white/15 bg-neutral-950/85 p-4 text-sm text-neutral-200 backdrop-blur-md">
          <h3 className="mb-2 font-semibold">Controls</h3>
          <ul className="space-y-1 text-xs text-neutral-300">
            <li><b>Walk:</b> click the scene, move the mouse to look, WASD or arrows to move, Shift to run</li>
            <li><b>Phone:</b> left stick to move, drag anywhere else to look</li>
            <li><b>Orbit:</b> drag to rotate, scroll or pinch to zoom</li>
            <li><b>V</b> walk/orbit · <b>F</b> flyover · <b>M</b> map · <b>Esc</b> close</li>
            {debug && <li><b>H</b> copy hotspot position · <b>N</b> noclip ({noclip ? "on" : "off"})</li>}
          </ul>
          <p className="mt-3 text-[11px] text-neutral-500">
            {quality === "high" ? "HD: full detail." : "Lite: fewer splats for phones and older laptops."}
          </p>
        </div>
      )}

      {toast && (
        <div className="absolute bottom-14 left-1/2 z-20 -translate-x-1/2 rounded-full bg-black/70 px-4 py-2 text-xs text-white">
          {toast}
        </div>
      )}

      {mapOpen && <MapOverlay zones={zones} current={zoneId} onPick={switchZone} onClose={() => setMapOpen(false)} />}
    </div>
  );
}

function HudButton({
  children,
  onClick,
  active,
  hint,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  hint?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={hint ? `Shortcut: ${hint}` : undefined}
      className={`rounded-full px-3 py-1.5 text-xs font-medium backdrop-blur-md transition ${
        active ? "bg-white text-black" : "bg-black/45 text-white hover:bg-black/65"
      }`}
    >
      {children}
    </button>
  );
}
