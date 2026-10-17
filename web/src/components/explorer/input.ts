/**
 * Input shared between DOM handlers and the render loop. Mutated in place (no
 * React state) so 60 fps movement never re-renders the tree.
 */
export interface InputState {
  /** Movement intent, -1..1: x = strafe right, y = forward. */
  move: { x: number; y: number };
  run: boolean;
  /** Accumulated look delta in radians since the last frame. */
  look: { yaw: number; pitch: number };
}

export const createInput = (): InputState => ({ move: { x: 0, y: 0 }, run: false, look: { yaw: 0, pitch: 0 } });

const KEYS: Record<string, [number, number]> = {
  KeyW: [0, 1],
  ArrowUp: [0, 1],
  KeyS: [0, -1],
  ArrowDown: [0, -1],
  KeyA: [-1, 0],
  ArrowLeft: [-1, 0],
  KeyD: [1, 0],
  ArrowRight: [1, 0],
};

/** WASD / arrows / Shift. Returns a cleanup function. */
export function bindKeyboard(input: InputState): () => void {
  const down = new Set<string>();
  const update = () => {
    let x = 0;
    let y = 0;
    for (const code of down) {
      const k = KEYS[code];
      if (k) {
        x += k[0];
        y += k[1];
      }
    }
    const len = Math.hypot(x, y) || 1;
    input.move.x = x / len;
    input.move.y = y / len;
    input.run = down.has("ShiftLeft") || down.has("ShiftRight");
  };
  const onDown = (e: KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (KEYS[e.code] || e.code.startsWith("Shift")) {
      down.add(e.code);
      update();
      if (e.code.startsWith("Arrow")) e.preventDefault();
    }
  };
  const onUp = (e: KeyboardEvent) => {
    down.delete(e.code);
    update();
  };
  const onBlur = () => {
    down.clear();
    update();
  };
  window.addEventListener("keydown", onDown);
  window.addEventListener("keyup", onUp);
  window.addEventListener("blur", onBlur);
  return () => {
    window.removeEventListener("keydown", onDown);
    window.removeEventListener("keyup", onUp);
    window.removeEventListener("blur", onBlur);
  };
}

/**
 * Mouse look with pointer lock (click the scene to capture the mouse, Esc to
 * release) and drag-to-look for touch / unlocked mouse.
 */
export function bindLook(target: HTMLElement, input: InputState, sensitivity = 0.0022): () => void {
  let dragging = false;
  let last = { x: 0, y: 0 };
  const onClick = (e: Event) => {
    const touch = (e as PointerEvent).pointerType === "touch";
    if (!touch && document.pointerLockElement !== target) target.requestPointerLock?.();
  };
  const onMove = (e: PointerEvent) => {
    if (document.pointerLockElement === target) {
      input.look.yaw -= e.movementX * sensitivity;
      input.look.pitch -= e.movementY * sensitivity;
    } else if (dragging) {
      input.look.yaw -= (e.clientX - last.x) * sensitivity * 1.6;
      input.look.pitch -= (e.clientY - last.y) * sensitivity * 1.6;
      last = { x: e.clientX, y: e.clientY };
    }
  };
  const onDown = (e: PointerEvent) => {
    if (e.pointerType === "touch") {
      dragging = true;
      last = { x: e.clientX, y: e.clientY };
    }
  };
  const onUp = () => {
    dragging = false;
  };
  target.addEventListener("click", onClick);
  target.addEventListener("pointerdown", onDown);
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
  return () => {
    target.removeEventListener("click", onClick);
    target.removeEventListener("pointerdown", onDown);
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    if (document.pointerLockElement === target) document.exitPointerLock();
  };
}
