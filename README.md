# kraken-fedora

Show **two temperatures side by side** on an NZXT Kraken Z (Z53/Z63/Z73) LCD under
Linux — the CAM "dual" view, which neither CoolerControl nor liquidctl offers.

```
┌───────────────────┐
│       NZXT        │
│   58°      42°    │      CPU = blue   #3200FF
│   CPU      GPU    │      GPU = red    #FF0050
└───────────────────┘
```

`kraken-lcd-dual.py` renders that 320×320 frame with Pillow and pushes it to the
screen with liquidctl; `kraken-lcd-dual.service` keeps it live (every 3 s by
default).

## Install

```bash
git clone https://github.com/nfoulon-dev/kraken-fedora
cd kraken-fedora
./setup.sh                       # packages + renderer + service
./setup.sh --with-coolercontrol  # ...and install CoolerControl from its COPR
```

`setup.sh` installs `liquidctl`, `python3-pillow` and `dejavu-sans-fonts`, drops the
renderer in `/usr/local/bin/`, installs and starts the systemd unit, then prints the
sensors it detected. It is idempotent — re-run it any time.

Useful flags: `--interval SECONDS`, `--free-device`, `--help`.

## The one rule: only one process may own the AIO

The Kraken's LCD is driven over its USB interface, and **one owner only**. If
CoolerControl manages that device it streams its own frames continuously and
liquidctl fails with:

```
ERROR: NZXT Kraken Z (Z53, Z63 or Z73): unexpected OS error: USBError(16, 'Resource busy')
```

`setup.sh` therefore ships a helper that tells CoolerControl to leave the device
alone (it writes `disable = true` into `/etc/coolercontrol/config.toml` and restarts
the daemon):

```bash
# Close the CoolerControl desktop app first: it re-applies its own state.
sudo ./free-device.py            # hand the AIO to this project
sudo ./free-device.py --enable   # give it back (CoolerControl's LCD returns)
```

Equivalently, in the GUI: **Devices → NZXT Kraken Z → disable the device**.

Everything else in CoolerControl keeps working (Aura LEDs, fans, other devices), and
you get a bonus: with the liquidctl copy disabled, CoolerControl stops hiding the
duplicate hwmon device, so the AIO finally shows up with its **pump, radiator fan and
coolant temperature** — which is what lets you build coolant-based AIO curves there.

## What happens across reboots

* **Normal reboot, or suspend + resume** — the screen keeps its last frame. The image
  lives in the device's own memory, and liquidctl's documentation notes that
  configuration "persists as long as the device still gets power, even if the system
  has gone to Soft Off (S5) state". The service is `enabled`, so within a few seconds
  of boot it repaints the display with live temperatures regardless.
* **Full power loss** (PSU switched off, cable pulled, wall switch) — the device's
  memory is gone, and liquidctl refuses to write until it has been initialized
  ("necessary after powering on from Mechanical Off"). A failed push therefore runs
  `liquidctl --match kraken initialize` automatically (at most once a minute) and
  retries, so the display comes back on its own. Nothing to do by hand after a cold
  boot.

## Choosing what to display

Sensor sources are `LABEL=source`:

| Source | Meaning |
|---|---|
| `k10temp:Tctl` | hwmon chip name + temperature label |
| `nvidia:0` | `nvidia-smi` GPU index |
| `amdgpu:edge` | AMD GPU via hwmon |
| `auto:kraken` | the AIO's own coolant temperature |
| `cmd:<shell>` | any command that prints a number |

With no options the script auto-detects: `k10temp:Tctl` (or `Tdie`, `coretemp`,
`zenpower`) for the top row and `nvidia:0` (or `amdgpu:edge`) for the bottom.

```bash
kraken-lcd-dual.py --list-sensors                # what this machine exposes
kraken-lcd-dual.py                               # preview -> /tmp/kraken-dual.png
kraken-lcd-dual.py --push                        # render and send it
kraken-lcd-dual.py --top LIQUID=auto:kraken --bottom CPU=k10temp:Tctl --push
```

To change the pair the service shows, edit `ExecStart` in
`/etc/systemd/system/kraken-lcd-dual.service` and `sudo systemctl restart
kraken-lcd-dual`.

## Customising

* **Refresh rate** — `--loop SECONDS` (default 3).
* **Colours** — `ACCENTS` at the top of `kraken-lcd-dual.py`.
* **Header text** — `TITLE` (set to `""` to remove it).
* **Brightness** — `sudo liquidctl --match kraken set lcd screen brightness 70`;
  orientation likewise with `set lcd screen orientation 90`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `USBError(16, 'Resource busy')` | Something else owns the AIO — see *The one rule* above (`./free-device.py`). |
| `AssertionError('missing messages …')` | Two processes were talking to the LCD during a hand-over; it clears once only one owns the device. |
| Service is `active` but silent | By design: it only logs problems. The LCD itself is the proof. |
| Nothing on screen, no errors | The last frame is shown until the next push; check `kraken-lcd-dual.py --push` by hand. |
| `PermissionError: /tmp/kraken-dual.png` | With SELinux enforcing, root cannot write a *user-owned* `/tmp` file. The service writes to `/run/kraken-lcd-dual/frame.png` instead; run previews as your normal user. |
| CoolerControl LCD came back by itself | Its desktop app re-applied its state — close the app, then `sudo ./free-device.py`. |

## Uninstall

```bash
./uninstall.sh                     # service + renderer
./uninstall.sh --restore-coolercontrol   # ...and give the AIO back to CoolerControl
```

## Requirements

Fedora (uses `dnf`), Python 3.10+, Pillow, `liquidctl` ≥ 1.14 (Kraken Z support),
and the in-tree `nzxt_kraken3` kernel driver for the coolant reading. Non-Fedora
users only need the two package lines changed in `setup.sh`.

## Licence

MIT — see [LICENSE](LICENSE).
