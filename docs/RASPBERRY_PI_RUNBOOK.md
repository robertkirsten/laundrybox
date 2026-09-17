# Raspberry Pi runbook

ARGUS has two entry points:

- `./argus` operates from the source checkout for development, validation, and deployment.
- `argusctl` operates the installed production system.

The commands assume sibling checkouts at `~/laundrybox` and `~/smart-shaft`.
Set `ARGUS_FRONTEND_DIR=/another/path` when the frontend is elsewhere.

## Development

From the LaundryBox checkout, run the whole system with one command:

```sh
cd ~/laundrybox
./argus dev
```

On its first run this command creates the Python environment, installs missing
frontend dependencies, migrates and seeds SQLite, and starts both applications:

- frontend: `http://127.0.0.1:3000`
- backend: `http://127.0.0.1:8000`
- API documentation: `http://127.0.0.1:8000/docs`

`Ctrl+C` stops both processes. Development configuration is stored in
`backend/.env`, and development data is stored in
`backend/var/argus.sqlite3`.

Run all available checks with:

```sh
./argus check
```

This runs Python lint/tests, frontend lint and the Pi production build, plus the
firmware build when PlatformIO is installed.

## First production installation

Install the native build prerequisite used by the Raspberry Pi GPIO dependency:

```sh
sudo apt update
sudo apt install -y swig liblgpio-dev
```

Install from the current two checkouts:

```sh
cd ~/laundrybox
sudo ./argus install
```

The installer builds both applications before stopping anything, installs
systemd services, configures the Teensy udev name, enables daily SQLite backups,
and verifies ports 8000 and 3000. If a development database exists and no
production database exists yet, it is migrated with SQLite's online backup API.

Production locations are intentionally fixed:

- application releases: `/opt/argus/releases`
- active application links: `/opt/argus/laundrybox`, `/opt/argus/smart-shaft`
- configuration: `/etc/argus/argus.env`
- editable garment fixture: `/etc/argus/mock_garments.csv`
- database: `/var/lib/argus/argus.sqlite3`
- verified backups: `/var/lib/argus/backups`

Point the Pi's Chromium kiosk at `http://127.0.0.1:3000`.

## Production updates

Update both source checkouts, then deploy them together:

```sh
cd ~/laundrybox
git pull
cd ~/smart-shaft
git pull
cd ~/laundrybox
sudo ./argus deploy
```

The deployment is staged and built before the running services stop. It backs
up SQLite, switches the active release, runs migrations through systemd, starts
both services, and checks backend and frontend HTTP endpoints. A failed startup
restores the previous active release.

## Daily operation

```sh
argusctl status
argusctl start
argusctl stop
argusctl restart
argusctl health
argusctl state
argusctl logs
```

The services start automatically after a Pi reboot.

## Clean garment scan log

Show the latest completed scans:

```sh
argusctl scans
```

Follow new scans live:

```sh
argusctl scans --follow
```

Other useful forms are:

```sh
argusctl scans --last 50
argusctl scans --last 50 --csv
```

The default output intentionally contains only EPC, garment, measured weight
(`IST`), and reference weight (`SOLL`). Technical logs remain under
`argusctl logs`.

## Raw Teensy serial

Use the safe wrapper rather than opening `/dev/ttyACM0` directly:

```sh
argusctl serial
```

Exit with `Ctrl+C`. The command remembers whether the backend was active,
temporarily stops it so only one process owns the serial port, and restores it
on exit. For an automatically bounded capture:

```sh
argusctl serial --seconds 15
argusctl serial --lines 30
```

Set `ARGUS_LOG_LEVEL=DEBUG` in `/etc/argus/argus.env` and restart the backend
when raw Teensy lines should also appear in the technical journal.

## Database and backup

Open the production database read-only:

```sh
argusctl db
```

Trigger a verified backup immediately:

```sh
argusctl backup
```

The daily timer retains the latest 14 verified backups. Deployments never reset
or replace the production database.

## Configuration changes

Edit production settings in one place:

```sh
sudo nano /etc/argus/argus.env
sudo argusctl restart
```

Current weight stability defaults are three consecutive readings within a total
2 g range. The 6-second acquisition timeout remains the fallback.
An unanswered CHECK remains available for 30 seconds after garment removal;
then it is recorded as `nothing_found` and the display returns to ready. Placing
the next garment before that timeout performs the same automatic completion.

## Addressable status strip

The strip used by ARGUS is a 5 V, individually addressable, dual-data-path RGB
strip in the WS2813 family (or a pin-compatible equivalent). Its `DI`/`BI` pads
are inputs, its `DO`/`BO` pads are outputs, and the arrows printed on the strip
point from the controller end towards the output end. Connect only at the end
marked `DI` and `BI`.

The backend drives the strip directly from Raspberry Pi SPI. A completed `PASS`
decision fills it green, a completed `CHECK` decision fills it red, and all
other states (startup, waiting, acquiring, unavailable, and shutdown) switch it
off. No Pi-to-Teensy command is involved.

### Wiring

Power down and unplug the Pi before changing connections. This prototype uses
60 pixels and displays only red or green, never a mixture of RGB channels. The
brightness is capped at 50%. Under those constraints the strip is
powered from the Pi's 5 V rail;
never power it from a GPIO or the 3.3 V pin.

| Strip connection | Connect to |
| --- | --- |
| `+5V` | Raspberry Pi 5 V, physical pin 2 or 4 |
| `GND` | Raspberry Pi GND, for example physical pin 6 |
| `DI` | Raspberry Pi SPI0 MOSI, BCM10/physical pin 19, through 470 ohms |
| `BI` | GND at the first pixel |
| `DO`, `BO` | Leave disconnected; these are outputs at the far end |

Keep the MOSI-to-`DI` wire short. The photographed pinout is consistent with
WS2813B V5, whose specified 2.7 V minimum logic-high level accepts the Pi's
3.3 V signal without a level shifter. The 470 ohm resistor limits transient
current and suppresses ringing; it does not materially lower the logic voltage.

SPI0 must be enabled before deploying:

```sh
sudo raspi-config nonint do_spi 0
sudo reboot
ls -l /dev/spidev0.0
```

The NeoPixel SPI driver uses MOSI to synthesize the 800 kHz pixel waveform, so
SPI0 cannot simultaneously be used for another peripheral. ARGUS's RFID and
scale data arrive over the Teensy's USB serial connection and do not conflict.

The deployed configuration matches the one-metre prototype and defaults to 30%.
Brightness is configurable from 0.0 to 0.5; larger values are rejected. The
driver also rejects any color that would activate multiple RGB channels
simultaneously.

```sh
ARGUS_NEOPIXEL_ENABLED=true
ARGUS_NEOPIXEL_COUNT=60
ARGUS_NEOPIXEL_BRIGHTNESS=0.5
sudo argusctl restart
```

The driver uses GRB byte order and a 300 microsecond reset interval suitable for
WS2813B. It only emits red, green, or off. If SPI or the LED library cannot
initialize, the backend logs the error and continues without the strip so the
inspection UI remains operational.

Test the wiring with:

```sh
argusctl led-test
```

The command temporarily stops the backend so only one process owns SPI, fills
the entire strip red and then green, clears the strip on exit, and then restores
the backend. Brightness remains limited by `ARGUS_NEOPIXEL_BRIGHTNESS`. Useful
options are `--color red`, `--color green`, `--brightness 0.5`, `--delay 5`, and
`--cycles 2`; `--delay` controls how many seconds each solid color remains
visible. Without `--brightness`, the command uses `ARGUS_NEOPIXEL_BRIGHTNESS`.

To invoke the Python test directly from a source checkout, first stop the
backend so it does not write to SPI concurrently, then use the backend virtual
environment:

```sh
sudo systemctl stop argus-backend.service
cd ~/laundrybox/backend
.venv/bin/python scripts/led_test.py --env-file .env
sudo systemctl start argus-backend.service
```

When the virtual environment is already activated, the middle command is simply
`python scripts/led_test.py --env-file .env`. The script accepts the same
`--color`, `--brightness`, `--delay`, and `--cycles` options and always clears
the strip on exit.

The garment CSV is copied to `/etc/argus/mock_garments.csv` only on first
installation, so deployments do not overwrite local garments. New rows are
seeded when the backend restarts; existing database garments are not
destructively rewritten by the fixture importer.

## Common failures

If `./argus dev` reports port 3000 or 8000 in use, stop production first:

```sh
sudo argusctl stop
```

Installations created before the unified ARGUS services may still have a
legacy `smart-shaft.service`. Current deployments disable it automatically. To
remove the conflict manually before deploying, run:

```sh
sudo systemctl disable --now smart-shaft.service
```

If the Teensy is not detected:

```sh
ls -l /dev/argus-teensy /dev/ttyACM0 2>/dev/null
lsusb
dmesg --ctime | tail -n 40
```

If production does not start:

```sh
argusctl status
argusctl logs
```

Always shut the Pi down before removing power:

```sh
sudo poweroff
```
