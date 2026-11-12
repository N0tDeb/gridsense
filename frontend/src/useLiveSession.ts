import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { LiveSession, PendingRequest, Receipt, SessionSummary } from './liveTypes';

const SESSION_KEY = 'gridsense.live.session';
const REQUEST_KEY = 'gridsense.live.request';
function saved(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function savedRequest(): PendingRequest | null {
  try {
    const item = JSON.parse(saved(REQUEST_KEY) ?? 'null');
    return item &&
      typeof item.label === 'string' &&
      typeof item.body?.request_id === 'string' &&
      /^\/sessions(?:\/[a-zA-Z0-9-]+\/actions)?$/.test(item.path)
      ? item
      : null;
  } catch {
    return null;
  }
}

/** The server owns time. Polling only reads committed revisions. */
export function useLiveSession(active: boolean) {
  const [id, setId] = useState<string | null>(() => saved(SESSION_KEY));
  const [session, setSession] = useState<LiveSession | null>(null);
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [pending, setPending] = useState<PendingRequest | null>(savedRequest);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [storageWarning, setStorageWarning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const owner = useRef(id);
  const inFlight = useRef(false);

  function persist(key: string, value: string | null) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      setStorageWarning(true);
    }
  }
  function choose(next: string) {
    owner.current = next;
    setId(next);
    setSession(null);
    setReadError(null);
    setError(null);
    setNotice(null);
    persist(SESSION_KEY, next);
  }
  const adopt = useCallback((value: LiveSession) => {
    if (owner.current !== value.id) return;
    setSession((old) => (old?.id === value.id && old.revision > value.revision ? old : value));
    setReadError(null);
  }, []);
  const refresh = useCallback(
    async (target: string) => {
      const value = await api<LiveSession>(`/sessions/${target}/simulation`);
      adopt(value);
      return value;
    },
    [adopt],
  );
  const refreshHistory = useCallback(async () => {
    setHistory(await api<SessionSummary[]>('/sessions'));
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    api<SessionSummary[]>('/sessions')
      .then((rows) => {
        if (!cancelled) setHistory(rows);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(`Cannot load saved sessions. ${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, [active, id]);

  useEffect(() => {
    if (!id || !active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<LiveSession>(`/sessions/${id}/simulation`);
        if (!cancelled) adopt(value);
      } catch (e) {
        if (!cancelled) setReadError(`Live state could not be refreshed. ${(e as Error).message}`);
      }
      if (!cancelled) timer = setTimeout(poll, 1000);
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, id, adopt]);

  function remember(request: PendingRequest | null) {
    setPending(request);
    persist(REQUEST_KEY, request ? JSON.stringify(request) : null);
  }
  async function send(request: PendingRequest) {
    if (inFlight.current) return false;
    inFlight.current = true;
    setWorking(request.label);
    setError(null);
    setNotice(null);
    remember(request);
    let accepted = false;
    try {
      const receipt = await api<Receipt>(request.path, request.body);
      accepted = true;
      remember(null);
      if (owner.current !== receipt.id) choose(receipt.id);
      setNotice(
        `Request accepted · ${request.label} · t=${receipt.at_s} s (revision ${receipt.revision}).`,
      );
      try {
        await refresh(receipt.id);
      } catch (e) {
        setReadError(
          `Request saved, but the current state could not be loaded. ${(e as Error).message}`,
        );
      }
      await refreshHistory().catch(() => {});
      return true;
    } catch (e) {
      const rejected = e instanceof ApiError && [400, 404, 409, 422].includes(e.status);
      if (rejected) {
        remember(null);
        setError(
          e.status === 409
            ? `The session changed or this action was rejected. ${e.message} Check the refreshed state before trying again.`
            : e.message,
        );
        if (owner.current)
          await refresh(owner.current).catch((failure: Error) => setReadError(failure.message));
      } else {
        setError(
          `Could not confirm whether the server saved this request. ${(e as Error).message} Use Retry same request to recover its receipt.`,
        );
      }
      return false;
    } finally {
      if (accepted) remember(null);
      inFlight.current = false;
      setWorking(null);
    }
  }
  function create(config: Record<string, unknown>) {
    return send({
      path: '/sessions',
      body: { request_id: crypto.randomUUID(), config },
      label: 'Create session',
    });
  }
  function mutate(operation: string, values: Record<string, unknown> = {}) {
    if (!session || pending || readError || inFlight.current) return Promise.resolve(false);
    return send({
      path: `/sessions/${session.id}/actions`,
      label:
        operation === 'schedule'
          ? 'Schedule events'
          : `${operation[0].toUpperCase()}${operation.slice(1)}`,
      body: {
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
        operation,
        ...values,
      },
    });
  }
  return {
    id,
    session,
    history,
    pending,
    working,
    error,
    readError,
    storageWarning,
    notice,
    choose,
    create,
    mutate,
    retry: () => (pending ? send(pending) : Promise.resolve(false)),
    refresh: () => (id ? refresh(id) : Promise.resolve(null)),
    dismissError: () => setError(null),
  };
}
