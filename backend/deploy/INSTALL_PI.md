# Raspberry Pi installation

The Pi needs Python 3.11+, Node.js 22+, `npm`, `rsync`, `curl`, and `sqlite3`.
The two repositories should normally be sibling checkouts named `laundrybox`
and `smart-shaft`.

Install the complete production stack with one command:

```sh
cd ~/laundrybox
sudo ./argus install
```

The installer creates the `argus` service account, builds a staged release,
installs the backend/frontend/backup systemd units, configures the Teensy udev
rule, preserves or migrates SQLite data, enables boot startup, and verifies the
two HTTP endpoints.

After installation:

```sh
argusctl status
argusctl scans --follow
```

Open `http://127.0.0.1:3000` in Chromium. See
[`../../docs/RASPBERRY_PI_RUNBOOK.md`](../../docs/RASPBERRY_PI_RUNBOOK.md) for
development, updates, serial access, database access, and troubleshooting.
