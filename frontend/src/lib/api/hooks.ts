"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type ApiError, getAccessToken } from "./client";

interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/**
 * Minimal data-fetching hook. Auto-runs on mount and when `deps` change.
 * Returns a `reload` to manually refetch (e.g. after a mutation).
 *
 * Not SWR — intentionally tiny to avoid an extra dependency.
 */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> & {
  reload: () => void;
} {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true });
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: deps are caller-controlled; nonce drives manual reload
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef
      .current()
      .then((data) => {
        if (alive) setState({ data, error: null, loading: false });
      })
      .catch((err) => {
        if (alive) setState({ data: null, error: err as ApiError, loading: false });
      });
    return () => {
      alive = false;
    };
  }, [...deps, nonce]);

  return { ...state, reload };
}

/** True once the access cookie is present (used to gate fetches until auth ready). */
export function useAuthReady(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(Boolean(getAccessToken()));
  }, []);
  return ready;
}
