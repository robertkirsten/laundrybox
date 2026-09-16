# ARGUS backend

Local FastAPI service for the LaundryBox prototype. It owns USB serial input,
the one-garment cycle, SQLite persistence, decision logic, SSE display state,
and inspection feedback.

## Development

```sh
cd backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
argus-backend seed
argus-backend serve --reload
```

OpenAPI is available at `http://127.0.0.1:8000/docs`.

For frontend development without hardware:

```sh
ARGUS_SERIAL_ENABLED=false ARGUS_ENABLE_DEBUG_INGEST=true argus-backend serve
argus-backend replay scripts/example-cycle.jsonl --hold 5
```

The debug ingest endpoint is disabled by default and the server binds to
loopback by default.

Mock garment/reference data is loaded from the packaged, Pydantic-validated
`src/argus_backend/fixtures/mock_garments.csv`. Set `ARGUS_MOCK_DATA_PATH` to
an absolute CSV path to supply a deployment-specific fixture file.

## Raspberry Pi

Production units, the udev rule, environment file, verified daily backup, and
step-by-step installation are in [`deploy/`](deploy/INSTALL_PI.md). The service
uses one worker and exclusively owns `/dev/argus-teensy`; the serial reader
automatically reconnects when the Teensy is unplugged and reattached.
