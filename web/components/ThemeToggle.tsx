"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

/**
 * Light, system, dark.
 *
 * Three states rather than two, because "system" is not a synonym for one of
 * the other two: a laptop that switches at sunset should take the console with
 * it, and a two-way toggle silently opts every user out of that. System stamps
 * nothing and lets the media query decide; the other two stamp `data-theme`,
 * which wins over the query in both directions.
 *
 * The console is used in two places with opposite needs — a NOC wall at 3am and
 * a client's boardroom at 3pm — so this is a real setting, not a preference
 * nobody changes.
 */

type Theme = "light" | "system" | "dark";

const KEY = "chetana.theme";

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "system", label: "System", icon: Monitor },
  { value: "dark", label: "Dark", icon: Moon },
];

function apply(theme: Theme) {
  const root = document.documentElement;

  // Suppress transitions for one frame. Otherwise every border, background and
  // shadow on the page animates at once and the switch reads as a rendering
  // fault rather than a deliberate change.
  root.classList.add("theming");
  window.setTimeout(() => root.classList.remove("theming"), 0);

  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function ThemeToggle() {
  // Start at "system" so the server and the first client render agree. The
  // stored value is read in the effect below; the inline script in the document
  // head has already applied it, so there is no flash despite the delay.
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(KEY);
      if (stored === "light" || stored === "dark") setTheme(stored);
    } catch {
      // Private window, or site data blocked. The default is correct anyway.
    }
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    apply(next);
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // The theme still applies for this session; it just will not persist.
    }
  }

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="flex items-center gap-0.5 rounded-lg border border-surface-border bg-surface-overlay p-0.5"
    >
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        const active = theme === option.value;
        return (
          <button
            key={option.value}
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            title={option.label}
            onClick={() => choose(option.value)}
            className={`rounded-md p-1.5 transition ${
              active
                ? "bg-surface-raised text-ink shadow-sm"
                : "text-ink-faint hover:text-ink-2"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </div>
  );
}
