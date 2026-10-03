#!/usr/bin/env bash
# kraken-fedora -- install the NZXT Kraken Z LCD dual-temperature view.
#
#   ./setup.sh                        install packages, renderer and service
#   ./setup.sh --with-coolercontrol   also install CoolerControl from its COPR
#   ./setup.sh --free-device          let CoolerControl release the AIO (GUI closed!)
#   ./setup.sh --interval 2           refresh every 2 s instead of 5
#
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RENDERER_SRC="$REPO_DIR/kraken-lcd-dual.py"
UNIT_SRC="$REPO_DIR/kraken-lcd-dual.service"
RENDERER_DST="/usr/local/bin/kraken-lcd-dual.py"
UNIT_DST="/etc/systemd/system/kraken-lcd-dual.service"
SERVICE="kraken-lcd-dual.service"
PACKAGES=(liquidctl python3-pillow dejavu-sans-fonts)

WITH_COOLERCONTROL=0
FREE_DEVICE=0
INTERVAL=5

usage() {
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'EOF'

Options:
  --with-coolercontrol   install CoolerControl + daemon (COPR codifryed/CoolerControl)
  --free-device          disable the Kraken inside CoolerControl so the LCD is free
                         (close the CoolerControl desktop app first)
  --interval SECONDS     refresh interval for the LCD (default 5)
  -h, --help             this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-coolercontrol) WITH_COOLERCONTROL=1 ;;
        --free-device)        FREE_DEVICE=1 ;;
        --interval)           INTERVAL="${2:?--interval needs a value}"; shift ;;
        -h|--help)            usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# Run privileged commands through sudo only when not already root.
root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

if ! command -v dnf >/dev/null; then
    echo "This installer targets Fedora (dnf not found)." >&2
    exit 1
fi

echo "==> packages: ${PACKAGES[*]}"
root dnf install -y "${PACKAGES[@]}"

if (( WITH_COOLERCONTROL )); then
    echo "==> CoolerControl (COPR codifryed/CoolerControl)"
    root dnf install -y dnf-plugins-core
    root dnf copr enable -y codifryed/CoolerControl
    root dnf install -y coolercontrol
    root systemctl enable --now coolercontrold
fi

echo "==> renderer -> $RENDERER_DST"
root install -m 0755 "$RENDERER_SRC" "$RENDERER_DST"

echo "==> systemd unit -> $UNIT_DST"
root install -m 0644 "$UNIT_SRC" "$UNIT_DST"
root sed -i "s/--loop [0-9.]*/--loop $INTERVAL/" "$UNIT_DST"
root systemctl daemon-reload
root systemctl enable --now "$SERVICE"

if (( FREE_DEVICE )); then
    echo "==> handing the AIO over from CoolerControl"
    root python3 "$REPO_DIR/free-device.py"
fi

echo
echo "==> sensors detected on this machine"
python3 "$RENDERER_DST" --list-sensors

cat <<EOF

Installed. The LCD now shows CPU + GPU and refreshes every ${INTERVAL}s.

  status    systemctl status $SERVICE --no-pager
  errors    journalctl -u $SERVICE -f
  preview   python3 $RENDERER_DST          ->  /tmp/kraken-dual.png
  layout    edit --top/--bottom in $UNIT_DST, then: sudo systemctl restart $SERVICE

If the screen still shows CoolerControl's own readout, the AIO is still claimed
by it. Close the CoolerControl desktop app and run:

  sudo $REPO_DIR/free-device.py

or do it in its GUI: Devices -> NZXT Kraken Z -> disable the device.
EOF
