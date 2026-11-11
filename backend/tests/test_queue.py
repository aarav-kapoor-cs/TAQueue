import asyncio

from fastapi.testclient import TestClient

from app.main import app


async def join(client, name):
    response = await client.post("/api/queue", json={"student_name": name, "topic": "help"})
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------- basic flow

async def test_join_and_position(client):
    alice = await join(client, "Alice")
    bob = await join(client, "Bob")
    assert alice["position"] == 1
    assert bob["position"] == 2

    response = await client.get(f"/api/queue/{bob['id']}")
    assert response.json()["position"] == 2


async def test_ta_sees_waiting_students_in_order(client):
    await join(client, "Alice")
    await join(client, "Bob")
    queue = (await client.get("/api/queue")).json()
    assert [e["student_name"] for e in queue] == ["Alice", "Bob"]
    assert all(e["status"] == "waiting" for e in queue)


async def test_claim_moves_everyone_else_up(client):
    alice = await join(client, "Alice")
    bob = await join(client, "Bob")

    response = await client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": "TA-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "claimed"
    assert response.json()["claimed_by"] == "TA-1"
    assert response.json()["claim_token"]

    # The live queue and the public lookup must not include the secret.
    public = (await client.get("/api/queue")).json()
    assert "claim_token" not in public[0]
    looked_up = (await client.get(f"/api/queue/{alice['id']}")).json()
    assert "claim_token" not in looked_up

    bob_now = (await client.get(f"/api/queue/{bob['id']}")).json()
    assert bob_now["position"] == 1


async def test_second_claim_is_rejected(client):
    alice = await join(client, "Alice")
    await client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": "TA-1"})
    response = await client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": "TA-2"})
    assert response.status_code == 409
    assert "TA-1" in response.json()["detail"]


async def test_complete_removes_from_queue(client):
    alice = await join(client, "Alice")
    claimed = (await client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": "TA-1"})).json()
    response = await client.post(
        f"/api/queue/{alice['id']}/complete", json={"claim_token": claimed["claim_token"]}
    )
    assert response.status_code == 200
    assert (await client.get("/api/queue")).json() == []


async def test_cannot_complete_a_student_nobody_claimed(client):
    alice = await join(client, "Alice")
    response = await client.post(
        f"/api/queue/{alice['id']}/complete", json={"claim_token": "not-a-real-ticket"}
    )
    assert response.status_code == 409


async def test_another_ta_cannot_complete_my_session(client):
    alice = await join(client, "Alice")
    await client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": "TA-1"})

    # Typing TA-1's name is not enough. A different tab does not have the ticket.
    by_name = await client.post(f"/api/queue/{alice['id']}/complete", json={"ta_name": "TA-1"})
    assert by_name.status_code == 422
    guessed = await client.post(
        f"/api/queue/{alice['id']}/complete", json={"claim_token": "guessed-ticket"}
    )
    assert guessed.status_code == 403

    # Alice is still claimed by TA-1.
    entry = (await client.get(f"/api/queue/{alice['id']}")).json()
    assert entry["status"] == "claimed"
    assert entry["claimed_by"] == "TA-1"


async def test_claim_unknown_entry_is_404(client):
    response = await client.post("/api/queue/999/claim", json={"ta_name": "TA-1"})
    assert response.status_code == 404


async def test_empty_name_is_rejected(client):
    response = await client.post("/api/queue", json={"student_name": ""})
    assert response.status_code == 422


# --------------------------------------------------------------- concurrency

async def test_ten_simultaneous_claims_exactly_one_wins(client):
    """
    THE IMPORTANT TEST. Ten TAs hit "claim" on the same student at the same
    moment. asyncio.gather starts all ten requests before any has finished,
    and each one uses its own database connection from the pool.
    Exactly one must get 200. The other nine must get 409.
    """
    alice = await join(client, "Alice")

    responses = await asyncio.gather(
        *[
            client.post(f"/api/queue/{alice['id']}/claim", json={"ta_name": f"TA-{i}"})
            for i in range(10)
        ]
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 9

    # The database must agree with the one TA who was told "you got it".
    winner = next(r for r in responses if r.status_code == 200).json()["claimed_by"]
    entry = (await client.get(f"/api/queue/{alice['id']}")).json()
    assert entry["claimed_by"] == winner


async def unsafe_claim(pool, entry_id, ta_name):
    """
    TEST-ONLY. The buggy version of claim: same logic, but NO 'FOR UPDATE'.
    The sleep stands in for normal network/CPU delay between read and write.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            status = await conn.fetchval(
                "SELECT status FROM queue_entries WHERE id = $1", entry_id
            )
            await asyncio.sleep(0.05)
            if status != "waiting":
                return False
            await conn.execute(
                "UPDATE queue_entries SET status = 'claimed', claimed_by = $2 WHERE id = $1",
                entry_id,
                ta_name,
            )
            return True


async def test_without_the_lock_several_tas_win(client):
    """
    Proves the race condition is real, so the test above isn't passing by luck.
    Without FOR UPDATE, every TA reads 'waiting' and every TA believes it won.
    """
    alice = await join(client, "Alice")
    results = await asyncio.gather(
        *[unsafe_claim(app.state.pool, alice["id"], f"TA-{i}") for i in range(5)]
    )
    assert sum(results) > 1  # more than one "winner" = the bug


# ---------------------------------------------------------------- websockets

def test_websocket_receives_queue_updates():
    """A connected browser gets the queue on connect and after every change."""
    with TestClient(app) as tc:  # TestClient runs startup/shutdown for us
        tc.post("/api/demo/reset")
        with tc.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first == {"type": "queue_update", "queue": []}

            created = tc.post("/api/queue", json={"student_name": "Alice", "topic": "recursion"}).json()
            after_join = ws.receive_json()
            assert after_join["queue"][0]["student_name"] == "Alice"
            assert after_join["queue"][0]["position"] == 1

            claimed = tc.post(f"/api/queue/{created['id']}/claim", json={"ta_name": "TA-1"}).json()
            after_claim = ws.receive_json()
            assert after_claim["queue"][0]["status"] == "claimed"
            assert after_claim["queue"][0]["claimed_by"] == "TA-1"
            assert "claim_token" not in after_claim["queue"][0]

            tc.post(f"/api/queue/{created['id']}/complete", json={"claim_token": claimed["claim_token"]})
            after_complete = ws.receive_json()
            assert after_complete["queue"] == []
