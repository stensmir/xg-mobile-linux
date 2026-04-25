# Claude Code — Automated XG Mobile Setup

Copy the prompt below into [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Replace `<ally-ip>` and `<password>` with yours. Claude will SSH into your Ally and install the Decky plugin, which then handles the nvidia driver install from the UI.

---

## Prerequisites (do these first, on the Ally, Desktop Mode)

1. **Set a sudo password** for `deck`:
   ```bash
   passwd
   ```

2. **Enable SSH:**
   ```bash
   sudo systemctl enable --now sshd
   ip addr show | grep -E 'inet .*192\.168'
   ```
   Note the IP.

3. **Install [Decky Loader](https://decky.xyz/)** if not already:
   ```bash
   curl -L https://github.com/SteamDeckHomebrew/decky-installer/releases/latest/download/decky_installer.desktop > ~/Desktop/decky_installer.desktop
   chmod +x ~/Desktop/decky_installer.desktop
   ```
   Double-click the desktop icon and follow the prompts (release version).

4. **Plug in the XG Mobile dock** and toggle the physical switch to ON.

---

## Prompt for Claude Code

```
I have a ROG Ally Z1 Extreme running SteamOS with an ASUS XG Mobile dock connected.
SSH is enabled at deck@<ally-ip>, password: <password>.
Decky Loader is already installed at ~/homebrew/.

Please install the XG Mobile Decky plugin from https://github.com/stensmir/xg-mobile-linux
so I can manage the eGPU (install nvidia driver, activate/deactivate, copy launch options)
from the Steam QAM.

Steps:
1. SSH in and verify: `ls ~/homebrew/plugins/` (Decky must be installed).
2. Clone the repo to /tmp and copy `decky-plugin/XG-Mobile/` into `~/homebrew/plugins/`.
3. chown the plugin directory to deck:deck.
4. Restart `plugin_loader.service`.
5. Tell me to open QAM → Decky → XG Mobile → Setup on the Ally,
   enter my password once, then click "Install nvidia driver" in the plugin UI.
6. The plugin will:
   - disable readonly rootfs
   - init pacman keyring
   - free up rootfs space + symlink /var/lib/dkms to /home (rootfs is only 5GB)
   - install nvidia-dkms, nvidia-utils, lib32-nvidia-utils (SteamOS extra-3.8 repo)
   - install the auto-detect systemd service (xg-mobile-auto) so nvidia only
     loads when the dock is present
   - configure blacklists (nouveau, nvidia-drm at boot)
7. Tell me to reboot with the dock connected.
8. After reboot, run `ssh deck@<ally-ip> "nvidia-smi"` — it should show the RTX 4090.

Warn me before any destructive step (file deletion, system config change).
Do NOT add `nvidia` to `/etc/modules-load.d/` — it breaks boot without the dock.
Do NOT switch SteamOS channels (stable ↔ beta) without asking me first.
```

---

## What Claude should NOT do without explicit OK

- Enable beta channel (`steamos-select-branch beta`) — this changes your whole OS. If your kernel is older than 6.16 or your extra repo doesn't have `nvidia-dkms 575+`, you'll need to switch manually first.
- Remove pacman databases or reinstall the OS image.
- Force-push or rewrite anything on your GitHub.

## Troubleshooting

- **"plugin_loader.service not found"** → Decky Loader isn't installed. Run the Decky installer from Desktop Mode.
- **"sudo: a password is required"** during install → set the `deck` password via `passwd`. The plugin prompts for it once in the Decky UI.
- **Plugin install fails at Step 5** → SteamOS A/B update wiped nvidia-dkms or pacman keyring got corrupted. The plugin handles both (re-init keyring, fallback to extra-3.8 repo). If it still fails, SSH in and run `sudo steamos-readonly disable && sudo pacman-key --init && sudo pacman-key --populate archlinux holo`, then retry.
- **GPU not detected after reboot** → dock switch not toggled, or `egpu_connected` returns 0. Check `cat /sys/devices/platform/asus-nb-wmi/egpu_connected` (should be `1`).
- **Nothing works and you want to roll back** → SSH in, `sudo pacman -Rns nvidia-dkms nvidia-utils lib32-nvidia-utils`, `sudo systemctl disable --now xg-mobile-auto xg-mobile-shutdown`, `sudo rm /etc/modprobe.d/blacklist-nouveau.conf /etc/modprobe.d/blacklist-nvidia-drm.conf`, reboot.
