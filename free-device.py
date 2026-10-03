#!/usr/bin/env python3
"""Hand the NZXT Kraken's USB interface to (or back from) CoolerControl.

CoolerControl claims the AIO to drive its own LCD, which makes liquidctl fail with
`Resource busy`. Disabling the device in CoolerControl's config frees it:

    [settings.<device-uid>]
    name    = "NZXT Kraken Z (Z53, Z63 or Z73)"
    disable = true

The desktop app re-applies its own state, so **close it first**; the daemon is
restarted for you if the change was written.

    sudo ./free-device.py            # disable the Kraken in CoolerControl
    sudo ./free-device.py --enable   # give it back (CoolerControl's LCD returns)
"""
from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys

CONF = pathlib.Path("/etc/coolercontrol/config.toml")
MARKER = "kraken"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    return subprocess.run([*prefix, *args], check=check, text=True,
                          capture_output=True)


def find_uid(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-f]{64})\s*=\s*\"(.*)\"", line)
        if m and MARKER in m.group(2).lower():
            return m.group(1)
    return ""


def patch(text: str, uid: str, disabled: bool) -> str:
    """Set (or clear) `disable` inside the device's [settings.<uid>] section.

    Returns the text unchanged when it already carries the wanted value, so the
    helper is safe to re-run.
    """
    section = f"[settings.{uid}]"
    wanted = "true" if disabled else "false"
    lines = text.splitlines()
    out: list[str] = []
    index, patched = 0, False

    while index < len(lines):
        line = lines[index]
        if line.strip() != section:
            out.append(line)
            index += 1
            continue

        out.append(line)
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("["):
            body.append(lines[index])
            index += 1

        current = next((b.split("=", 1)[1].strip() for b in body
                        if b.strip().startswith("disable")), None)
        if current == wanted:
            return text  # already correct
        if current is None:
            out.extend(body)
            out.append(f"disable = {wanted}")
        else:
            out.extend(f"disable = {wanted}" if b.strip().startswith("disable") else b
                       for b in body)
        patched = True

    if not patched:
        if not disabled:  # nothing to clear
            return text
        out += ["", section, 'name = "NZXT Kraken"', f"disable = {wanted}"]

    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--enable", action="store_true",
                    help="re-enable the device in CoolerControl instead")
    ap.add_argument("--no-restart", action="store_true",
                    help="do not restart coolercontrold afterwards")
    args = ap.parse_args()

    if not CONF.exists():
        print(f"{CONF} not found - is CoolerControl installed?", file=sys.stderr)
        return 1

    text = CONF.read_text()
    uid = find_uid(text)
    if not uid:
        print(f"no Kraken device found in {CONF}", file=sys.stderr)
        return 1

    new_text = patch(text, uid, disabled=not args.enable)
    if new_text == text:
        state = "enabled" if args.enable else "disabled"
        print(f"kraken already {state} in CoolerControl")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = pathlib.Path(f"/tmp/coolercontrol-config-{stamp}.toml")
    tmp.write_text(new_text)
    run("cp", "-a", str(CONF), f"{CONF}.bak-{stamp}")
    run("install", "-m", "0644", "-o", "root", "-g", "root", str(tmp), str(CONF))
    tmp.unlink(missing_ok=True)

    action = "re-enabled" if args.enable else "disabled"
    print(f"{action} {uid} in {CONF}  (backup: {CONF}.bak-{stamp})")
    if not args.no_restart and run("systemctl", "restart", "coolercontrold",
                                   check=False).returncode == 0:
        print("coolercontrold restarted")
    if not args.enable:
        print("If the LCD still shows CoolerControl's readout, close its desktop "
              "app and run this again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
