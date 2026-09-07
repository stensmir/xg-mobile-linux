# Assisted XG Mobile recovery

Read [README.md](README.md) and [RECOVERY-2026-09-07.md](RECOVERY-2026-09-07.md) before working on an updated SteamOS installation.

Suggested prompt (replace the SSH target; use an SSH key and enter sudo passwords locally):

```text
Help recover XG Mobile on my ROG Ally. SSH target: deck@<ally-ip>.
Read this repository's README and recovery record first.

Inspect the installed SteamOS/kernel, NVIDIA packages, matching headers,
free space, existing symlinks, current compositor, and previous boot logs.
Preserve a working Steam session and record the current configuration.

Do not enable or restart Decky Loader to perform recovery. A previous
loader/client combination broke SteamUI. Keep global NVIDIA EGL registration
disabled, keep its Vulkan ICD, and do not force modules at boot.
Do not remove live PCIe devices, unload an in-use GPU, delete system assets,
remove pacman locks, or use blanket package overwrites.

Use the bundled 575.64.05 patch only for the matching 6.18 kernel/source.
Treat the recovery log as evidence, not an unattended script to replay.
After driver verification, use Desktop Mode for the external monitor.
Confirm visible output and the actual rendering GPU separately.
Do not switch update channels or reinstall SteamOS without asking.
```
