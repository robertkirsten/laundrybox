#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
LAUNDRY_SOURCE="${2:-}"
FRONTEND_SOURCE="${3:-}"
INSTALL_ROOT=/opt/argus
RELEASES_DIR="$INSTALL_ROOT/releases"
CONFIG_DIR=/etc/argus
CONFIG_FILE="$CONFIG_DIR/argus.env"
STATE_DIR=/var/lib/argus

die() {
    echo "argus deploy: $*" >&2
    exit 1
}

[[ "$MODE" == install || "$MODE" == deploy ]] || die "expected install or deploy"
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "must run as root"
[[ -f "$LAUNDRY_SOURCE/backend/pyproject.toml" ]] || die "invalid LaundryBox source: $LAUNDRY_SOURCE"
[[ -f "$FRONTEND_SOURCE/package.json" ]] || die "invalid frontend source: $FRONTEND_SOURCE"

for command in python3 node npm rsync curl sqlite3 systemctl udevadm runuser; do
    command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done
[[ -x /usr/bin/node ]] || die "production requires Node at /usr/bin/node"

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    || die "Python 3.11 or newer is required"
/usr/bin/node -e 'process.exitCode = Number(process.versions.node.split(".")[0]) < 22 ? 1 : 0' \
    || die "Node.js 22 or newer is required at /usr/bin/node (found $(/usr/bin/node --version))"

if [[ "$MODE" == install ]]; then
    if ! getent group argus >/dev/null; then
        groupadd --system argus
    fi
    if ! id -u argus >/dev/null 2>&1; then
        useradd --system --gid argus --home-dir /nonexistent --shell /usr/sbin/nologin argus
    fi
else
    id -u argus >/dev/null 2>&1 || die "ARGUS is not installed; run 'sudo ./argus install'"
fi
getent group dialout >/dev/null || die "dialout group does not exist"
getent group spi >/dev/null || die "spi group does not exist"
usermod -aG dialout,spi argus

install -d -o root -g argus -m 0750 "$INSTALL_ROOT" "$RELEASES_DIR" "$CONFIG_DIR"
install -d -o argus -g argus -m 0750 "$STATE_DIR" "$STATE_DIR/backups"

development_database="$LAUNDRY_SOURCE/backend/var/argus.sqlite3"
if [[ "$MODE" == install && ! -f "$STATE_DIR/argus.sqlite3" && -f "$development_database" ]]; then
    echo "Migrating the existing development database into production..."
    sqlite3 "$development_database" ".backup '$STATE_DIR/argus.sqlite3'"
    chown argus:argus "$STATE_DIR/argus.sqlite3"
    chmod 0640 "$STATE_DIR/argus.sqlite3"
fi

release_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
release="$RELEASES_DIR/$release_id"
install -d -o root -g argus -m 0750 "$release/laundrybox" "$release/smart-shaft"

echo "Staging backend..."
rsync -a --delete \
    --exclude .git --exclude .venv --exclude .pytest_cache --exclude .ruff_cache \
    --exclude __pycache__ --exclude backend/var --exclude backend/.env \
    "$LAUNDRY_SOURCE/" "$release/laundrybox/"
python3 -m venv "$release/venv"
"$release/venv/bin/python" -m pip install "$release/laundrybox/backend"
"$release/venv/bin/python" -c 'import argus_backend'

echo "Staging production frontend..."
rsync -a --delete \
    --exclude .git --exclude node_modules --exclude .output --exclude dist --exclude .env \
    "$FRONTEND_SOURCE/" "$release/smart-shaft/"
(
    cd "$release/smart-shaft"
    npm install --no-package-lock
    VITE_ARGUS_API_BASE=http://127.0.0.1:8000/api/v1 npm run build:pi
)
[[ -f "$release/smart-shaft/.output/server/index.mjs" ]] \
    || die "frontend build did not produce .output/server/index.mjs"

chown -R root:argus "$release"
chmod -R g+rX,o-rwx "$release"

if [[ ! -f "$CONFIG_FILE" ]]; then
    if [[ -f "$CONFIG_DIR/backend.env" ]]; then
        cp "$CONFIG_DIR/backend.env" "$CONFIG_FILE"
    else
        cp "$release/laundrybox/backend/deploy/backend.env" "$CONFIG_FILE"
    fi
fi

# Carry existing installations from the former conservative timing defaults to
# the faster production defaults. Values that differ from the old defaults are
# operator customizations and remain untouched.
migrate_default_setting() {
    local key="$1" old_value="$2" new_value="$3"
    if grep -Fqx "${key}=${old_value}" "$CONFIG_FILE"; then
        sed -i "s/^${key}=${old_value}$/${key}=${new_value}/" "$CONFIG_FILE"
    fi
}
migrate_default_setting ARGUS_STABILITY_WINDOW_SIZE 6 3
migrate_default_setting ARGUS_REMOVAL_CONFIRM_SAMPLES 4 3
migrate_default_setting ARGUS_ACQUISITION_TIMEOUT_S 10.0 6.0

# Remove the short-lived analog-strip settings. The actual hardware is a
# WS2813-compatible addressable strip driven through SPI.
sed -i '/^ARGUS_RGB_LED_ENABLED=/d' "$CONFIG_FILE"
sed -i '/^ARGUS_RGB_LED_RED_GPIO=/d' "$CONFIG_FILE"
sed -i '/^ARGUS_RGB_LED_GREEN_GPIO=/d' "$CONFIG_FILE"

if ! grep -q '^ARGUS_MOCK_DATA_PATH=' "$CONFIG_FILE"; then
    printf '\nARGUS_MOCK_DATA_PATH=/etc/argus/mock_garments.csv\n' >>"$CONFIG_FILE"
fi
if ! grep -q '^ARGUS_NEOPIXEL_ENABLED=' "$CONFIG_FILE"; then
    printf 'ARGUS_NEOPIXEL_ENABLED=true\n' >>"$CONFIG_FILE"
fi
if ! grep -q '^ARGUS_NEOPIXEL_COUNT=' "$CONFIG_FILE"; then
    printf 'ARGUS_NEOPIXEL_COUNT=60\n' >>"$CONFIG_FILE"
fi
if ! grep -q '^ARGUS_NEOPIXEL_BRIGHTNESS=' "$CONFIG_FILE"; then
    printf 'ARGUS_NEOPIXEL_BRIGHTNESS=0.2\n' >>"$CONFIG_FILE"
fi
if [[ ! -f "$CONFIG_DIR/mock_garments.csv" ]]; then
    cp "$release/laundrybox/backend/src/argus_backend/fixtures/mock_garments.csv" \
        "$CONFIG_DIR/mock_garments.csv"
fi
chown root:argus "$CONFIG_FILE" "$CONFIG_DIR/mock_garments.csv"
chmod 0640 "$CONFIG_FILE" "$CONFIG_DIR/mock_garments.csv"

install -m 0644 "$release/laundrybox/backend/deploy/99-argus-teensy.rules" \
    /etc/udev/rules.d/99-argus-teensy.rules
for unit in argus-backend.service argus-frontend.service argus-backup.service argus-backup.timer; do
    install -m 0644 "$release/laundrybox/backend/deploy/$unit" "/etc/systemd/system/$unit"
done
install -m 0755 "$release/laundrybox/backend/deploy/argusctl" /usr/local/bin/argusctl

if [[ -f "$STATE_DIR/argus.sqlite3" ]]; then
    echo "Creating pre-deploy database backup..."
    predeploy_backup="$STATE_DIR/backups/argus-predeploy-$release_id.sqlite3"
    runuser -u argus -- sqlite3 "$STATE_DIR/argus.sqlite3" ".backup '$predeploy_backup'"
    integrity="$(runuser -u argus -- sqlite3 "$predeploy_backup" 'PRAGMA integrity_check;')"
    [[ "$integrity" == ok ]] || die "pre-deploy database backup failed integrity checking"
fi

systemctl stop argus-frontend.service argus-backend.service 2>/dev/null || true

old_laundry="$(readlink "$INSTALL_ROOT/laundrybox" 2>/dev/null || true)"
old_frontend="$(readlink "$INSTALL_ROOT/smart-shaft" 2>/dev/null || true)"
old_venv="$(readlink "$INSTALL_ROOT/venv" 2>/dev/null || true)"
for name in laundrybox smart-shaft venv; do
    path="$INSTALL_ROOT/$name"
    if [[ -e "$path" && ! -L "$path" ]]; then
        legacy="$INSTALL_ROOT/${name}.legacy.$release_id"
        mv "$path" "$legacy"
        case "$name" in
            laundrybox) old_laundry="$legacy" ;;
            smart-shaft) old_frontend="$legacy" ;;
            venv) old_venv="$legacy" ;;
        esac
    fi
done

ln -sfn "$release/laundrybox" "$INSTALL_ROOT/laundrybox"
ln -sfn "$release/smart-shaft" "$INSTALL_ROOT/smart-shaft"
ln -sfn "$release/venv" "$INSTALL_ROOT/venv"

rollback() {
    local failed=$?
    trap - ERR
    echo "Deployment failed; restoring the previous release." >&2
    if [[ -n "$old_laundry" ]]; then
        ln -sfn "$old_laundry" "$INSTALL_ROOT/laundrybox"
    else
        unlink "$INSTALL_ROOT/laundrybox" 2>/dev/null || true
    fi
    if [[ -n "$old_frontend" ]]; then
        ln -sfn "$old_frontend" "$INSTALL_ROOT/smart-shaft"
    else
        unlink "$INSTALL_ROOT/smart-shaft" 2>/dev/null || true
    fi
    if [[ -n "$old_venv" ]]; then
        ln -sfn "$old_venv" "$INSTALL_ROOT/venv"
    else
        unlink "$INSTALL_ROOT/venv" 2>/dev/null || true
    fi
    systemctl daemon-reload
    systemctl restart argus-backend.service argus-frontend.service 2>/dev/null || true
    exit "$failed"
}
trap rollback ERR

udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
# Older installations used smart-shaft.service for the frontend. Leaving it
# enabled makes it reclaim port 3000 even though argus-frontend.service is
# stopped, and argusctl cannot otherwise control that legacy process.
if systemctl cat smart-shaft.service >/dev/null 2>&1; then
    echo "Disabling legacy smart-shaft.service..."
    systemctl disable --now smart-shaft.service
fi
systemctl enable argus-backend.service argus-frontend.service argus-backup.timer
systemctl restart argus-backend.service argus-frontend.service
systemctl start argus-backup.timer

for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null \
        && curl -fsS http://127.0.0.1:3000 >/dev/null; then
        trap - ERR
        echo "ARGUS deployment $release_id is healthy."
        echo "Use 'argusctl status' or open http://127.0.0.1:3000"
        exit 0
    fi
    sleep 1
done

echo "Services did not become healthy within 30 seconds." >&2
systemctl --no-pager --full status argus-backend.service argus-frontend.service >&2 || true
false
