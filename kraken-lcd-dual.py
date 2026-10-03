#!/usr/bin/env python3
"""NZXT Kraken Z (Z53/Z63/Z73) LCD: CAM-style "dual" view of two temperatures.

Why this exists: neither CoolerControl (None / Liquid / Image-gif / Single Temp /
Carousel) nor liquidctl (`liquid`, `static`, `gif`) can display two readings at
once, so the frame is rendered here and pushed to the screen as an image.

Sensor syntax for --top / --bottom, given as LABEL=source:

    CPU=k10temp:Tctl            hwmon chip name + temperature label
    GPU=nvidia:0                nvidia-smi GPU index
    GPU=amdgpu:edge             hwmon fallback for AMD GPUs
    LIQUID=auto:kraken          the AIO's own coolant temperature
    ANY=cmd:sensors -u | awk '...'   any command that prints a number

Options:
    --list-sensors     show the chips/labels this machine exposes
    --render PATH      output PNG (default: /run/kraken-lcd-dual/frame.png as root,
                       /tmp/kraken-dual.png otherwise)
    --push             send the frame to the LCD (uses sudo when not root)
    --loop SECONDS     redraw and push forever (what the systemd service runs)

With no --top/--bottom, suitable CPU and GPU sensors are auto-detected.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

SIZE = 320
BG = (0, 0, 0)
FG = (255, 255, 255)
DIM = (127, 127, 127)
TITLE = "NZXT"
# CAM-style accents: first reading CPU (blue), second GPU (red)
ACCENTS = ((0x32, 0x00, 0xFF), (0xFF, 0x00, 0x50))

KRAKEN_LABEL = "Coolant temp"
CPU_CANDIDATES = (("k10temp", "Tctl"), ("k10temp", "Tdie"),
                  ("coretemp", "Package id 0"), ("zenpower", "Tctl"))


# --------------------------------------------------------------------------- hwmon

def _read(path: str) -> str:
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def _milli(path: str | None) -> float | None:
    if not path:
        return None
    try:
        return int(_read(path)) / 1000.0
    except (OSError, ValueError):
        return None


def chips() -> dict[str, str]:
    """{chip name: hwmon directory}"""
    found: dict[str, str] = {}
    for path in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = _read(os.path.join(path, "name"))
        if name:
            found.setdefault(name, path)
    return found


def temp_input(directory: str, label: str = "") -> float | None:
    """Temperature in degrees C for a chip directory, matched by label."""
    for lab in sorted(glob.glob(os.path.join(directory, "temp*_label"))):
        if label and _read(lab) != label:
            continue
        value = _milli(lab[: -len("_label")] + "_input")
        if value is not None:
            return value
    if not label:
        for inp in sorted(glob.glob(os.path.join(directory, "temp*_input"))):
            value = _milli(inp)
            if value is not None:
                return value
    return None


def kraken_chip() -> str | None:
    """The AIO's hwmon chip: identified by its coolant sensor, then by name."""
    found = chips()
    for name, path in found.items():
        if temp_input(path, KRAKEN_LABEL) is not None:
            return name
    for name in found:
        if name in ("z53", "z63", "z73") or name.startswith("kraken"):
            return name
    return None


def has_nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None


# --------------------------------------------------------------------------- readings

def read_temp(spec: str) -> float:
    """Value in degrees C for a source spec such as 'k10temp:Tctl'."""
    if spec.startswith("cmd:"):
        out = subprocess.check_output(spec[4:], shell=True, text=True, timeout=10)
        return float(out.strip().splitlines()[0])

    chip, _, label = spec.partition(":")
    label = label.strip().strip('"')

    if chip == "auto" and label == "kraken":
        chip, label = kraken_chip() or "", KRAKEN_LABEL

    if chip == "nvidia":
        out = subprocess.check_output(
            ["nvidia-smi", f"--id={label or 0}", "--query-gpu=temperature.gpu",
             "--format=csv,noheader,nounits"], text=True, timeout=10)
        return float(out.strip().splitlines()[0])

    directory = chips().get(chip)
    if not directory:
        raise LookupError(f"no hwmon chip named {chip!r}")
    value = temp_input(directory, label)
    if value is None:
        raise LookupError(f"{chip}: no temperature {label or '(any)'}")
    return value


def default_sources() -> tuple[str, str]:
    """(top, bottom) specs: CPU first, GPU second, chosen for this machine."""
    top = ""
    for chip, label in CPU_CANDIDATES:
        if chip in chips() and temp_input(chips()[chip], label) is not None:
            top = f"CPU={chip}:{label}"
            break
    if not top:
        top = "CPU=cmd:sensors -u | awk '/Tctl|Package id 0/{print $2; exit}'"
    bottom = "GPU=nvidia:0" if has_nvidia() else "GPU=amdgpu:edge"
    return top, bottom


def parse(spec: str) -> tuple[str, str]:
    label, sep, sensor = spec.partition("=")
    if not sep:  # no LABEL= prefix, derive it from the chip name
        return sensor.split(":")[0].upper(), spec
    return label.upper(), sensor


# --------------------------------------------------------------------------- rendering

def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    pattern = "sans:bold" if bold else "sans"
    try:
        path = subprocess.check_output(["fc-match", "-f", "%{file}", pattern],
                                       text=True, timeout=5).strip()
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    for candidate in ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
                      "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def render(rows: list[tuple[str, float, tuple[int, int, int]]], out: str,
           title: str = TITLE) -> str:
    """CAM-style gauge: two readouts side by side, accent arc down each flank."""
    img = Image.new("RGB", (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(img)

    box = (18, 24, SIZE - 18, SIZE - 24)
    for (_, _, accent), (start, end) in zip(rows, ((138, 222), (-42, 42))):
        draw.arc(box, start=start, end=end, fill=accent, width=10)

    if title:
        draw.text((SIZE / 2, 0.17 * SIZE), title, font=font(20), fill=DIM, anchor="mm")

    for (name, value, accent), x in zip(rows, (0.30 * SIZE, 0.70 * SIZE)):
        draw.text((x, 0.46 * SIZE), f"{value:.0f}\u00b0", font=font(74), fill=FG,
                  anchor="mm")
        draw.text((x, 0.68 * SIZE), name, font=font(26), fill=accent, anchor="mm")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img.save(out)
    return out


# --------------------------------------------------------------------------- output

def default_render_path() -> str:
    if os.geteuid() == 0:
        return "/run/kraken-lcd-dual/frame.png"
    return "/tmp/kraken-dual.png"


def liquidctl_cmd(*args: str) -> list[str]:
    cmd = ["liquidctl", "--match", "kraken", *args]
    if os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo", "-n", *cmd]
    return cmd


_last_init = 0.0


def initialize() -> bool:
    """Send liquidctl's initialize, at most once a minute.

    liquidctl needs this after a cold power-on (device fully off mains) before
    reads and writes behave, so a failed push retries through it.
    """
    global _last_init
    if time.time() - _last_init < 60:
        return False
    _last_init = time.time()
    return subprocess.run(liquidctl_cmd("initialize"), capture_output=True).returncode == 0


def push(path: str, attempts: int = 6, delay: float = 0.4, quiet: bool = False) -> bool:
    """Send the frame, retrying while another process briefly holds the device."""
    cmd = liquidctl_cmd("set", "lcd", "screen", "static", path)
    for attempt in range(1, attempts + 1):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True
        message = res.stderr + res.stdout
        if "Resource busy" in message:
            if attempt < attempts:
                time.sleep(delay)
            continue
        # Not a busy device: most likely a cold boot, where liquidctl requires an
        # initialize before it will write. Do that once, then keep trying.
        if initialize() and attempt < attempts:
            continue
        sys.stderr.write(res.stderr or res.stdout)
        return False
    if not quiet:
        sys.stderr.write("device stayed busy (is another LCD owner running?)\n")
    return False


def list_sensors() -> None:
    print("hwmon chips on this machine:")
    for name, path in sorted(chips().items()):
        labels = [_read(lab) for lab in sorted(glob.glob(os.path.join(path, "temp*_label")))]
        suffix = f"   temps: {', '.join(l for l in labels if l)}" if labels else ""
        print(f"  {name:16} {path}{suffix}")
    print(f"gpu:            {'nvidia-smi' if has_nvidia() else 'none'}"
          f"{' + amdgpu hwmon' if 'amdgpu' in chips() else ''}")
    print(f"kraken chip:    {kraken_chip() or 'not found'}  (coolant label: {KRAKEN_LABEL!r})")


def main() -> int:
    top_default, bottom_default = default_sources()

    ap = argparse.ArgumentParser(description="dual temperature display on a Kraken Z LCD")
    ap.add_argument("--top", default=top_default, help=f"default: {top_default}")
    ap.add_argument("--bottom", default=bottom_default, help=f"default: {bottom_default}")
    ap.add_argument("--render", default=None, metavar="PATH",
                    help="output PNG (default: %s)" % default_render_path())
    ap.add_argument("--push", action="store_true", help="send the frame to the LCD")
    ap.add_argument("--loop", type=float, metavar="SECONDS",
                    help="redraw and push every SECONDS (implies --push)")
    ap.add_argument("--list-sensors", action="store_true", help="print sensors and exit")
    args = ap.parse_args()

    if args.list_sensors:
        list_sensors()
        return 0

    out = args.render or default_render_path()

    def frame() -> list[tuple[str, float, tuple[int, int, int]]]:
        rows = []
        for index, spec in enumerate((args.top, args.bottom)):
            label, sensor = parse(spec)
            try:
                rows.append((label, read_temp(sensor), ACCENTS[index % len(ACCENTS)]))
            except Exception as exc:  # keep showing the reading that does work
                sys.stderr.write(f"{label}: {exc}\n")
        return rows

    def describe(rows) -> str:
        return ", ".join(f"{n} {v:.1f}C" for n, v, _ in rows)

    if args.loop:
        time.sleep(args.loop)
        while True:
            rows = frame()
            if rows and render(rows, out) and push(out, quiet=True):
                print(f"{out}: {describe(rows)}", flush=True)
            time.sleep(args.loop)

    rows = frame()
    render(rows, out)
    print(f"{out}: {describe(rows)}")
    if args.push and not push(out):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
