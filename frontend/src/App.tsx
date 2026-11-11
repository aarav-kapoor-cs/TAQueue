import { useState } from "react";
import { Entry, claimStudent, completeSession, joinQueue, resetDemo, useLiveQueue } from "./api";

export default function App() {
  const [role, setRole] = useState<"student" | "ta">("student");
  const { queue, connected } = useLiveQueue();

  return (
    <>
      <header>
        <h1>TAQueue</h1>
        <p className="lede">Office hours, one shared queue.</p>
      </header>
      <nav>
        <button disabled={role === "student"} onClick={() => setRole("student")}>Student</button>
        <button disabled={role === "ta"} onClick={() => setRole("ta")}>TA</button>
        <span className={connected ? "live" : "muted"}>{connected ? "Live" : "Reconnecting…"}</span>
      </nav>
      {role === "student" ? <StudentView queue={queue} /> : <TAView queue={queue} />}
    </>
  );
}

function StudentView({ queue }: { queue: Entry[] }) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  // Remember which queue entry is mine. sessionStorage survives a refresh
  // and is separate per browser tab, so two tabs can be two students.
  const [myId, setMyId] = useState<number | null>(() => {
    const saved = sessionStorage.getItem("myEntryId");
    return saved ? Number(saved) : null;
  });
  const [error, setError] = useState("");

  async function handleJoin(event: React.FormEvent) {
    event.preventDefault(); // stop the browser from reloading the page
    try {
      const entry = await joinQueue(name, topic);
      sessionStorage.setItem("myEntryId", String(entry.id));
      setMyId(entry.id);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function leaveScreen() {
    sessionStorage.removeItem("myEntryId");
    setMyId(null);
  }

  if (myId === null) {
    return (
      <form onSubmit={handleJoin}>
        <h2>Join the queue</h2>
        <input placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input placeholder="What do you need help with?" value={topic} onChange={(e) => setTopic(e.target.value)} />
        <button type="submit">Join</button>
        {error && <p className="error">{error}</p>}
      </form>
    );
  }

  // Find my row in the live queue. This re-runs on every WebSocket update.
  const me = queue.find((entry) => entry.id === myId);

  if (!me) {
    // Completed sessions are no longer in the queue the server sends.
    return (
      <>
        <h2>Your session is finished</h2>
        <button onClick={leaveScreen}>Join again</button>
      </>
    );
  }
  if (me.status === "claimed") {
    return (
      <>
        <h2>{me.student_name}, it's your turn!</h2>
        <p><b>{me.claimed_by}</b> is helping you now.</p>
      </>
    );
  }
  return (
    <>
      <h2>{me.student_name}, you're in the queue</h2>
      <p>Your position:</p>
      <p className="big" data-testid="position">{me.position}</p>
      <p className="muted">This updates by itself. No need to refresh.</p>
    </>
  );
}

// Secret from the claim response, kept in this tab only. sessionStorage is
// separate per tab, so a second tab acting as another TA never has it.
const TICKETS_KEY = "taClaimTickets";

function readTickets(): Record<string, string> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(TICKETS_KEY) ?? "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

function TAView({ queue }: { queue: Entry[] }) {
  const [taName, setTaName] = useState("");
  const [tickets, setTickets] = useState<Record<string, string>>(readTickets);
  const [error, setError] = useState("");

  const waiting = queue.filter((entry) => entry.status === "waiting");
  const inProgress = queue.filter((entry) => entry.status === "claimed");

  // Run an API call and show the server's message if it fails
  // (for example "Already claimed by TA-1" when another TA was faster).
  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <h2>TA dashboard</h2>
      <input className="ta-name" placeholder="Your name" value={taName} onChange={(e) => setTaName(e.target.value)} />
      <p className="muted">Mark complete shows only in the tab that claimed the student.</p>
      {error && <p className="error" data-testid="error">{error}</p>}

      <h3>Waiting ({waiting.length})</h3>
      <ol>
        {waiting.map((entry) => (
          <li key={entry.id}>
            <b>{entry.student_name}</b> {entry.topic && <>— {entry.topic}</>}{" "}
            <button
              disabled={!taName.trim()}
              onClick={() =>
                run(async () => {
                  const claimed = await claimStudent(entry.id, taName);
                  if (!claimed.claim_token) return;
                  const next = { ...readTickets(), [String(claimed.id)]: claimed.claim_token };
                  sessionStorage.setItem(TICKETS_KEY, JSON.stringify(next));
                  setTickets(next);
                })
              }
            >
              Claim
            </button>
          </li>
        ))}
      </ol>
      {waiting.length === 0 && <p className="muted">Nobody is waiting.</p>}

      <h3>In progress ({inProgress.length})</h3>
      <ul>
        {inProgress.map((entry) => {
          const ticket = tickets[String(entry.id)];
          return (
            <li key={entry.id}>
              <b>{entry.student_name}</b> with {entry.claimed_by}{" "}
              {/* This tab claimed them, so it holds the secret. The server checks it too. */}
              {ticket && (
                <button
                  onClick={() =>
                    run(async () => {
                      await completeSession(entry.id, ticket);
                      const next = { ...readTickets() };
                      delete next[String(entry.id)];
                      sessionStorage.setItem(TICKETS_KEY, JSON.stringify(next));
                      setTickets(next);
                    })
                  }
                >
                  Mark complete
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <p>
        <button className="quiet" onClick={() => run(resetDemo)}>Clear queue</button>
      </p>
    </>
  );
}
