import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

/**
 * Loads data when the screen is focused, optionally re-polling every
 * `intervalMs` while it stays focused. Errors are kept so the screen can show
 * them; the last good data stays on screen during a failed refresh.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  intervalMs?: number | null,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fetcherRef = useRef(fetcher);
  const alive = useRef(true);
  // Callers pass a fresh closure each render; loads always use the latest one.
  useLayoutEffect(() => {
    fetcherRef.current = fetcher;
  });
  const depKey = JSON.stringify(deps);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const result = await fetcherRef.current();
      if (!alive.current) return;
      setData(result);
      setError(null);
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
      if (!intervalMs) return undefined;
      const id = setInterval(() => load(), intervalMs);
      return () => clearInterval(id);
      // depKey is deliberate: a change in the caller's inputs (ticker, range) reloads.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [load, intervalMs, depKey]),
  );

  return { data, setData, error, loading, refreshing, reload: () => load(true), refresh: () => load(false) };
}
