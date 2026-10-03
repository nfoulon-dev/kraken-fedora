#!/usr/bin/env bash
# Remove the Kraken LCD dual-temperature view.
#
#   ./uninstall.sh                      remove service + renderer
#   ./uninstall.sh --restore-coolercontrol   also hand the AIO back to CoolerControl
#
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RENDERER_DST="/usr/local/bin/kraken-lcd-dual.py"
UNIT_DST="/etc/systemd/system/kraken-lcd-dual.service"
SERVICE="kraken-lcd-dual.service"

RESTORE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --restore-coolercontrol) RESTORE=1 ;;
        -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

echo "==> stopping $SERVICE"
root systemctl disable --now "$SERVICE" 2>/dev/null || true
root rm -f "$UNIT_DST"
root systemctl daemon-reload
root systemctl reset-failed "$SERVICE" 2>/dev/null || true

echo "==> removing $RENDERER_DST"
root rm -f "$RENDERER_DST"
root rm -rf /run/kraken-lcd-dual

if (( RESTORE )); then
    echo "==> giving the AIO back to CoolerControl"
    root python3 "$REPO_DIR/free-device.py" --enable
fi

echo
echo "Removed. Packages (liquidctl, python3-pillow, coolercontrol) were left in place;"
echo "remove them with 'sudo dnf remove ...' if you no longer want them."
