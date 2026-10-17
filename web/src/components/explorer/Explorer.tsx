"use client";

import { PerformanceMonitor, Stats } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { AnimalPlacement } from "@/lib/animals";
import { assetPath, DEFAULT_LIGHTING, fetchZoneMeta, type ZoneMeta } from "@/lib/assets";
import { detectQuality, isTouchDevice, type Quality } from "@/lib/device";
import { type Hotspot, loadHotspots } from "@/lib/hotspots";
import { loadWorldCollision, loadWorldManifest, type Place, type WorldManifest, worldBase } from "@/lib/world";
import { zones as configuredZones, zonesFile } from "@/lib/zones";
import Animals from "./Animals";
import { CollisionWorld } from "./collision";
import Hotspots from "./Hotspots";
import { bindKeyboard, createInput } from "./input";
import MapOverlay, { type ZoneEntry } from "./MapOverlay";
import OrbitFlyover, { type CameraFocus } from "./OrbitFlyover";
import PlaceLabels from "./PlaceLabels";
import TouchJoystick from "./TouchJoystick";
import WalkControls, { type Player, spawnPlayer } from "./WalkControls";
import WorldScene from "./WorldScene";

type Mode = "walk" | "orbit";
const FADE_MS = 450;
const EYE_HEIGHT = 1.6;
const isDev = process.env.NODE_ENV === "development";

interface Loaded {
  key: string;
  meta: ZoneMeta;
  world: CollisionWorld | null;
  /** The collision mesh belongs to a mesh world shared by several zones: keep it. */
  sharedWorld: boolean;
  hotspots: Hotspot[];
  animals: AnimalPlacement[];
}

/** The mesh world on screen (stays loaded while moving between its zones). */
interface WorldOnScreen {
  url: string;
  manifest: WorldManifest;
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
    Object.assign(window, { __r3f: get }); // debug: inspect renderer, scene, camera
  }, [get]);
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
  const [worldOnScreen, setWorldOnScreen] = useState<WorldOnScreen | null>(null);
  const [worldReady, setWorldReady] = useState<string | null>(null);
  const [place, setPlace] = useState<Place | null>(null);
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const [progress, setProgress] = useState<{ key: string; world: number; collision: number }>({
    key: "",
    world: 0,
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

  // Metadata, collision mesh and hotspots for the current zone. The mesh
  // world streams in parallel inside the canvas.
  useEffect(() => {
    if (!zoneId) return;
    const ac = new AbortController();
    const k = `${zoneId}|${quality}`;
    (async () => {
      try {
        const meta = await fetchZoneMeta(zoneId, ac.signal);
        if (ac.signal.aborted) return;
        if (meta.world) {
          // Mesh world: manifest and collision are shared by all its zones (cached).
          const url = assetPath(meta.world.manifest);
          const manifest = await loadWorldManifest(url);
          const [world, hotspots] = await Promise.all([
            loadWorldCollision(worldBase(url) + manifest.collision, (p) =>
              setProgress((prev) => ({ ...prev, key: k, collision: p })),
            ),
            loadHotspots(zoneId),
          ]);
          if (ac.signal.aborted) return;
          setWorldOnScreen((prev) => (prev?.url === url ? prev : { url, manifest }));
          setLoaded({ key: k, meta, world, sharedWorld: true, hotspots, animals: manifest.animals });
          return;
        }
        throw new Error(`Zone "${zoneId}" is not part of the mesh world`);
      } catch (e) {
        if (!ac.signal.aborted) setError({ key: k, message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => ac.abort();
  }, [zoneId, quality]);

  // Free the previous zone's collision data.
  useEffect(
    () => () => {
      if (!loaded?.sharedWorld) loaded?.world?.dispose();
    },
    [loaded],
  );

  // New zone data: put the player at the spawn point.
  useEffect(() => {
    if (loaded) playerRef.current = spawnPlayer(loaded.meta, loaded.world);
  }, [loaded]);

  useEffect(() => bindKeyboard(inputRef.current), []);

  // Debug: inspect live state from the console (window.__vantara).
  useEffect(() => {
    if (debug) Object.assign(window, { __vantara: { player: playerRef, input: inputRef, world: () => loaded?.world } });
  }, [debug, loaded]);

  const current = loaded?.key === key ? loaded : null;
  const isWorld = !!current?.meta.world;
  const ready = !!current && worldReady === worldOnScreen?.url;
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
        setPlace(null);
      } else if (e.code === "KeyN" && debug) setNoclip((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [debug]);

  // Places (mesh world): click a label or a map entry to fly there.
  const places = worldOnScreen?.manifest.places;
  const zoomTo = useCallback(
    (p: Place) => {
      setMapOpen(false);
      setOpenHotspot(null);
      setPlace(p);
      setFlying(false);
      setMode("orbit");
      const groundY = current?.meta.groundY ?? 0;
      const y = p.tier === 1 ? groundY : Math.max(groundY, p.position[1] - 2.5);
      const distance = THREE.MathUtils.clamp(p.size * (p.tier === 1 ? 1.1 : 1.8), 18, 450);
      setFocus((f) => ({ target: [p.position[0], y, p.position[2]], distance, seq: (f?.seq ?? 0) + 1 }));
    },
    [current],
  );

  /** Double-click in orbit: show the card of the place under the pointer, if any. */
  const onPickScene = useCallback(
    (hit: THREE.Vector3) => {
      if (!places) return;
      let best: Place | null = null;
      let bestD = Infinity;
      for (const p of places) {
        if (p.tier === 1) continue;
        const d = Math.hypot(p.position[0] - hit.x, p.position[2] - hit.z);
        if (d < p.size * 0.6 + 3 && d < bestD) {
          best = p;
          bestD = d;
        }
      }
      setPlace(best);
    },
    [places],
  );

  const walkTo = useCallback((p: Place) => {
    const player = playerRef.current;
    if (!p.stand || !player) return;
    player.feet.set(...p.stand.position);
    player.lastSafe.copy(player.feet);
    player.velY = 0;
    player.yaw = THREE.MathUtils.degToRad(p.stand.yawDeg);
    player.pitch = -0.05;
    setFocus(null);
    setFlying(false);
    setMode("walk");
  }, []);

  const onPickPoint = useCallback((p: THREE.Vector3) => {
    const text = JSON.stringify([+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)]);
    console.info("hotspot position", text);
    navigator.clipboard?.writeText(text).catch(() => {});
    setToast(`Hotspot position ${text} (copied)`);
    window.setTimeout(() => setToast(null), 3000);
  }, []);

  const pct =
    progress.key === key ? Math.round(100 * (0.85 * Math.max(0, progress.world) + 0.15 * Math.max(0, progress.collision))) : 0;
  const zoneName = zones.find((z) => z.id === zoneId)?.name ?? zoneId ?? "";
  // HUD title follows a selected place into its zone (the world spans all zones).
  const zoneNameOf = (id: string) => zones.find((z) => z.id === id)?.name ?? places?.find((p) => p.id === id)?.name;
  const hudName = (place && zoneNameOf(place.zone)) || zoneName;

  return (
    <div className="relative h-full w-full select-none">
      <Canvas
        flat
        dpr={dpr}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        camera={{ fov: 60, near: 0.05, far: 1000, position: [0, 1.6, 0] }}
        className="touch-none"
      >
        <PerformanceMonitor
          onDecline={() => setDpr((d) => Math.max(0.5, +(d - 0.25).toFixed(2)))}
          onIncline={() => setDpr((d) => Math.min(quality === "high" ? 1.5 : 1, +(d + 0.25).toFixed(2)))}
        />
        {worldOnScreen && (
          <WorldScene
            key={worldOnScreen.url}
            url={worldOnScreen.url}
            manifest={worldOnScreen.manifest}
            onProgress={(p) => setProgress((prev) => ({ ...prev, key, world: p }))}
            onReady={() => setWorldReady(worldOnScreen.url)}
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
                focus={focus}
                world={isWorld ? current.world : null}
                onPick={onPickScene}
              />
            )}
            {ready && <Hotspots hotspots={current.hotspots} world={current.world} onOpen={setOpenHotspot} />}
            {ready && places && <PlaceLabels
                places={places}
                occluders={worldOnScreen?.manifest.occluders ?? []}
                selected={place?.id ?? null}
                onSelect={zoomTo}
              />}
            {ready && current.animals.length > 0 && (
              <Suspense fallback={null}>
                <Animals
                  placements={current.animals}
                  world={current.world}
                  groundY={current.meta.groundY}
                  lighting={current.meta.lighting ?? DEFAULT_LIGHTING}
                  sceneLit={isWorld}
                />
              </Suspense>
            )}
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
          <div className="text-sm font-semibold">{hudName || "Vantara 3D"}</div>
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

      {place && (
        <div className="absolute bottom-4 left-4 z-20 w-80 max-w-[calc(100%-2rem)] rounded-2xl border border-white/15 bg-neutral-950/85 p-4 text-neutral-100 shadow-2xl backdrop-blur-md">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="font-semibold">{place.name}</h3>
              {place.tier > 1 && (
                <p className="text-[11px] text-neutral-400">{zoneNameOf(place.zone)}</p>
              )}
            </div>
            <button onClick={() => setPlace(null)} className="text-neutral-400 hover:text-white" aria-label="Close">
              ✕
            </button>
          </div>
          {place.description && <p className="mt-2 text-sm leading-relaxed text-neutral-300">{place.description}</p>}
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => zoomTo(place)}
              className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-black hover:bg-neutral-200"
            >
              Zoom to it
            </button>
            {place.stand && (
              <button
                onClick={() => walkTo(place)}
                className="rounded-full border border-white/25 px-3 py-1.5 text-xs font-medium hover:bg-white/10"
              >
                Walk here
              </button>
            )}
          </div>
          <p className="mt-3 text-[10px] text-neutral-500">Designed layout: artistic interpretation, not surveyed.</p>
        </div>
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
            <li><b>Orbit:</b> drag to rotate, scroll or pinch to zoom{isWorld && ", double-click to zoom in"}</li>
            {isWorld && <li><b>Labels:</b> click a name (or a place on the map) to fly there</li>}
            <li><b>V</b> walk/orbit · <b>F</b> flyover · <b>M</b> map · <b>Esc</b> close</li>
            {debug && <li><b>H</b> copy hotspot position · <b>N</b> noclip ({noclip ? "on" : "off"})</li>}
          </ul>
          <div className="mt-3 space-y-1 text-[11px] text-neutral-500">
            <p>{worldOnScreen?.manifest.note}</p>
            {worldOnScreen?.manifest.attribution.map((a) => <p key={a}>{a}</p>)}
          </div>
        </div>
      )}

      {toast && (
        <div className="absolute bottom-14 left-1/2 z-20 -translate-x-1/2 rounded-full bg-black/70 px-4 py-2 text-xs text-white">
          {toast}
        </div>
      )}

      {mapOpen && (
        <MapOverlay
          zones={zones}
          current={zoneId}
          onPick={switchZone}
          onClose={() => setMapOpen(false)}
          places={isWorld ? places : undefined}
          worldMap={isWorld ? worldOnScreen?.manifest.map : undefined}
          onPickPlace={zoomTo}
        />
      )}
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
