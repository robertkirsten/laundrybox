# ARGUS MVP Implementation Plan

- **Status:** Software implementation validated locally; Pi/hardware acceptance pending
- **Last updated:** 2026-09-16
- **Source of truth:** Update the checkboxes and implementation log as work progresses.
- **Repositories:** `laundrybox.nosync` (firmware/backend) and `smart-shaft.nosync` (frontend)

## 1. Approved scope and decisions

- Process **exactly one garment per cycle**. Preserve data needed for a later batch/removal experiment, but do not implement batch mode in the MVP.
- Teensy 4.1 reads the U107 and load-cell hardware and streams newline-delimited JSON to the Raspberry Pi over **USB serial**.
- A single Python 3 service owns serial ingestion, cycle logic, decisions, SQLite, and the local API.
- Use **FastAPI**, **Pydantic v2/pydantic-settings**, **SQLAlchemy 2/Alembic**, **PySerial**, and **SQLite** in WAL mode. Run one Uvicorn worker so only one process owns the serial port.
- The React/TanStack frontend runs locally on the Pi. It receives complete display snapshots through **Server-Sent Events (SSE)** and uses REST for feedback.
- Use a configurable initial decision threshold of **±3.0 g**, with no contamination correction. Any uncertainty produces CHECK; the system never shows PASS during startup or failure.
- Garment/customer/wearer/operator/station data and reference weights are mock database records for the MVP.
- Reference weights are seeded through a script/CSV initially; a clean-reference capture UI is deferred.
- Inspection-dialog selections are stored as ground-truth feedback and never overwrite the original automated decision.
- Until the final load-cell arrangement is connected and calibrated, use simulated weights for integration; hardware mode reports UNAVAILABLE rather than PASS when weight is missing.

## 2. Target architecture

```text
U107 + HX711/load cell(s)
          │
       Teensy 4.1
          │ USB serial: JSON lines
          ▼
  serial reader/reconnector
          │
  one-garment state machine
          │
   decision + SQLite transaction
          │
    current display snapshot
       ┌──┴───────────┐
       │              │
GET /api/v1/events    REST /api/v1/*
       │ SSE          │
       └──── local React kiosk ──── inspection feedback
```

Backend location: `laundrybox.nosync/backend/`. Frontend integration remains in the separate Lovable-connected `smart-shaft.nosync` repository; do not rewrite its published Git history.

## 3. Hardware and protocol baseline

Wiring recorded from `hardware/laundrybox_wiring.png`:

| Connection | Pins |
|---|---|
| U107 UART | U107 TXD → Teensy D0/RX1; U107 RXD ← Teensy D1/TX1 |
| U107 power | 5 V and common GND |
| HX711 | VCC → Teensy 3.3 V, GND → GND, DT → D2, SCK → D3 |
| Pi link | Teensy device USB → Raspberry Pi USB host |

The attached drawing records the original one-cell wiring. The current experimental
firmware also uses D4/D5 for a second HX711; that arrangement remains subject to the
Phase 6 mechanical and calibration decision.

Power gate: verify the U107 5 V rail during RF transmission. Do not assume the Pi/Teensy USB path can safely supply every peripheral configuration. If a regulated peripheral supply is added, share ground and avoid feeding Teensy VUSB and VIN simultaneously without the documented separation.

Current Teensy reports:

```json
{"v":1,"t":12345,"raw":8342133,"weight_g":601.2,"auto_tare":false,"tare_residual_g":null,"tags":[{"epc":"E280...","rssi":210}]}
```

It emits `boot`; the backend also accepts a future `rfid_config_error` self-test event. The backend must validate version/size/types, timestamp reports with the Pi clock, tolerate malformed lines, and reconnect after USB removal. Use `/dev/ttyACM0` initially and add a udev-managed `/dev/argus-teensy` symlink before deployment.

Use strict Pydantic v2 models at every external boundary: Teensy messages, REST requests/responses, SSE snapshots, mock fixtures, and environment configuration. Reject unexpected fields where appropriate and model protocol versions explicitly. Keep SQLAlchemy models separate for persistence, and keep cycle/decision business rules in services rather than Pydantic validators.

Future multiple-load-cell firmware should still expose one logical `weight_g` and `stable` value, with optional per-cell diagnostics and a calibration version. The backend decision must not depend on the physical cell count.

## 4. Runtime behavior

State machine:

```text
STARTING → WAITING_EMPTY → ACQUIRING → EVALUATING
                                      → DISPLAYING_RESULT
                                      → WAITING_REMOVAL → WAITING_EMPTY
Any state → UNAVAILABLE/CHECK on required-data or hardware failure
```

PASS requires all of the following within the acquisition deadline:

1. Stable calibrated weight in the supported range.
2. Exactly one consistently observed EPC.
3. Known active garment and active reference weight.
4. Healthy RFID, scale, serial link, database, and configuration.
5. `abs(measured_g - reference_g) <= threshold_g`.

Missing/multiple tags, missing reference, null/unstable/implausible weight, timeout, serial loss, database error, or restart produces CHECK/UNAVAILABLE. Removal is confirmed by stable return to the empty-weight band, not by one missed RFID read. A scan count increments once for each persisted cycle with one known garment, whether its decision is PASS or CHECK.

## 5. SQLite model

- `stations`: configured shaft/station identity.
- `operators`: mock operator identity.
- `customers`, `wearers`: UI master data.
- `garments`: EPC, item/article identifiers, name, size, manufacture year/week, customer and wearer.
- `garment_references`: versioned reference weights; one active reference per garment.
- `scan_cycles`: timestamps, measured/reference/difference weights, decision, reason, versions and optional future `batch_id`.
- `tag_observations`: EPC, RSSI, first/last seen and read count per cycle.
- `inspection_feedback`: `nothing_found`, `scissors`, `keys`, `money`, `paper`, `pen`, `tissues`, `headphones`, `tool`, `other`, plus optional note and timestamp.
- `configuration_history`: threshold and algorithm/calibration identifiers used for traceability.

Store weights as integer milligrams. Enable foreign keys, WAL, busy timeout, migrations, and atomic cycle/decision commits. Store the database at `/var/lib/argus/argus.sqlite3` in deployment.

## 6. Backend/frontend contract

Endpoints:

```text
GET  /api/v1/health
GET  /api/v1/state
GET  /api/v1/events                         # SSE
POST /api/v1/cycles/{cycle_id}/inspection
```

SSE emits `event: state` with a monotonically increasing revision and the **complete current display snapshot**. It sends a snapshot immediately on connection, sends keepalives, and relies on `EventSource` auto-reconnect. `GET /state` is the fallback and diagnostic endpoint.

Snapshot content:

- lifecycle/status: waiting, acquiring, pass, check, unavailable;
- cycle ID, revision, decision reason and timestamp;
- scanned count, station and operator;
- garment/customer/wearer/article/manufacture metadata;
- reference, measured and difference weights;
- hardware/backend health needed for an unavailable display.

Frontend changes:

- Replace hard-coded `GARMENT`, operator and scan count with the snapshot.
- Preserve the existing three screens and item-selection dialog.
- Show automatic CHECK immediately; allow manual inspection feedback from the PASS screen as designed.
- POST `nothing_found` or the selected item against the displayed cycle ID; prevent duplicate submission.
- Do not increment counts locally or show green before a valid backend decision.
- Add waiting, acquiring, unavailable and disconnected states.
- Remove remote font dependencies for offline operation (local system fonts are acceptable).
- Configure a loopback API base or local proxy; restrict CORS to the actual local frontend origin if ports differ.

## 7. Implementation phases and gates

### Phase 0 — Contract and skeleton

- [x] Create backend package, Pydantic Settings configuration, application lifespan and structured logging.
- [x] Define strict Pydantic serial/API/snapshot models, separate SQLAlchemy database models, and example fixtures.
- [x] Add mock-data seed and serial-replay tools.

**Gate:** service starts without hardware, exposes health/state, and reports UNAVAILABLE.

### Phase 1 — Database and decision core

- [x] Add migrations and seed station/operator/garment/reference fixtures.
- [x] Implement repository layer, state machine and configurable ±3 g decision.
- [x] Unit-test thresholds, missing/multiple tags, missing reference/weight, timeout and restart.

**Gate:** deterministic replay produces the expected persisted PASS/CHECK cycles.

### Phase 2 — USB serial integration

- [x] Implement bounded line parsing, protocol validation and reconnect/backoff.
- [x] Handle boot/configuration faults and accumulate EPC observations over a cycle.
- [x] Add udev rule/documentation for `/dev/argus-teensy`.

**Gate:** automated disconnect/reconnect and fail-closed paths are verified; physical USB unplug/replug on the Pi remains an acceptance test.

### Phase 3 — API and SSE

- [x] Implement health/state/SSE/inspection endpoints and OpenAPI examples.
- [x] Broadcast full revisioned snapshots with initial state and reconnect behavior.
- [x] Integration-test database commits, SSE updates and idempotent feedback.

**Gate:** a diagnostic client follows a full simulated cycle and records feedback.

### Phase 4 — Frontend integration

- [x] Add typed API client and SSE hook to `smart-shaft.nosync`.
- [x] Bind all displayed fields and decision states to backend data.
- [x] Wire the existing inspection flow to feedback POSTs.
- [x] Remove network font dependencies and add waiting/acquiring/unavailable/disconnected UI states.

**Gate:** simulated RFID events update the kiosk without refresh and reload restores the current snapshot; a real U107/tag event remains a hardware acceptance test.

### Phase 5 — Pi deployment

- [x] Verify the frontend's current Pi build/start command and wrap frontend/backend in systemd.
- [x] Run backend as an unprivileged `dialout` user, one worker, bound to loopback.
- [x] Configure paths, permissions, restart policy, journald logging and database backup procedure.
- [ ] Verify cold boot, offline operation, service restart and Chromium kiosk startup.

**Gate:** unattended reboot returns to a safe operational kiosk with persistent history.

### Phase 6 — Weight hardware and acceptance

- [ ] Finalize one-versus-multiple-load-cell mechanics and Teensy aggregation.
- [ ] Calibrate/tare, establish stability and empty-band limits, and version the calibration.
- [ ] Validate known masses, placement, drift and the initial 3 g threshold.
- [ ] Run end-to-end garment tests against the ≤10 s requirement and record inspection ground truth.

**Gate:** real hardware meets the agreed accuracy/safety criteria; simulated weights are disabled.

### Deferred — Batch/removal experiment

Use the stored tag observations and optional `batch_id` to test 2/3/5 garments. Infer a removal only from a stable before/after weight step plus a high-confidence EPC set difference. Never treat one missed read as removal. Enable batch mode only after measured read completeness and removal latency satisfy an explicitly approved acceptance criterion.

## 8. Definition of done

- [x] Local kiosk updates automatically in simulation and survives frontend/SSE reconnects.
- [x] Every completed scan and feedback action is traceable in SQLite.
- [x] Known stable garment within threshold shows PASS; excess/deficit or uncertainty shows CHECK.
- [x] Automated boot, disconnect, null weight, unknown/multiple EPC, missing reference, RFID configuration fault, and database-error paths never show PASS.
- [ ] Physical USB unplug/replug and Pi reboot recover without manual database repair.
- [x] Automated tests and a repeatable Pi installation/deployment procedure are included.
- [x] Implementation and architecture documents reflect the actual USB topology and protocol.
- [ ] Real reader/load-cell acceptance passes with the final mechanics and calibrated thresholds.

## 9. Progress log

| Date | Phase | Result |
|---|---|---|
| 2026-09-16 | Planning | Consolidated firmware, backend, frontend, database, deployment and hardware plan drafted for approval. |
| 2026-09-16 | Approval | User approved the plan; Phase 0 started. |
| 2026-09-16 | Phases 0–3 | Backend, SQLite schema, one-garment state machine, USB reader, REST/SSE, fixtures, backup and 17 automated tests completed. |
| 2026-09-16 | Phase 4 | Existing kiosk connected to live snapshots and feedback; production Pi build passed and the full simulated UI flow was visually verified. |
| 2026-09-16 | Phase 5 | systemd, udev, environment, backup timer and Pi installation artifacts added; actual Pi installation/reboot remains pending. |
| 2026-09-16 | Firmware | Integrated U107/HX711 firmware and separate HX711 calibration firmware both compiled successfully for Teensy 4.1. |
| 2026-09-16 | Validation audit | Replaced hard-coded garment fixtures with validated CSV, made database and RFID configuration faults fail closed, required stable near-zero removal, added feedback-category display state, and reconciled architecture documentation. |
| 2026-09-16 | Validation results | 26 backend tests and Ruff passed; the built wheel (including CSV) passed all tests under target Python 3.11; a clean Alembic migration/seed and live REST/SSE cycles passed; frontend lint had 0 errors and both builds passed; both Teensy projects compiled. Physical Pi/U107/load-cell gates remain open as listed above. |
| 2026-09-16 | RFID rollback | Removed the experimental U107 Europe-region/readback/hopping and strict frame changes after the current antenna failed with that configuration. Restored the previous `begin → setTxPower → poll` behavior; frequency/legal validation remains open. |
| 2026-09-16 | Operations | Added the unified `./argus` development/install/deploy workflow, installed `argusctl` operations, staged production releases with rollback, safe serial inspection, development-database migration, and the database-backed EPC/garment/IST/SOLL scan log. |
