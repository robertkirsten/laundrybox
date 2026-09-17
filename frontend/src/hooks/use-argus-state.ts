import { useEffect, useState } from "react";
import {
  fetchState,
  openStateEvents,
  type DisplaySnapshot,
} from "@/lib/argus-api";

export type BackendConnection = "connecting" | "connected" | "disconnected";

export function useArgusState() {
  const [snapshot, setSnapshot] = useState<DisplaySnapshot | null>(null);
  const [connection, setConnection] = useState<BackendConnection>("connecting");

  useEffect(() => {
    const abort = new AbortController();
    let active = true;

    const accept = (next: DisplaySnapshot) => {
      if (!active) return;
      setSnapshot((current) =>
        current === null || next.revision >= current.revision ? next : current,
      );
    };

    void fetchState(abort.signal)
      .then(accept)
      .catch((error: unknown) => {
        if (
          active &&
          !(error instanceof DOMException && error.name === "AbortError")
        ) {
          setConnection("disconnected");
        }
      });

    const events = openStateEvents(accept, (connected) => {
      if (active) setConnection(connected ? "connected" : "disconnected");
    });

    return () => {
      active = false;
      abort.abort();
      events.close();
    };
  }, []);

  return { snapshot, connection };
}
