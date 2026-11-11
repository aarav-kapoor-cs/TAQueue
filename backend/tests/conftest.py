"""
Test setup. Tests run against a REAL PostgreSQL, in a separate database
called taqueue_test, because row locking can't be tested with a fake database.
"""
import os

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/taqueue")
TEST_URL = BASE_URL.rsplit("/", 1)[0] + "/taqueue_test"

# Point the app at the test database BEFORE it is imported.
os.environ["DATABASE_URL"] = TEST_URL

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    """A fresh, empty queue and an HTTP client wired straight into the app."""
    # Create the test database the first time.
    admin = await asyncpg.connect(BASE_URL.rsplit("/", 1)[0] + "/postgres")
    if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'taqueue_test'"):
        await admin.execute("CREATE DATABASE taqueue_test")
    await admin.close()

    # lifespan_context runs the app's startup (pool + schema) and shutdown.
    async with app.router.lifespan_context(app):
        async with app.state.pool.acquire() as conn:
            await conn.execute("TRUNCATE queue_entries RESTART IDENTITY")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
