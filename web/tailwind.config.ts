import type { Config } from "tailwindcss";

/**
 * Every colour is a CSS variable, so the whole console re-themes from one place
 * and the light and dark values live side by side in globals.css.
 *
 * The values are `<r> <g> <b>` triplets rather than hex, wrapped here in
 * `rgb(... / <alpha-value>)`. That is what keeps Tailwind's opacity modifiers
 * working — `bg-accent/10`, `border-sev-critical/40` — which the console uses
 * everywhere. A variable holding `#7c3aed` would break all of them silently:
 * the class compiles, the colour just never applies.
 *
 * ---------------------------------------------------------------------------
 * The `slate` override deserves an explanation, because it is unusual.
 *
 * This console was built dark-only, and its pages say `text-slate-200` for
 * primary text, `text-slate-500` for muted, and so on — twenty-one pages of
 * literal greys chosen against a dark ground. On a light ground `text-slate-200`
 * is invisible.
 *
 * Rather than edit twenty-one files by hand and risk a typo in each, `slate` is
 * remapped onto the ink scale. Every existing page becomes theme-correct with
 * no edit at all, and the greys stay meaningful: 200 is primary ink in both
 * themes rather than a fixed grey that only works in one.
 *
 * It is a migration aid, not the end state. As pages are redesigned they move
 * to the semantic names (`text-ink`, `text-ink-muted`) and the mapping matters
 * less each time.
 * ---------------------------------------------------------------------------
 */
const rgb = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          // `base` is the old name for the page plane; kept so existing
          // markup keeps working while pages migrate to `canvas`.
          base: rgb("--canvas"),
          canvas: rgb("--canvas"),
          raised: rgb("--raised"),
          overlay: rgb("--overlay"),
          border: rgb("--border"),
          firm: rgb("--border-firm"),
        },
        ink: {
          DEFAULT: rgb("--ink"),
          2: rgb("--ink-2"),
          muted: rgb("--ink-muted"),
          faint: rgb("--ink-faint"),
        },
        accent: {
          DEFAULT: rgb("--accent"),
          hi: rgb("--accent-hi"),
          ink: rgb("--accent-ink"),
          muted: rgb("--accent-hi"),
        },
        sev: {
          critical: rgb("--sev-critical"),
          high: rgb("--sev-high"),
          warning: rgb("--sev-warning"),
          low: rgb("--sev-low"),
          // Info is the absence of urgency, so it is ink rather than a hue.
          // Giving it one put it within ΔE 14 of the accent in dark mode.
          info: rgb("--ink-muted"),
        },
        good: rgb("--good"),
        series: {
          1: rgb("--series-1"),
          2: rgb("--series-2"),
          3: rgb("--series-3"),
        },
        // Intertec's own red. The logo lockup and nothing else: it measures
        // ΔE 8.1 from critical-severity red, under the 15 floor, so the two
        // must never carry meaning in the same place.
        intertec: rgb("--intertec"),

        // --- migration aid; see the note above ---
        slate: {
          50: rgb("--ink"),
          100: rgb("--ink"),
          200: rgb("--ink"),
          300: rgb("--ink-2"),
          400: rgb("--ink-2"),
          500: rgb("--ink-muted"),
          600: rgb("--ink-faint"),
          700: rgb("--border-firm"),
          800: rgb("--overlay"),
          900: rgb("--raised"),
          950: rgb("--canvas"),
        },
        emerald: { 400: rgb("--good"), 500: rgb("--good"), 700: rgb("--good") },
        amber: { 400: rgb("--sev-warning"), 500: rgb("--sev-warning"), 700: rgb("--sev-warning"), 800: rgb("--sev-warning") },
        rose: { 400: rgb("--sev-critical"), 500: rgb("--sev-critical"), 700: rgb("--sev-critical") },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "0.625rem",
        xl: "0.75rem",
      },
      boxShadow: {
        // Two elevations, both token-driven so dark mode gets real depth
        // rather than a light-mode shadow nobody can see.
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: {
        "fade-up": "fade-up 180ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
