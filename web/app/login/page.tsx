"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";
import { login, setToken } from "@/lib/api";

/**
 * Sign in, on the marketing site's ground.
 *
 * The page the visitor just came from is a night sky with a glass card on it;
 * arriving at a flat white form would read as landing on a different product.
 * The sky and scrim are supplied by body::before/::after in globals.css, so
 * this page only has to place the card on them.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await login(email, password);
      setToken(session.access_token);
      router.replace("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4 py-10">
      {/* A way back to the site. Someone who clicked Sign In to look around
          should not have to reach for the browser's back button. */}
      <Link
        href="/"
        className="absolute left-5 top-5 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-4 py-2 text-sm font-medium text-ink-2 transition hover:border-white/35 hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </Link>

      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          {/* The site's mark, at the size it uses in its own nav. */}
          <span className="relative mb-4 block h-[34px] w-[34px] rounded-full border-4 border-[#3B82F6] shadow-[0_0_20px_rgba(59,130,246,.75)]">
            <span className="absolute inset-[6px] rounded-full bg-[#60A5FA]" />
          </span>
          <h1 className="text-[26px] font-bold tracking-[-0.02em] text-white">Chetana AI</h1>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
            AI Operations for a brighter tomorrow
          </p>
        </div>

        <form onSubmit={onSubmit} className="card space-y-4 p-6">
          <div>
            <label className="label mb-1.5 block" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label mb-1.5 block" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error ? (
            <p className="rounded-xl border border-sev-critical/30 bg-sev-critical/10 px-3 py-2 text-sm text-sev-critical">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary w-full justify-center py-2.5" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Sign in
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-ink-faint">
          Intertec Systems · Keep is the system of record
        </p>
      </div>
    </main>
  );
}
