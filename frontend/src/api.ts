// Everything the frontend knows about talking to the backend lives here.
// VITE_DEMO=true (the hosted page) keeps the queue in the browser instead.
import { useEffect, useState } from "react";
import {
  previewClaim,
  previewComplete,
  previewJoin,
  previewQueue,
  previewReset,
  subscribePreview,
} from "./demoQueue";

const PREVIEW = import.meta.env.VITE_DEMO === "true";

// Where the FastAPI server runs. Override with VITE_API_URL when deploying.
const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws") + "/ws"; // http -> ws, https -> wss

// The shape of one queue row, exactly as the backend sends it.
export type Entry = {
  id: number;
  student_name: string;
  topic: string;
  status: "waiting" | "claimed";
  claimed_by: string | null;
  position: number | null; // 1 = next; null once a TA has claimed them
  claim_token?: string; // only on the claim response; the live queue never includes it
};

// One helper for every POST. Throws the server's error message on 4xx/5xx.
async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(API_URL + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? "Request failed");
  return data;
}

export const joinQueue = (student_name: string, topic: string) =>
  PREVIEW ? Promise.resolve(previewJoin(student_name, topic)) : post<Entry>("/api/queue", { student_name, topic });

export const claimStudent = (id: number, ta_name: string) =>
  PREVIEW ? Promise.resolve(previewClaim(id, ta_name)) : post<Entry>(`/api/queue/${id}/claim`, { ta_name });

export const completeSession = (id: number, claim_token: string) =>
  PREVIEW ? Promise.resolve(previewComplete(id, claim_token)) : post(`/api/queue/${id}/complete`, { claim_token });

export const resetDemo = () => (PREVIEW ? Promise.resolve(previewReset()) : post("/api/demo/reset"));

/**
 * Live queue. Opens ONE WebSocket and keeps the latest queue in React state.
 * Every time the server pushes a message, React re-renders with the new queue.
 * If the connection drops (server restart, wifi), it retries after 1 second.
 */
export function useLiveQueue() {
  const [queue, setQueue] = useState<Entry[]>([]);
  const [connected, setConnected] = useState(PREVIEW);

  useEffect(() => {
    if (PREVIEW) {
      setQueue(previewQueue());
      return subscribePreview(() => setQueue(previewQueue()));
    }

    let socket: WebSocket;
    let retryTimer: number;
    let stopped = false;

    function connect() {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => setConnected(true);
      // The server always sends the WHOLE queue, so we just replace our copy.
      socket.onmessage = (event) => setQueue(JSON.parse(event.data).queue);
      socket.onclose = () => {
        setConnected(false);
        if (!stopped) retryTimer = window.setTimeout(connect, 1000);
      };
    }
    connect();

    // Cleanup when the component unmounts.
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      socket.close();
    };
  }, []);

  return { queue, connected };
}
