"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { login, setToken } from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";

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
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4 py-10">
      {/* The theme control belongs here too: whoever opens the console on a
          projector needs it before they can sign in, not after. */}
      <div className="absolute right-5 top-5">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-sm animate-fade-up">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="mb-3.5 flex h-12 w-12 items-center justify-center rounded-2xl bg-intertec shadow-md">
            <ShieldCheck className="h-6 w-6 text-white" />
          </span>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-ink">Chetana AI</h1>
          <p className="mt-1.5 text-[11px] font-semibold uppercase tracking-[0.11em] text-ink-muted">
            by Intertec
          </p>
        </div>

        <form onSubmit={onSubmit} className="card space-y-4 p-6 shadow-md">
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
            <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/10 px-3 py-2 text-sm text-sev-critical">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
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
