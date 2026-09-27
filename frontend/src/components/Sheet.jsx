// Bottom sheet with three snap points: peek (120 px), half (52%), full (92%). Drag the handle or tap it.
import { useRef } from "react";

const ORDER = ["peek", "half", "full"];
export function snapHeight(snap) {
  const H = window.innerHeight - 64;
  return snap === "peek" ? 120 : snap === "full" ? Math.round(H * 0.92) : Math.round(H * 0.52);
}

export default function Sheet({ snap = "half", onSnap, children, foot, header, noTabs, style }) {
  const drag = useRef(null);
  const el = useRef(null);
  const down = (e) => {
    drag.current = { y: e.clientY, h: el.current.getBoundingClientRect().height, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
    el.current.style.transition = "none";
  };
  const move = (e) => {
    if (!drag.current) return;
    const dy = e.clientY - drag.current.y;
    if (Math.abs(dy) > 4) drag.current.moved = true;
    el.current.style.height = `${Math.max(90, drag.current.h - dy)}px`;
  };
  const up = (e) => {
    if (!drag.current) return;
    const h = el.current.getBoundingClientRect().height;
    el.current.style.transition = "";
    el.current.style.height = "";
    if (!drag.current.moved) {
      onSnap?.(ORDER[(ORDER.indexOf(snap) + 1) % 3]);
    } else {
      const best = ORDER.map((s) => [s, Math.abs(snapHeight(s) - h)]).sort((a, b) => a[1] - b[1])[0][0];
      onSnap?.(best);
    }
    drag.current = null;
  };
  return (
    <section ref={el} className={`sheet ${noTabs ? "no-tabs" : ""}`} style={{ height: snapHeight(snap), ...style }}>
      <div className="sheet-handle" onPointerDown={down} onPointerMove={move} onPointerUp={up} role="button" aria-label="Resize panel"><span /></div>
      {header}
      <div className="sheet-body">{children}</div>
      {foot && <div className="sheet-foot">{foot}</div>}
    </section>
  );
}
