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

exec gosu "$PUID:$PGID" "$@"
