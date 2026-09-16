# Raspberry Pi installation

These commands assume both repositories are copied to `/opt/argus`, Node.js 22+
and Python 3.11+ are installed, and the kiosk user is separate from the service
account.

```sh
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin argus
sudo usermod -aG dialout argus
sudo install -d -o argus -g argus -m 0750 /var/lib/argus /etc/argus

sudo python3 -m venv /opt/argus/venv
sudo /opt/argus/venv/bin/pip install /opt/argus/laundrybox/backend
cd /opt/argus/smart-shaft
sudo npm install
sudo npm run build:pi

sudo install -o root -g argus -m 0640 /opt/argus/laundrybox/backend/deploy/backend.env /etc/argus/backend.env
sudo install -m 0644 /opt/argus/laundrybox/backend/deploy/99-argus-teensy.rules /etc/udev/rules.d/99-argus-teensy.rules
sudo install -m 0644 /opt/argus/laundrybox/backend/deploy/argus-backend.service /etc/systemd/system/
sudo install -m 0644 /opt/argus/laundrybox/backend/deploy/argus-frontend.service /etc/systemd/system/
sudo install -m 0644 /opt/argus/laundrybox/backend/deploy/argus-backup.service /etc/systemd/system/
sudo install -m 0644 /opt/argus/laundrybox/backend/deploy/argus-backup.timer /etc/systemd/system/

sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl daemon-reload
sudo systemctl enable --now argus-backend.service argus-frontend.service argus-backup.timer
```

Point Chromium kiosk mode at `http://127.0.0.1:3000`. Confirm the device and
services before running a garment:

```sh
readlink -f /dev/argus-teensy
curl -fsS http://127.0.0.1:8000/api/v1/health
systemctl --no-pager --full status argus-backend argus-frontend
journalctl -u argus-backend -n 100 --no-pager
```

If `/dev/argus-teensy` is absent, inspect `udevadm info --attribute-walk
--name=/dev/ttyACM0`. The supplied rule matches the normal Teensy USB Serial
VID/PID (`16c0:0483`); add the board serial attribute if multiple Teensies are
connected.

The timer makes verified online SQLite backups in `/var/lib/argus/backups` and
retains the latest 14. Test restoration on a stopped service by copying a backup
to a separate filename and running `sqlite3 FILE 'PRAGMA integrity_check;'`.
