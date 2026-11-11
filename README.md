# TAQueue

A real-time office hours queue. Students join and watch their position change live. TAs see who is waiting, claim a student, and mark the session complete. If two TAs click "claim" on the same student at the same moment, exactly one of them gets the student.

Stack: React + TypeScript (Vite), Python FastAPI, PostgreSQL, WebSockets.

## Architecture

```
 Browser tab (React)                    FastAPI server                 PostgreSQL
 ───────────────────                    ──────────────                 ──────────
  click "Join"/"Claim"  ── HTTP POST ─▶  REST endpoint  ── SQL ──────▶  queue_entries
                                              │                         (one table)
                                              │ after COMMIT
  setQueue(newQueue)   ◀── WebSocket ───  broadcast_queue()
  React re-renders          push          sends the whole queue
                                          to every open tab
```

There are two channels between the browser and the server, and they do different jobs.

HTTP is for actions. The browser asks for something (join, claim, complete) and gets one answer back, including an error code if it failed.

The WebSocket is for news. The server pushes the current queue to every open tab whenever anything changes. The browser never sends anything over it.

PostgreSQL is the only place the truth lives. The server keeps no queue in memory. That is why a server restart loses nothing, and why the database is the right place to stop two TAs claiming the same student.

## Files

```
backend/
  app/main.py        the whole server: setup, WebSocket, 6 endpoints (about 200 lines)
  app/schema.sql     the one table
  tests/conftest.py  test database setup
  tests/test_queue.py 12 tests, including the concurrency tests
frontend/
  src/api.ts         fetch calls + the useLiveQueue WebSocket hook
  src/App.tsx        student view and TA view
docker-compose.yml   PostgreSQL (and optionally the whole stack)
```

## Setup

You need Python 3.11+, Node 18+, and PostgreSQL (through Docker, or installed with Homebrew).

### 1. Database

With Docker Desktop running:

```bash
docker compose up -d db
```

Or without Docker, on a Mac:

```bash
brew install postgresql@16
brew services start postgresql@16
createdb taqueue
export DATABASE_URL="postgresql://$(whoami)@localhost:5432/taqueue"
```

(With Homebrew you must keep that `export` in every terminal that runs the backend or the tests.)

### 2. Backend (terminal 1)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The table is created on startup. Open http://localhost:8000/docs to see and try every endpoint.

### 3. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 4. Tests (terminal 3)

```bash
cd backend
source .venv/bin/activate
pytest -v
```

The tests create and use a separate database, `taqueue_test`, so they don't touch your demo data.

### Whole stack in Docker

```bash
docker compose up --build
```

This path was not run when the project was built (no Docker daemon was available). The database-only command above is the tested route. Run this once yourself before you rely on it.

## Demo script (2 minutes)

1. Open four browser tabs at http://localhost:5173. Put them side by side if you can.
2. Tabs 1 and 2: stay on "I'm a student". Join as Alice, then as Bob. Alice shows position 1, Bob shows 2.
3. Tabs 3 and 4: click "I'm a TA". Type TA-1 in one and TA-2 in the other. Both show two waiting students.
4. In the TA-1 tab, claim Alice. Without any refresh: Alice's tab says TA-1 is helping her, Bob's tab drops to position 1, and the TA-2 tab shows Alice as in progress.
5. Show the race in a terminal. Add a student, then fire eight claims at once:

```bash
curl -s -X POST localhost:8000/api/queue -H 'content-type: application/json' -d '{"student_name":"Race"}'
# use the id from the response in place of 3
for i in 1 2 3 4 5 6 7 8; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/queue/3/claim \
    -H 'content-type: application/json' -d "{\"ta_name\":\"TA-$i\"}" &
done; wait
```

You get one `200` and seven `409`.

6. Run `pytest -v` and point at `test_ten_simultaneous_claims_exactly_one_wins`.

## API

| Method | Path | Body | Success | Errors | What it does |
|---|---|---|---|---|---|
| POST | `/api/queue` | `{student_name, topic?}` | 201 + entry | 422 bad input | Student joins the queue |
| GET | `/api/queue` | | 200 + list | | Everyone waiting or being helped, oldest first |
| GET | `/api/queue/{id}` | | 200 + entry | 404 | One entry with its position |
| POST | `/api/queue/{id}/claim` | `{ta_name}` | 200 + entry, including `claim_token` | 404, 409 already claimed | TA claims a student (row lock). The token is only in this response. |
| POST | `/api/queue/{id}/complete` | `{claim_token}` | 200 | 403 wrong token, 409 not claimed | Ends the session. The token from claim is required; the TA's typed name is not checked. |
| POST | `/api/demo/reset` | | 200 | | DEMO ONLY: deletes every entry |
| WS | `/ws` | | | | Server pushes `{type: "queue_update", queue: [...]}` on connect and after every change |

An entry looks like this:

```json
{"id": 1, "student_name": "Alice", "topic": "recursion", "status": "waiting", "claimed_by": null, "position": 1}
```

`position` is 1 for the next student to be helped and `null` once a TA has claimed them.

## Database schema

One table, `queue_entries`. A row is one request for help.

| Column | Type | Why it is there |
|---|---|---|
| `id` | SERIAL PRIMARY KEY | Auto-incrementing. Lower id means joined earlier, so `ORDER BY id` is the FIFO order. |
| `student_name` | TEXT NOT NULL | Who is waiting |
| `topic` | TEXT | What they need help with |
| `status` | TEXT + CHECK | `waiting`, `claimed` or `completed`. The CHECK constraint makes the database reject any other value. |
| `claimed_by` | TEXT, nullable | TA name. NULL until claimed. A label, not a password. |
| `claim_token` | TEXT, nullable | Secret created at claim time. Returned once to the caller. Omitted from the queue and from WebSocket messages. |
| `created_at`, `claimed_at`, `completed_at` | TIMESTAMPTZ | Timestamps for each step. Not shown in the UI yet; they would give wait-time stats later. |

A row moves one way: `waiting` to `claimed` to `completed`.

Position is not stored. It is computed on read: your position is how many `waiting` rows have a smaller id than yours, plus one. If it were stored, every claim would have to rewrite every row behind it, and the numbers could drift out of sync.

Completed rows are kept, and the queue query filters them out. That leaves a history.

There is an index on `status` because every read filters on it.

## Demo-only shortcuts

These are labelled `DEMO ONLY` in the code and the UI.

- No login. The role is a button and the TA name is typed text. Anyone can call any endpoint.
- Only the browser tab that clicked Claim can mark that session complete. The server checks a random token from that claim, not the typed name, so another TA cannot finish it by typing the first TA's name. This is not a login. Anyone who can read that tab's storage can still copy the token. Real accounts would replace it.
- CORS allows every origin.
- `POST /api/demo/reset` wipes the queue.
- One queue. There are no courses or rooms.
- The list of open WebSockets lives in the memory of one server process, so this runs correctly as a single process only.

## Test results

Run on PostgreSQL 16.15, Python 3.13, 10 November 2026: 12 passed, 0 failed.

| Test | Result |
|---|---|
| test_join_and_position | passed |
| test_ta_sees_waiting_students_in_order | passed |
| test_claim_moves_everyone_else_up | passed |
| test_second_claim_is_rejected | passed |
| test_complete_removes_from_queue | passed |
| test_cannot_complete_a_student_nobody_claimed | passed |
| test_another_ta_cannot_complete_my_session | passed |
| test_claim_unknown_entry_is_404 | passed |
| test_empty_name_is_rejected | passed |
| test_ten_simultaneous_claims_exactly_one_wins | passed |
| test_without_the_lock_several_tas_win | passed |
| test_websocket_receives_queue_updates | passed |

Two more checks were done by hand and are not part of `pytest`:

- With `FOR UPDATE` deleted from the claim query, `test_ten_simultaneous_claims_exactly_one_wins` failed 15 times out of 15 (all ten TAs got a 200). So the test really does depend on the lock.
- The UI was driven in a real browser (Chromium, four tabs) against the running backend and frontend. Join, live position, live TA list, claim, complete, refresh-keeps-your-place, and two TAs clicking claim together (one got "Already claimed by TA-1") all worked.

Not verified: the full `docker compose up --build` path, anything on macOS, and deployment. Nothing is deployed.
