"use client";

import { useCallback, useState } from "react";
import { ApprovalRequired, api } from "./api";
import type { ApprovalRequest } from "./types";

export interface ActionState {
  busy: boolean;
  error: string | null;
  parked: ApprovalRequest | null;
  message: string | null;
}

const IDLE: ActionState = { busy: false, error: null, parked: null, message: null };

/**
 * Runs a gated write against the BFF.
 *
 * A 202 with an approval request is not an error — the gateway parked the
 * action and is telling the console who has to release it. The caller renders
 * `parked` as a banner instead of a failure.
 */
export function useAction() {
  const [state, setState] = useState<ActionState>(IDLE);

  const run = useCallback(
    async <T,>(
      path: string,
      options: { method?: string; body?: unknown; successMessage?: string } = {},
    ): Promise<T | null> => {
      setState({ ...IDLE, busy: true });
      try {
        const result = await api<T>(path, {
          method: options.method ?? "POST",
          body: options.body ?? {},
        });
        setState({ ...IDLE, message: options.successMessage ?? "Done" });
        return result;
      } catch (err) {
        if (err instanceof ApprovalRequired) {
          setState({ ...IDLE, parked: err.approval, message: err.message });
          return null;
        }
        setState({ ...IDLE, error: err instanceof Error ? err.message : "Action failed" });
        return null;
      }
    },
    [],
  );

  const reset = useCallback(() => setState(IDLE), []);

  return { ...state, run, reset };
}
