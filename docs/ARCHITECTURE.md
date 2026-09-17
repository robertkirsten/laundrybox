# ARGUS Scan System Architecture

- **Project:** LaundryBox prototype
- **Status:** Software-complete MVP; Pi and real-hardware acceptance pending
- **Topology:** U107 + two HX711/load cells → Teensy 4.1 → USB serial → Raspberry Pi

## Purpose and safety rule

ARGUS processes exactly one garment per cycle. It combines UHF RFID identity
with a stable aggregate weight, compares that weight with the active clean
reference in SQLite, and returns PASS or CHECK. PASS is permitted only when
every required input and subsystem is healthy; missing, stale, ambiguous, or
failed data always produces CHECK or UNAVAILABLE.

## Runtime topology

```text
U107 (EU band) ─ UART1 ─┐
                       ├─ Teensy 4.1 ─ USB CDC JSON lines ─ Raspberry Pi
2 × HX711/load cell ───┘                              │
                                                    Python service
                                           serial + state machine + SQLite
                                                    │          │
                                              SSE snapshots   REST feedback
                                                    └────┬─────┘
                                                  local React kiosk
```

The Teensy owns hardware acquisition and emits observations. The Pi owns the
cycle state machine, garment lookup, final decision, persistence, API, and UI.
There is currently no command or result channel back to the Teensy and no
hardware PASS/CHECK indicator.

## Wiring and firmware

| Teensy connection | Function |
|---|---|
| D0/RX1 ← U107 TXD | U107 receive |
| D1/TX1 → U107 RXD | U107 transmit |
| D2 / D3 | HX711 1 DOUT / SCK |
| D4 / D5 | HX711 2 DOUT / SCK |
| 5 V + GND | U107 power and common ground |
| 3.3 V + GND | HX711 power and common ground |
| device USB | Raspberry Pi USB host (`/dev/argus-teensy`, fallback `/dev/ttyACM0`) |

The integrated firmware currently leaves the U107 operating region and hopping
mode unchanged and only applies the configured transmit power. This preserves
the reader setup that works with the current antenna. Its actual frequencies,
antenna compatibility, and legal EU operation remain a hardware acceptance
gate; do not infer regulatory compliance from the firmware configuration.

The current two load-cell readings are combined into one logical `raw` count
and one `weight_g`. Load cell 2 has a temporary negative polarity correction
because it is mounted upside down. Tare and calibration run at startup. After
the firmware has observed at least 50 g, a subsequent residual below 30 g is
treated as a removal candidate. Three consecutive readings within a 2 g band
are averaged and applied as a new empty-box offset exactly once for that
loaded-to-empty transition. This compensates gradual box contamination and
load-cell drift without running a blocking tare. Final mechanics, calibration,
placement error, drift, load-cell diagnostics, and the 3 g threshold still
require physical validation.

The newline-delimited USB protocol is:

```json
{"v":1,"event":"boot"}
{"v":1,"t":12345,"raw":8342133,"weight_g":240.1,"auto_tare":false,"tare_residual_g":null,"tags":[{"epc":"E280...","rssi":210}]}
```

When the guarded re-zero is applied, `auto_tare` is `true` and
`tare_residual_g` contains the stable pre-correction residual for production
diagnostics. The reported `weight_g` already uses the new offset.

The backend enforces the protocol version, known field types, EPC format,
maximum line length, and bounded tag count. Unknown report and tag fields are
ignored for additive firmware compatibility; malformed known fields are still
discarded. USB removal invalidates an active cycle; reconnection requires a
stable empty box before a new garment can be accepted.

## Pi service

One FastAPI process and one Uvicorn worker own the serial port. The service
contains:

- a reconnecting PySerial reader;
- a fail-closed, one-garment state machine;
- strict Pydantic boundary models and validated settings;
- SQLAlchemy repositories and Alembic migrations;
- SQLite with foreign keys, WAL, busy timeout, and atomic cycle writes;
- complete revisioned snapshots over SSE and REST inspection feedback.

The operator flow is:

```text
UNAVAILABLE → stable empty → WAITING → garment detected → ACQUIRING
            → stable weight + EPC or timeout → PASS/CHECK
            → inspection feedback, replacement garment, or removal timeout → WAITING
```

The reference decision is:

```text
PASS if exactly one repeatedly observed known EPC has an active reference,
        the aggregate weight is stable and plausible,
        and abs(measured_g - reference_g) <= threshold_g
CHECK otherwise
```

Startup, Teensy restart, serial disconnect/staleness, null weight, reader
configuration failure, and database failure force UNAVAILABLE. Database errors
clear the active/result state and are not recovered in-process; systemd must
restart the service after the underlying database problem is corrected.

## Data and UI

SQLite stores station/operator identities, customers, wearers, garments,
versioned garment references, scan cycles, accumulated EPC observations,
inspection feedback, and configuration history. Weights are integer
milligrams. Mock master data comes from a packaged, Pydantic-validated CSV.

The local React/TanStack kiosk fetches the current snapshot and then follows
SSE updates. It never calculates decisions or counts locally. It displays
waiting, acquiring, PASS, CHECK, unavailable, and disconnected states, and
POSTs `nothing_found` or the selected found-item category for the current cycle.
It uses local system fonts and therefore has no runtime font-network dependency.

## Deployment and remaining acceptance

Deployment artifacts install backend and frontend systemd units, an optional
database-backup timer, environment configuration, and the udev serial symlink.
The remaining gates are physical, not assumed complete:

1. Install on the Pi and verify cold boot, kiosk startup, offline operation,
   service restart, database persistence, and real USB unplug/replug.
2. Confirm the reader is actually operating in the legal EU band and tune
   transmit power/read-zone containment with the final antenna and enclosure.
3. Calibrate the final load-cell mechanics with verified masses and characterize
   placement, drift, hysteresis, noise, stability, and empty-band thresholds.
4. Run labeled end-to-end garment trials against the ≤10 s requirement before
   disabling simulated input or relying on PASS operationally.

## References

1. [M5Stack U107 documentation](https://docs.m5stack.com/en/unit/uhf_rfid)
2. [M5Stack U107 serial protocol](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/842/Unit-RFID-UHF-Protocol-EN.pdf)
3. [PJRC Teensy 4.1 hardware information](https://www.pjrc.com/store/teensy41.html)
