// Browser preview used by the hosted demo. Each visitor's queue stays in
// their own browser and is shared across tabs. The real app uses the API in
// api.ts against FastAPI and PostgreSQL.

type Row = {
  id: number;
  student_name: string;
  topic: string;
  status: "waiting" | "claimed" | "completed";
  claimed_by: string | null;
  claim_token: string | null;
};

type State = { rev: number; nextId: number; rows: Row[] };

export type PreviewEntry = {
  id: number;
  student_name: string;
  topic: string;
  status: "waiting" | "claimed";
  claimed_by: string | null;
  position: number | null;
  claim_token?: string;
};

const KEY = "taqueue-preview";
const CHANNEL = "taqueue-preview";

function empty(): State {
  return { rev: 0, nextId: 1, rows: [] };
}

function load(): State {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "");
    if (!parsed || !Array.isArray(parsed.rows)) return empty();
    return parsed as State;
  } catch {
    return empty();
  }
}

let channel: BroadcastChannel | null = null;

function publish(state: State) {
  localStorage.setItem(KEY, JSON.stringify(state));
  window.dispatchEvent(new Event("taqueue-preview"));
  channel ??= new BroadcastChannel(CHANNEL);
  channel.postMessage("update");
}

function change<T>(update: (state: State) => T): T {
  for (let attempt = 0; attempt < 5; attempt++) {
    const state = load();
    const rev = state.rev;
    const result = update(state);
    if (load().rev !== rev) continue;
    state.rev = rev + 1;
    publish(state);
    return result;
  }
  throw new Error("Please try again");
}

function visible(state: State): PreviewEntry[] {
  let position = 0;
  const queue: PreviewEntry[] = [];
  for (const row of state.rows) {
    if (row.status === "completed") continue;
    if (row.status === "waiting") position += 1;
    queue.push({
      id: row.id,
      student_name: row.student_name,
      topic: row.topic,
      status: row.status,
      claimed_by: row.claimed_by,
      position: row.status === "waiting" ? position : null,
    });
  }
  return queue;
}

export function previewQueue(): PreviewEntry[] {
  return visible(load());
}

export function subscribePreview(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener("taqueue-preview", onChange);
  const channel = new BroadcastChannel(CHANNEL);
  channel.onmessage = () => onChange();
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("taqueue-preview", onChange);
    channel.close();
  };
}

export function previewJoin(studentName: string, topic: string): PreviewEntry {
  const name = studentName.trim();
  if (!name) throw new Error("Name is required");
  return change((state) => {
    const row: Row = {
      id: state.nextId,
      student_name: name,
      topic: topic.trim(),
      status: "waiting",
      claimed_by: null,
      claim_token: null,
    };
    state.nextId += 1;
    state.rows.push(row);
    const entry = visible(state).find((item) => item.id === row.id);
    if (!entry) throw new Error("Could not join");
    return entry;
  });
}

export function previewClaim(id: number, taName: string): PreviewEntry {
  return change((state) => {
    const row = state.rows.find((item) => item.id === id);
    if (!row) throw new Error("No such queue entry");
    if (row.status !== "waiting") throw new Error(`Already claimed by ${row.claimed_by}`);
    row.status = "claimed";
    row.claimed_by = taName.trim();
    row.claim_token = crypto.randomUUID();
    const entry = visible(state).find((item) => item.id === row.id);
    if (!entry) throw new Error("No such queue entry");
    return { ...entry, claim_token: row.claim_token };
  });
}

export function previewComplete(id: number, claimToken: string) {
  change((state) => {
    const row = state.rows.find((item) => item.id === id);
    if (!row || row.status !== "claimed") throw new Error("Only a claimed session can be completed");
    if (row.claim_token !== claimToken) {
      throw new Error("Only the TA who claimed this session can complete it");
    }
    row.status = "completed";
  });
}

export function previewReset() {
  change((state) => {
    state.rows = [];
  });
}
