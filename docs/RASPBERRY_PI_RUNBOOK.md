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

The garment CSV is copied to `/etc/argus/mock_garments.csv` only on first
installation, so deployments do not overwrite local garments. New rows are
seeded when the backend restarts; existing database garments are not
destructively rewritten by the fixture importer.

## Common failures

If `./argus dev` reports port 3000 or 8000 in use, stop production first:

```sh
sudo argusctl stop
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
