# LedgerCore

A backend project exploring consistent ledger updates under concurrent requests, with database transactions and an auditable history.

**Status: planning / initial repository setup.** This repository contains a roadmap; the API and concurrency demonstration are not implemented yet.

## Planned stack
Python, FastAPI, PostgreSQL, SQL, Docker, pytest.

## MVP roadmap
- [ ] Accounts and ledger entry schema with database constraints
- [ ] REST APIs for accounts and transactions
- [ ] Atomic transfers and fixed-precision monetary values
- [ ] Row-level locking using SELECT ... FOR UPDATE
- [ ] Consistent lock ordering and retry handling
- [ ] Idempotency for retried requests
- [ ] Audit history and reconciliation
- [ ] SQL analytics using JOINs, CTEs, and window functions
- [ ] Indexes and query plan analysis
- [ ] PostgreSQL integration tests for concurrent updates
- [ ] Docker setup and API documentation

## Planned concurrency demonstration
Reproduce a lost-update bug in an isolated example, then compare it with a transaction-protected implementation under the same workload. Verify balance invariants and record reproducible results.

## Validation plan
Test rollback on failure, insufficient funds, duplicate requests, and simultaneous transfers against a real PostgreSQL database. Performance and correctness results will be published only after the tests run.
