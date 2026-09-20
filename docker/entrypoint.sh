#!/bin/sh
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK="${UMASK:-002}"
CONFIG_DIR="${MUZIKK_CONFIG_DIR:-/config}"

umask "$UMASK"

if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# Reconcile the runtime user with the host ownership of the mounted volumes.
# gosu accepts raw ids, the account only exists so logs and shells look sane.
if ! getent group "$PGID" >/dev/null 2>&1 && command -v groupadd >/dev/null 2>&1; then
    groupadd -g "$PGID" muzikk || true
fi
GROUP_NAME="$(getent group "$PGID" | cut -d: -f1)"

if ! getent passwd "$PUID" >/dev/null 2>&1 && command -v useradd >/dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -d /app -s /usr/sbin/nologin -M muzikk || true
fi
USER_NAME="$(getent passwd "$PUID" | cut -d: -f1)"
: "${USER_NAME:=$PUID}"
: "${GROUP_NAME:=$PGID}"

mkdir -p "$CONFIG_DIR" "$CONFIG_DIR/logs" "$CONFIG_DIR/cache"
chown -R "$PUID:$PGID" "$CONFIG_DIR" 2>/dev/null || true

echo "Muzikk starting as ${USER_NAME}(${PUID}):${GROUP_NAME}(${PGID}) umask ${UMASK}"

# The image CMD hardcodes --port 8383. Honour MUZIKK_PORT so a healthcheck
# and a published mapping that follow that variable actually reach uvicorn.
if [ "$1" = "uvicorn" ]; then
    exec gosu "$PUID:$PGID" uvicorn muzikk.main:app \
        --host 0.0.0.0 \
        --port "${MUZIKK_PORT:-8383}" \
        --proxy-headers \
        --forwarded-allow-ips "*"
fi

exec gosu "$PUID:$PGID" "$@"
