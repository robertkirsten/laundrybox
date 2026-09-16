# Raspberry Pi runbook

This is the day-to-day operating guide for the ARGUS LaundryBox prototype on
the Raspberry Pi. It covers the Teensy USB connection, Python/FastAPI backend,
local frontend, health checks, logs, and direct serial diagnostics.

The production installation uses these locations:

- backend source: `/opt/argus/laundrybox/backend`
- frontend source: `/opt/argus/smart-shaft`
- Python environment: `/opt/argus/venv`
- backend configuration: `/etc/argus/backend.env`
- SQLite database: `/var/lib/argus/argus.sqlite3`
- frontend: `http://127.0.0.1:3000`
- backend API: `http://127.0.0.1:8000`

The installation procedure itself is in
[`../backend/deploy/INSTALL_PI.md`](../backend/deploy/INSTALL_PI.md).

## Normal startup

1. Connect the Teensy to a Raspberry Pi USB port.
2. Turn on the Raspberry Pi and log in using Pi Connect or a local terminal.
3. Confirm that Linux detected the Teensy:

   ```sh
   ls -l /dev/argus-teensy /dev/ttyACM0 2>/dev/null
   ```

   `/dev/argus-teensy` is the preferred stable name. `/dev/ttyACM0` is the
   configured fallback and is sufficient for development.

4. Start the backend and frontend:

   ```sh
   sudo systemctl start argus-backend argus-frontend
   ```

5. Confirm that both services are running:

   ```sh
   systemctl --no-pager --full status argus-backend argus-frontend
   ```

6. Open `http://127.0.0.1:3000` in Chromium on the Pi. The frontend receives
   proactive state updates from the backend through SSE; it does not need to
   poll the API.

The services are enabled during installation and should normally start by
themselves after a reboot.

## Quick verification

Check the backend API:

```sh
curl -s http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
```

Inspect the complete current display state:

```sh
curl -s http://127.0.0.1:8000/api/v1/state | python3 -m json.tool
```

A fully operational hardware connection should eventually report these health
fields as `true`:

- `backend_ok`
- `database_ok`
- `serial_connected`
- `serial_fresh`
- `rfid_ok`
- `scale_ok`

Immediately after restarting the backend, `lifecycle: "unavailable"` with
`reason: "remove_garment_after_restart"` is expected if a garment was present
or the backend cannot yet confirm an empty platform. Remove everything from the
scale and allow several fresh Teensy reports to arrive.

## Normal garment test

1. Start with the weighing platform empty.
2. Wait until the frontend/backend reports healthy input.
3. Put one tagged garment into the box.
4. Keep it still while RFID and weight readings stabilize.
5. Confirm that the frontend displays the matching mock garment and its weight
   decision.
6. If the result requests an inspection, record the result in the frontend
   dialog.
7. Remove the garment completely before beginning the next cycle.

The MVP workflow is deliberately one garment at a time.

## Logs and service control

Follow backend logs live:

```sh
sudo journalctl -u argus-backend -f
```

Follow frontend logs live:

```sh
sudo journalctl -u argus-frontend -f
```

Show the latest 100 backend messages without following:

```sh
sudo journalctl -u argus-backend -n 100 --no-pager
```

Restart both applications after a configuration or deployed-code change:

```sh
sudo systemctl restart argus-backend argus-frontend
```

Stop both applications:

```sh
sudo systemctl stop argus-backend argus-frontend
```

The frontend service requests the backend service, so starting the frontend
also causes systemd to start the backend. Both are set to restart after a
process failure.

## View the Teensy serial output directly

Only one process can own the serial port. Stop the backend before opening a
serial monitor:

```sh
sudo systemctl stop argus-backend
```

Use the stable device name if it exists:

```sh
/opt/argus/venv/bin/python -m serial.tools.miniterm /dev/argus-teensy 115200
```

Otherwise use the fallback:

```sh
/opt/argus/venv/bin/python -m serial.tools.miniterm /dev/ttyACM0 115200
```

The Teensy should emit newline-delimited JSON similar to:

```json
{"v":1,"t":12345,"raw":8342133,"weight_g":240.0,"tags":[{"epc":"E280...","rssi":210}]}
```

Exit miniterm with `Ctrl+]`, then return serial ownership to the backend:

```sh
sudo systemctl start argus-backend
```

Do not leave miniterm running while restarting the backend.

## USB and serial troubleshooting

If neither device path exists, check USB detection:

```sh
lsusb
dmesg --ctime | tail -n 40
```

Reconnect the Teensy and check again. When `/dev/ttyACM0` exists but
`/dev/argus-teensy` does not, reload the supplied udev rule:

```sh
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and reconnect the Teensy. Check the resolved stable device with:

```sh
readlink -f /dev/argus-teensy
```

If direct serial access reports `Permission denied`, confirm that the current
user belongs to `dialout`:

```sh
groups
```

Add the user if needed, then log out and back in:

```sh
sudo usermod -aG dialout "$USER"
```

If the port reports `Device or resource busy`, find its owner:

```sh
sudo fuser -v /dev/ttyACM0
```

Normally the owner is `argus-backend`; stop that service before using a serial
monitor.

## Run manually from development checkouts

Use this mode while modifying code. Stop the installed services first so ports
8000 and 3000 and the Teensy serial port are available:

```sh
sudo systemctl stop argus-backend argus-frontend
```

The examples below assume checkouts at `~/laundrybox` and `~/smart-shaft`.
Adjust the paths if the repositories are elsewhere.

### Backend

First-time setup:

```sh
cd ~/laundrybox/backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
mkdir -p var
alembic upgrade head
argus-backend seed
```

Run it in the foreground:

```sh
cd ~/laundrybox/backend
. .venv/bin/activate
argus-backend serve --reload
```

Keep this terminal open. The development defaults use
`./var/argus.sqlite3`, `/dev/argus-teensy`, and `/dev/ttyACM0`.

### Frontend development server

In a second terminal, perform the first-time dependency installation if
necessary, then start Vite:

```sh
cd ~/smart-shaft
npm install
npm run dev
```

Open the URL printed by Vite, normally `http://127.0.0.1:5173`. The frontend's
default API target is `http://127.0.0.1:8000/api/v1`.

### Frontend production-style build

To exercise the same standalone Node build used by the systemd service:

```sh
cd ~/smart-shaft
npm install
npm run build:pi
HOST=127.0.0.1 PORT=3000 npm run start:pi
```

Open `http://127.0.0.1:3000`.

Stop foreground development processes with `Ctrl+C`. When finished, restore
the installed services:

```sh
sudo systemctl start argus-backend argus-frontend
```

## Test the UI without the Teensy

Stop the production backend, then run the development backend with hardware
input disabled and debug ingestion enabled:

```sh
cd ~/laundrybox/backend
. .venv/bin/activate
ARGUS_SERIAL_ENABLED=false ARGUS_ENABLE_DEBUG_INGEST=true argus-backend serve
```

In another terminal, replay the packaged example cycle:

```sh
cd ~/laundrybox/backend
. .venv/bin/activate
argus-backend replay scripts/example-cycle.jsonl --hold 5
```

Never enable the debug-ingest endpoint on a network-exposed production
installation.

## Database and backup checks

The production database is `/var/lib/argus/argus.sqlite3`. Do not edit or copy
the live SQLite files manually while the backend is writing to them. Trigger a
verified backup using the supplied service:

```sh
sudo systemctl start argus-backup.service
sudo journalctl -u argus-backup.service -n 30 --no-pager
```

List the backup files:

```sh
sudo ls -lh /var/lib/argus/backups
```

The installed timer performs a daily backup and retains the newest 14 backups:

```sh
systemctl list-timers argus-backup.timer
```

## Complete shutdown or reboot

Shut down safely before removing Raspberry Pi power:

```sh
sudo poweroff
```

Reboot the complete Pi application stack:

```sh
sudo reboot
```

After a reboot, reconnect through Pi Connect, verify both services, and run the
API health check from the beginning of this document.
