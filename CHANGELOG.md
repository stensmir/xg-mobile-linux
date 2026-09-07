# Changelog

## v0.2.0 — SteamOS 3.8.26 recovery and external HDMI

Verified on ROG Ally Z1 Extreme + XG Mobile GC33Z (RTX 4090 Laptop, 16 GB), SteamOS 3.8.26, kernel 6.18.46-valve1, NVIDIA 575.64.05.

- External HDMI works at 3840×2160 / 60 Hz in **Desktop Mode (Plasma Wayland)**. PoE 2 build 25161798 rendered on RTX through Proton 11.0 and Steam Linux Runtime 4. Game Mode external output remains unresolved; this release does not replace the Steam compositor.
- Bundle the NVIDIA 575.64.05 kernel 6.18 compatibility patch. The installer applies it only to that driver/kernel combination, recognizes an already patched tree, and rejects mismatched source before editing it.
- Install matching Neptune headers, build tools, and `lib32-nvidia-utils`. Preserve disabled global NVIDIA EGL registration, retain the Vulkan ICD, rebuild initramfs, and request a reboot instead of replacing a live GPU driver.
- Replace destructive space cleanup with a free-space check. Refuse active pacman locks and relocated package-owned directories; these installations require the documented manual recovery path.
- Incorporate the HDMI-audio unbind fix before PCIe removal. Stop removal and dock power-off when teardown fails. Remove the competing `xgm-auto` stop teardown; the dedicated shutdown unit owns shutdown cleanup.
- Explain the external monitor workflow in the plugin panel and document recovery evidence and limitations.

The patched driver and Desktop Mode HDMI path were tested on hardware. The updated installer and shutdown safeguards are covered by focused checks, but a fresh end-to-end plugin installation and reboot with these additional safeguards have not been tested. **Decky Loader remains disabled on the recovery device** because a previous loader/client combination broke SteamUI. This release does not certify current Decky compatibility.
