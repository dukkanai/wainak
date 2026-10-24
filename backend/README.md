# Wainak backend foundation

**Synthetic development only. Do not use real personal data or expose this server.**

Python 3.11+ standard library; no package installation, mail provider, external API,
database connection, payment service or persistent credential is required. Server
checks were performed on Python 3.14.4. The domain rules and JSON contract are the
deliverable; WSGI is only a bounded local preview adapter, not a production server.

## Run tests from the repository root

```sh
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -v
python3 contracts/build_contract.py --check
python3 -m compileall -q backend contracts/build_contract.py
```

Tests construct fresh in-memory services, make no network requests and do not use
Docker, existing database volumes, mail, purchases or real accounts. Concurrency
tests verify a single-process lock, **not** multi-process/PostgreSQL transactions.

For an explicitly requested local manual preview only:

```sh
PYTHONPATH=backend python3 -m wainak --development --port 8089
```

It binds **127.0.0.1 only**, rejects untrusted Host and any browser Origin, disables
access logs and returns `Cache-Control: no-store`. It has no production mode,
cross-origin API, reverse-proxy configuration, container, systemd service or startup
integration. It is not started automatically by tests or installation. Stopping
the process loses every synthetic account and session.

## Read before integrating

- [`../contracts/README.md`](../contracts/README.md): DTOs, HTTP operations, errors and consent states.
- [`../contracts/phase1.openapi.json`](../contracts/phase1.openapi.json): OpenAPI 3.1 contract.
- [`../docs/phase1-architecture.md`](../docs/phase1-architecture.md): scope, rationale, safeguards, next milestones and blockers.

The UI may implement a fake repository against these contracts. It must not label
simulated verification/payment/delivery as real. The API does **not** send or store
dialogue answers, photos, voice, evidence uploads or messages. Requesting unknown
endpoints or submitting content fields fails closed rather than silently persisting
them. Reporting is a local metadata simulation, not submission to a live team.
