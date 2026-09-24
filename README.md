# TAQueue — Real-Time Office Hours Queue

A web application for managing university TA and professor office hours. Students join a live queue, describe their question, see their position and estimated wait, and receive a notification when they are next. TAs manage requests and monitor the session.

**Status: planned / repository setup.** This README describes the intended implementation. The application has not been built yet.

## Stack
React · TypeScript · FastAPI · PostgreSQL · WebSockets · Docker

## MVP roadmap
- [ ] Authentication with student and TA roles
- [ ] Open and close office hours queues
- [ ] Join a queue with a help topic
- [ ] Live queue positions and estimated wait times
- [ ] Notify students when they are next
- [ ] Call, skip, and resolve requests
- [ ] Prevent simultaneous claims of the same student by multiple TAs
- [ ] Basic session statistics
- [ ] Docker setup and documented REST and WebSocket APIs

## Design and validation plan
PostgreSQL will hold the authoritative queue state. Claims will use atomic database transactions and row-level locking so concurrent TA requests cannot claim the same entry. WebSocket updates will reflect committed changes, and clients will refresh queue state after reconnecting.

Tests will cover role permissions, queue lifecycle, simultaneous claims against PostgreSQL, and reconnect behavior. Wait-time estimates will be labeled as estimates and based on observed session service times when enough data is available.

## Engineering focus
Full-stack development, REST APIs, real-time systems, authentication and roles, database design, concurrency, and testing.

## Running the project
Implementation and setup instructions are pending. No working demo or test results are claimed yet.
