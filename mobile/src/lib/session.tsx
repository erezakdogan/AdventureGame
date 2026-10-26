import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { loadConnection, saveConnection, setActiveConnection, type Connection } from './api';

interface SessionValue {
  ready: boolean;
  connection: Connection | null;
  connect: (conn: Connection) => Promise<void>;
  disconnect: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);

  useEffect(() => {
    loadConnection().then((conn) => {
      setActiveConnection(conn);
      setConnection(conn);
      setReady(true);
    });
  }, []);

  const connect = useCallback(async (conn: Connection) => {
    await saveConnection(conn);
    setActiveConnection(conn);
    setConnection(conn);
  }, []);

  const disconnect = useCallback(async () => {
    await saveConnection(null);
    setActiveConnection(null);
    setConnection(null);
  }, []);

  const value = useMemo(() => ({ ready, connection, connect, disconnect }), [ready, connection, connect, disconnect]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession outside SessionProvider');
  return ctx;
}
