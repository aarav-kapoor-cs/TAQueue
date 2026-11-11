"""
TAQueue backend: the whole server is this one file.

Read it top to bottom:
  1. Setup       - connect to PostgreSQL when the server starts
  2. WebSockets  - remember who is connected, push the queue to all of them
  3. REST API    - join / view / claim / complete
"""
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/taqueue"
SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


# ---------------------------------------------------------------- 1. Setup

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after)."""
    # A pool keeps database connections open and lends one to each request.
    # Opening a new connection per request would be slow. min_size=10 opens
    # all ten up front, so ten simultaneous requests really do run at once.
    app.state.pool = await asyncpg.create_pool(
        os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), min_size=10, max_size=10
    )
    async with app.state.pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)  # create the table if it doesn't exist
    yield
    await app.state.pool.close()


app = FastAPI(title="TAQueue", lifespan=lifespan)

# The React dev server runs on http://localhost:5173 and this API on :8000.
# Browsers block cross-origin requests unless the server allows them (CORS).
# DEMO ONLY: "*" allows any website. In production, list your real frontend URL.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class JoinRequest(BaseModel):
    student_name: str = Field(min_length=1, max_length=50)
    topic: str = Field(default="", max_length=200)


class TARequest(BaseModel):
    # DEMO ONLY: there is no login. The TA just types a name and we trust it.
    # The name is a label. It is not what authorizes "mark complete".
    ta_name: str = Field(min_length=1, max_length=50)


class CompleteRequest(BaseModel):
    # Secret returned only by the claim call. Knowing the TA's display name
    # is not enough; a different tab never received this value.
    claim_token: str = Field(min_length=1, max_length=100)


async def get_queue() -> list[dict]:
    """Everyone who is waiting or being helped, oldest first, with positions."""
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, student_name, topic, status, claimed_by
            FROM queue_entries
            WHERE status IN ('waiting', 'claimed')
            ORDER BY id
            """
        )
    queue = []
    position = 0
    for row in rows:
        entry = dict(row)
        if entry["status"] == "waiting":
            position += 1
            entry["position"] = position  # 1 = next to be helped
        else:
            entry["position"] = None  # already with a TA
        queue.append(entry)
    return queue


# ----------------------------------------------------------- 2. WebSockets

# Every open browser tab holds one WebSocket. We keep them all in this set.
# NOTE: this lives in the memory of ONE server process. With several server
# processes you would need Redis pub/sub (or Postgres LISTEN/NOTIFY) so that
# a change handled by server A also reaches the sockets held by server B.
connected_clients: set[WebSocket] = set()


async def broadcast_queue() -> None:
    """Send the full, current queue to every connected browser."""
    message = {"type": "queue_update", "queue": await get_queue()}
    for ws in list(connected_clients):
        try:
            await ws.send_json(message)
        except Exception:
            connected_clients.discard(ws)  # that tab is gone; forget it


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    try:
        # Send the current queue right away so a new tab isn't blank.
        await ws.send_json({"type": "queue_update", "queue": await get_queue()})
        # The browser never sends us anything. This loop just keeps the
        # connection open; it raises WebSocketDisconnect when the tab closes.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(ws)


# ------------------------------------------------------------- 3. REST API

@app.post("/api/queue", status_code=201)
async def join_queue(body: JoinRequest):
    """Feature 1: a student joins the queue."""
    async with app.state.pool.acquire() as conn:
        entry_id = await conn.fetchval(
            "INSERT INTO queue_entries (student_name, topic) VALUES ($1, $2) RETURNING id",
            body.student_name.strip(),
            body.topic.strip(),
        )
    await broadcast_queue()
    return await get_entry(entry_id)


@app.get("/api/queue")
async def list_queue():
    """Feature 3: a TA sees the waiting (and currently claimed) students."""
    return await get_queue()


@app.get("/api/queue/{entry_id}")
async def get_entry(entry_id: int):
    """Feature 2: a student looks up their own entry and position."""
    for entry in await get_queue():
        if entry["id"] == entry_id:
            return entry
    raise HTTPException(404, "Not in the queue (never joined, or already completed)")


@app.post("/api/queue/{entry_id}/claim")
async def claim_student(entry_id: int, body: TARequest):
    """
    Features 4 + 7: a TA claims a student. Two TAs must never get the same one.

    The danger ("check-then-act" race):
        TA A reads the row: status = waiting
        TA B reads the row: status = waiting     <- both think it's free
        TA A writes claimed_by = A
        TA B writes claimed_by = B               <- B silently overwrites A

    The fix: SELECT ... FOR UPDATE inside a transaction. The first transaction
    to reach the row LOCKS it. The second one has to WAIT at its SELECT until
    the first commits, and then it reads the new status ('claimed') and backs off.
    """
    async with app.state.pool.acquire() as conn:
        async with conn.transaction():  # BEGIN ... COMMIT (or ROLLBACK on error)
            row = await conn.fetchrow(
                "SELECT status, claimed_by FROM queue_entries WHERE id = $1 FOR UPDATE",
                entry_id,
            )
            if row is None:
                raise HTTPException(404, "No such queue entry")
            if row["status"] != "waiting":
                # 409 Conflict = "your request was fine, but the state has changed"
                raise HTTPException(409, f"Already claimed by {row['claimed_by']}")
            # Unguessable secret. We return it once, to this caller only.
            # get_queue() does not select this column, so other tabs never see it.
            claim_token = secrets.token_urlsafe(24)
            await conn.execute(
                """
                UPDATE queue_entries
                SET status = 'claimed', claimed_by = $2, claimed_at = now(), claim_token = $3
                WHERE id = $1
                """,
                entry_id,
                body.ta_name.strip(),
                claim_token,
            )
        # Leaving the `transaction()` block COMMITs and releases the row lock.
    await broadcast_queue()  # only after the commit, so we never announce a claim that rolled back
    entry = await get_entry(entry_id)
    entry["claim_token"] = claim_token
    return entry


@app.post("/api/queue/{entry_id}/complete")
async def complete_session(entry_id: int, body: CompleteRequest):
    """
    Feature 5: mark a session finished. It then drops out of the queue.
    Only the tab that claimed the student can complete the session.

    This one uses the other safe pattern: a single conditional UPDATE.
    The WHERE clause makes the check and the write one atomic statement,
    so there is no gap for another request to sneak into.
    DEMO ONLY: this is not a login. It stops another TA, including one who
    types the first TA's name. It does not stop someone who copied the secret
    out of the first tab.
    """
    async with app.state.pool.acquire() as conn:
        updated_id = await conn.fetchval(
            """
            UPDATE queue_entries
            SET status = 'completed', completed_at = now()
            WHERE id = $1 AND status = 'claimed' AND claim_token = $2
            RETURNING id
            """,
            entry_id,
            body.claim_token,
        )
        if updated_id is None:
            # Nothing was updated. Look at the row to explain why.
            row = await conn.fetchrow(
                "SELECT status FROM queue_entries WHERE id = $1", entry_id
            )
            if row is not None and row["status"] == "claimed":
                # 403 Forbidden = "you are not allowed to do this"
                raise HTTPException(403, "Only the TA who claimed this session can complete it")
            raise HTTPException(409, "Only a claimed session can be completed")
    await broadcast_queue()
    return {"id": entry_id, "status": "completed"}


@app.post("/api/demo/reset")
async def demo_reset():
    """DEMO ONLY: wipe the queue so you can restart a demo. Remove in production."""
    async with app.state.pool.acquire() as conn:
        await conn.execute("TRUNCATE queue_entries RESTART IDENTITY")
    await broadcast_queue()
    return {"ok": True}
