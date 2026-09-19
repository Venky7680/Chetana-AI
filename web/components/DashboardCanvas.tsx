"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { GripVertical, Trash2 } from "lucide-react";
import type { Widget } from "@/lib/dashboard";
import { COLS, ROW_HEIGHT, MARGIN, settle } from "@/lib/dashboard";

/**
 * The drag-and-resize grid, written by hand.
 *
 * Keep's canvas is react-grid-layout at 24 columns and a 30px row. This uses
 * the same geometry — deliberately, so a layout saved here lands in the same
 * cells when Keep renders it — but not the same library: react-grid-layout has
 * not declared React 19 support, and the part that is actually needed is the
 * compaction algorithm in lib/dashboard, which is shorter than the integration
 * would have been and, living outside a component, can be tested directly.
 *
 * Two things here are not in Keep's canvas and are worth keeping. Widgets are
 * movable from the keyboard, because a grid that can only be arranged by
 * dragging cannot be arranged at all by someone using a keyboard. And the drag
 * runs on pointer events rather than mouse events, so it works on a touch
 * screen, which is where an on-call engineer often is.
 */

type Gesture =
  | { kind: "drag" | "resize"; id: string; startX: number; startY: number; from: Widget }
  | null;

export function DashboardCanvas({
  widgets,
  editing,
  onChange,
  onRemove,
  renderWidget,
}: {
  widgets: Widget[];
  editing: boolean;
  onChange: (next: Widget[]) => void;
  onRemove: (id: string) => void;
  renderWidget: (widget: Widget) => React.ReactNode;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1200);
  const [gesture, setGesture] = useState<Gesture>(null);
  const [preview, setPreview] = useState<Widget[] | null>(null);

  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  const live = preview ?? widgets;
  const colWidth = Math.max((width - MARGIN * (COLS + 1)) / COLS, 1);

  const box = useCallback(
    (w: Widget) => ({
      left: MARGIN + w.x * (colWidth + MARGIN),
      top: MARGIN + w.y * (ROW_HEIGHT + MARGIN),
      width: w.w * colWidth + (w.w - 1) * MARGIN,
      height: w.h * ROW_HEIGHT + (w.h - 1) * MARGIN,
    }),
    [colWidth],
  );

  // ------------------------------------------------------------- gestures
  function begin(kind: "drag" | "resize", widget: Widget, event: React.PointerEvent) {
    if (!editing) return;
    event.preventDefault();
    (event.target as Element).setPointerCapture?.(event.pointerId);
    setGesture({ kind, id: widget.i, startX: event.clientX, startY: event.clientY, from: widget });
  }

  useEffect(() => {
    if (!gesture) return;

    function move(event: PointerEvent) {
      if (!gesture) return;
      const dx = Math.round((event.clientX - gesture.startX) / (colWidth + MARGIN));
      const dy = Math.round((event.clientY - gesture.startY) / (ROW_HEIGHT + MARGIN));
      const from = gesture.from;

      const next =
        gesture.kind === "drag"
          ? {
              ...from,
              x: Math.min(Math.max(from.x + dx, 0), COLS - from.w),
              y: Math.max(from.y + dy, 0),
            }
          : {
              ...from,
              w: Math.min(Math.max(from.w + dx, from.minW ?? 3), COLS - from.x),
              h: Math.max(from.h + dy, from.minH ?? 3),
            };

      setPreview(settle(widgets.map((w) => (w.i === gesture.id ? next : w)), gesture.id));
    }

    function end() {
      setPreview((current) => {
        if (current) onChange(current);
        return null;
      });
      setGesture(null);
    }

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
  }, [gesture, widgets, colWidth, onChange]);

  /** Arrows move, shift+arrows resize. The only route in without a pointer. */
  function onKeyDown(event: React.KeyboardEvent, widget: Widget) {
    if (!editing) return;
    const step: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const delta = step[event.key];
    if (!delta) return;
    event.preventDefault();
    const [dx, dy] = delta;
    const next = event.shiftKey
      ? {
          ...widget,
          w: Math.min(Math.max(widget.w + dx, widget.minW ?? 3), COLS - widget.x),
          h: Math.max(widget.h + dy, widget.minH ?? 3),
        }
      : {
          ...widget,
          x: Math.min(Math.max(widget.x + dx, 0), COLS - widget.w),
          y: Math.max(widget.y + dy, 0),
        };
    onChange(settle(widgets.map((w) => (w.i === widget.i ? next : w)), widget.i));
  }

  const rows = live.reduce((max, w) => Math.max(max, w.y + w.h), 0);

  return (
    <div
      ref={host}
      className="relative w-full"
      style={{ height: MARGIN + rows * (ROW_HEIGHT + MARGIN) }}
    >
      {editing ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl opacity-40"
          style={{
            backgroundImage:
              "repeating-linear-gradient(to right, rgb(var(--border)) 0 1px, transparent 1px 100%)",
            backgroundSize: `${colWidth + MARGIN}px 100%`,
            backgroundPosition: `${MARGIN}px 0`,
          }}
        />
      ) : null}

      {live.map((widget) => {
        const dragging = gesture?.id === widget.i;
        return (
          <section
            key={widget.i}
            className={`absolute flex flex-col overflow-hidden rounded-xl border bg-surface-raised ${
              dragging
                ? "z-20 border-accent shadow-2xl"
                : "border-surface-border transition-[left,top,width,height] duration-150"
            }`}
            style={box(widget)}
          >
            <header className="flex items-center gap-1.5 border-b border-surface-border px-3 py-2">
              {editing ? (
                <button
                  aria-label={`Move ${widget.name}. Arrow keys move, shift and arrow keys resize.`}
                  onPointerDown={(e) => begin("drag", widget, e)}
                  onKeyDown={(e) => onKeyDown(e, widget)}
                  className="-ml-1 cursor-grab touch-none rounded p-0.5 text-ink-faint hover:text-ink-2 focus:outline-none focus:ring-1 focus:ring-accent active:cursor-grabbing"
                >
                  <GripVertical className="h-3.5 w-3.5" />
                </button>
              ) : null}
              <h3 className="truncate text-xs font-medium text-ink-2">{widget.name}</h3>
              {editing ? (
                <button
                  onClick={() => onRemove(widget.i)}
                  aria-label={`Remove ${widget.name}`}
                  className="ml-auto rounded p-0.5 text-ink-faint hover:text-sev-critical"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </header>

            <div className="min-h-0 flex-1 overflow-auto p-3">{renderWidget(widget)}</div>

            {editing ? (
              <button
                aria-label={`Resize ${widget.name}`}
                onPointerDown={(e) => begin("resize", widget, e)}
                className="absolute bottom-0 right-0 h-4 w-4 cursor-se-resize touch-none"
              >
                <svg viewBox="0 0 10 10" className="h-full w-full fill-slate-600">
                  <path d="M9 1v8H1z" opacity="0.5" />
                </svg>
              </button>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
