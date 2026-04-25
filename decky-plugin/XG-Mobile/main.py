import subprocess
import os
import re
import traceback
import asyncio
import logging

PROGRESS_DIR = "/home/deck/.xgm"
PROGRESS_FILE = "/home/deck/.xgm/install-progress.txt"

# Plugin-bundled assets (copied by Decky Loader into the plugin dir)
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_SCRIPTS = os.path.join(PLUGIN_DIR, "scripts")
PLUGIN_SYSTEMD = os.path.join(PLUGIN_DIR, "systemd")

# ── Logging ──────────────────────────────────────────────
LOG_DIR = os.path.expanduser("~/homebrew/logs/XG-Mobile")
os.makedirs(LOG_DIR, exist_ok=True)
log = logging.getLogger("xgm")
log.setLevel(logging.DEBUG)
_fh = logging.FileHandler(os.path.join(LOG_DIR, "backend.log"))
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
log.info("=== XG-Mobile backend loaded ===")

# Module-level operation flag — survives component remounts on the frontend
# None | "installing" | "uninstalling"
_operation = None

_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C",
}

_ENV_DECK = {**_ENV, "HOME": "/home/deck"}

def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""

def _run(cmd, timeout=300):
    log.debug(f"_run: {cmd[:200]}")
    try:
        # Decky v3.2+ runs plugins as deck user, not root — use sudo
        if os.geteuid() != 0:
            cmd = f"sudo /bin/bash -c {_shquote(cmd)}"
        r = subprocess.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout, env=_ENV,
        )
        out = r.stdout.strip() + "\n" + r.stderr.strip()
        log.debug(f"_run rc={r.returncode} out={out[:500]}")
        return r.returncode, out
    except subprocess.TimeoutExpired:
        log.error(f"_run TIMEOUT after {timeout}s: {cmd[:200]}")
        return 1, "Timeout after {}s".format(timeout)
    except Exception as e:
        log.error(f"_run EXCEPTION: {e}")
        return 1, str(e)

def _run_user(cmd, timeout=30):
    """Run a command as the current user (no sudo). For non-privileged checks."""
    log.debug(f"_run_user: {cmd[:200]}")
    try:
        r = subprocess.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout, env=_ENV_DECK,
        )
        out = r.stdout.strip() + "\n" + r.stderr.strip()
        log.debug(f"_run_user rc={r.returncode} out={out[:500]}")
        return r.returncode, out
    except subprocess.TimeoutExpired:
        log.error(f"_run_user TIMEOUT after {timeout}s: {cmd[:200]}")
        return 1, "Timeout after {}s".format(timeout)
    except Exception as e:
        log.error(f"_run_user EXCEPTION: {e}")
        return 1, str(e)

def _shquote(s):
    """Shell-quote a string for embedding in sudo bash -c '...'"""
    return "'" + s.replace("'", "'\\''") + "'"

def _progress(step, total, msg):
    try:
        os.makedirs(PROGRESS_DIR, exist_ok=True)
        with open(PROGRESS_FILE, "w") as f:
            f.write(f"{step}/{total}|{msg}")
    except Exception:
        pass

def _unload_nvidia():
    """Unload all nvidia kernel modules in dependency order."""
    _run("modprobe -r nvidia-uvm nvidia-drm nvidia-modeset nvidia 2>/dev/null")

def _pcie_remove_nvidia():
    """Remove all nvidia PCIe devices via sysfs."""
    import glob as g
    removed = 0
    for vendor_path in g.glob("/sys/bus/pci/devices/*/vendor"):
        if _read(vendor_path) == "0x10de":
            dev_path = os.path.dirname(vendor_path)
            bdf = os.path.basename(dev_path)
            log.info(f"PCIe remove: {bdf}")
            _run(f"echo 1 > {dev_path}/remove")
            removed += 1
    return removed

class StepError(Exception):
    def __init__(self, step, msg, output):
        self.step = step
        self.msg = msg
        self.output = output
        super().__init__(f"Step {step} failed: {msg}")

def _install_cleanup():
    """Remove passwordless sudo and re-enable readonly filesystem.
    Both commands in one sudo session — after sudoers removal, sudo stops working."""
    log.info("cleanup: starting (readonly enable + rm zz-deck)")
    rc, out = _run("steamos-readonly enable 2>/dev/null; rm -f /etc/sudoers.d/zz-deck")
    log.info(f"cleanup: rc={rc} out={out[:200]}")


class Plugin:
    async def get_progress(self):
        txt = _read(PROGRESS_FILE)
        if not txt:
            return {"step": 0, "total": 0, "msg": "",
                    "operation": _operation, "installing": _operation == "installing"}
        parts = txt.split("|", 1)
        nums = parts[0].split("/")
        return {
            "step": int(nums[0]) if nums[0].isdigit() else 0,
            "total": int(nums[1]) if len(nums) > 1 and nums[1].isdigit() else 0,
            "msg": parts[1] if len(parts) > 1 else "",
            "operation": _operation,
            "installing": _operation == "installing",
        }

    async def get_status(self):
        """Non-blocking status check — runs in executor to avoid blocking asyncio."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_status_sync)

    def _get_status_sync(self):
        try:
            connected = _read("/sys/devices/platform/asus-nb-wmi/egpu_connected") == "1"
            enabled = _read("/sys/devices/platform/asus-nb-wmi/egpu_enable") == "1"

            # Fast GPU-on-bus check via sysfs instead of slow lspci
            gpu_on_bus = False
            try:
                import glob as g
                for dev in g.glob("/sys/bus/pci/devices/*/vendor"):
                    if _read(dev) == "0x10de":  # NVIDIA vendor ID
                        gpu_on_bus = True
                        break
            except Exception:
                pass

            gpu_name = ""
            gpu_temp = ""
            gpu_mem = ""
            gpu_mem_total = ""
            gpu_power = ""

            nvidia_installed = os.path.exists("/usr/bin/nvidia-smi") or os.path.exists("/usr/sbin/nvidia-smi")

            nvidia_working = False
            if nvidia_installed and gpu_on_bus:
                rc, _ = _run_user("nvidia-smi -L 2>/dev/null", timeout=5)
                nvidia_working = rc == 0

            if nvidia_installed and gpu_on_bus and nvidia_working:
                rc, out = _run_user("nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total,power.default_limit --format=csv,noheader,nounits 2>/dev/null", timeout=5)
                if rc == 0 and "," in out:
                    parts = [p.strip() for p in out.split(",")]
                    gpu_name = parts[0] if len(parts) > 0 else ""
                    gpu_temp = parts[1] if len(parts) > 1 else ""
                    gpu_mem = parts[2] if len(parts) > 2 else ""
                    gpu_mem_total = parts[3] if len(parts) > 3 else ""
                    gpu_power = parts[4] if len(parts) > 4 else ""

            result = {
                "connected": connected,
                "enabled": enabled,
                "gpu_on_bus": gpu_on_bus,
                "gpu_name": gpu_name,
                "gpu_temp": gpu_temp,
                "gpu_mem": gpu_mem,
                "gpu_mem_total": gpu_mem_total,
                "gpu_power": gpu_power,
                "nvidia_installed": nvidia_installed,
                "nvidia_working": nvidia_working,
            }
            log.info(f"get_status: connected={connected} enabled={enabled} gpu_on_bus={gpu_on_bus} "
                     f"nvidia_installed={nvidia_installed} nvidia_working={nvidia_working} gpu={gpu_name}")
            return result
        except Exception as e:
            log.error(f"get_status EXCEPTION: {e}")
            return {
                "connected": False, "enabled": False, "gpu_on_bus": False,
                "gpu_name": "", "gpu_temp": "", "gpu_mem": "", "gpu_power": "",
                "nvidia_installed": False, "nvidia_working": False,
                "error": f"get_status failed: {e}",
            }

    async def setup_sudo(self, password: str):
        """Setup passwordless sudo for deck user. Must be called before install."""
        log.info("setup_sudo: starting")
        try:
            r = subprocess.run(
                ["/bin/bash", "-c",
                 f"echo '{password}' | sudo -S bash -c '"
                 "steamos-readonly disable 2>/dev/null; "
                 "echo \"deck ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/zz-deck && "
                 "chmod 440 /etc/sudoers.d/zz-deck"
                 "'"],
                capture_output=True, text=True, timeout=30, env=_ENV_DECK,
            )
            log.info(f"setup_sudo: bash rc={r.returncode} stderr={r.stderr.strip()[:200]}")
            # Verify with _run (adds sudo automatically if needed)
            rc2, out2 = _run("echo ok", timeout=5)
            log.info(f"setup_sudo: verify rc={rc2}")
            if rc2 == 0:
                return {"success": True}
            return {"success": False, "error": "sudo setup failed — check password"}
        except Exception as e:
            log.error(f"setup_sudo EXCEPTION: {e}")
            return {"success": False, "error": str(e)}

    async def install_nvidia(self):
        """Run install in a thread so get_progress() can respond during long steps."""
        global _operation
        log.info("install_nvidia: called")

        # Reentrancy guard — block parallel installs (frontend may call twice
        # under race; running pacman-key twice corrupts /etc/pacman.d/gnupg).
        if _operation is not None:
            log.warning(f"install_nvidia: already running ({_operation}), refusing")
            return {"success": False, "error": "already_running",
                    "msg": f"{_operation.capitalize()} already in progress"}

        # Always clear stale progress before anything else
        try:
            os.remove(PROGRESS_FILE)
        except Exception:
            pass

        # Quick sync check — doesn't block long
        rc_sudo, _ = _run("echo ok", timeout=5)
        log.info(f"install_nvidia: sudo check rc={rc_sudo}")
        if rc_sudo != 0:
            log.warning("install_nvidia: needs_password")
            return {"success": False, "error": "needs_password",
                    "msg": "Password required. Use Setup first."}

        # Claim the slot BEFORE handing off to the executor so a racing
        # second call sees _operation set immediately.
        _operation = "installing"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._install_nvidia_sync)

    def _install_nvidia_sync(self):
        global _operation
        _operation = "installing"
        total = 8

        def step(n, msg, cmd, timeout=300, critical=True):
            _progress(n, total, msg)
            rc, out = _run(cmd, timeout=timeout)
            if rc != 0:
                _progress(n, total, f"FAILED: {msg}")
                if critical:
                    raise StepError(n, msg, out)
            return rc, out

        try:
            step(1, "Disabling read-only filesystem...",
                 # Drop stale pacman locks from prior failed runs.
                 # SteamOS 3.7 used /var/lib/pacman/db.lck; 3.8 moved it to
                 # /usr/lib/holo/pacmandb/db.lck — clean both, ignore missing.
                 "steamos-readonly disable; "
                 "rm -f /var/lib/pacman/db.lck /usr/lib/holo/pacmandb/db.lck 2>/dev/null; true")
            # If populate fails (half-broken keyring after SteamOS A/B update or
            # a racing prior run), wipe /etc/pacman.d/gnupg and rebuild from scratch.
            step(2, "Initializing package keys...",
                 "(pacman-key --init && pacman-key --populate archlinux holo) || "
                 "(rm -rf /etc/pacman.d/gnupg && pacman-key --init && pacman-key --populate archlinux holo)")
            step(3, "Freeing disk space...",
                 "rm -rf /usr/share/fonts/noto-cjk/ /usr/share/wallpapers/* /usr/share/ibus/ 2>/dev/null; true",
                 critical=False)
            step(4, "Preparing build environment...", " && ".join([
                "mkdir -p /home/deck/.xgm/dkms /home/deck/.xgm/pacman-cache /home/deck/.xgm/tmp",
                "rm -rf /var/lib/dkms 2>/dev/null; ln -sfn /home/deck/.xgm/dkms /var/lib/dkms",
                "rm -rf /var/cache/pacman/pkg 2>/dev/null; ln -sfn /home/deck/.xgm/pacman-cache /var/cache/pacman/pkg",
                "rm -rf /usr/share/fonts/noto-cjk/ /usr/share/wallpapers/* /usr/share/ibus/ 2>/dev/null; true",
            ]))

            _, kernel = _run_user("uname -r", timeout=5)
            kernel = kernel.strip()
            log.info(f"install: kernel={kernel}")
            m = re.search(r"neptune-(\d+)", kernel)
            kver = m.group(1) if m else "616"
            headers_pkg = "linux-neptune-" + kver + "-headers"
            log.info(f"install: headers_pkg={headers_pkg}")

            rc, out = step(5, "Downloading nvidia (~400MB)...",
                          "pacman -S --noconfirm --overwrite '*' " + headers_pkg + " nvidia-dkms nvidia-utils opencl-nvidia",
                          timeout=600, critical=False)

            if rc != 0:
                # Retry without opencl — nvidia-utils IS critical (provides Vulkan ICD for games)
                step(5, "Retrying core packages...",
                     "pacman -S --noconfirm --overwrite '*' " + headers_pkg + " nvidia-dkms nvidia-utils",
                     timeout=600)

            # DKMS build — clean stale artifacts first, then build
            _, nvidia_ver_raw = _run_user("pacman -Q nvidia-dkms 2>/dev/null")
            nvidia_ver_raw = nvidia_ver_raw.strip()
            nvidia_ver = nvidia_ver_raw.split()[1].split("-")[0] if nvidia_ver_raw else ""
            log.info(f"install: nvidia-dkms version={nvidia_ver}")
            if not nvidia_ver:
                raise StepError(6, "nvidia-dkms not found", "Package not found after install")

            # Clean stale DKMS artifacts to avoid "already built" errors
            _run(f"dkms remove nvidia/{nvidia_ver} -k {kernel} 2>/dev/null")
            # Use disk-backed tmp — tmpfs 2G is not enough for nvidia DKMS link stage
            step(6, "Building kernel module (DKMS)...",
                 f"TMPDIR=/home/deck/.xgm/tmp dkms install nvidia/{nvidia_ver} -k {kernel} --force",
                 timeout=600)

            # Verify module actually built
            rc_mod, _ = _run("modinfo nvidia 2>/dev/null")
            if rc_mod != 0:
                raise StepError(6, "Module not found after DKMS build",
                                "DKMS reported success but nvidia.ko not found. Check kernel headers match.")

            # Safe auto-detect: NO modules-load.d, NO modeset=1 in config
            # modeset=1 in modprobe.conf causes nvidia-drm to load at boot,
            # which steals display from AMD iGPU and causes black screen on Ally.
            # Instead, pass modeset=1 only at runtime when eGPU is activated.
            #
            # Files come from the plugin bundle (decky-plugin/XG-Mobile/{scripts,systemd}),
            # not curl-from-github — keeps the plugin self-contained and works with private repos.
            step(7, "Configuring auto-detection...",
                 # nvidia-utils EGL vendor crashes gamescope — remove EGL/udev, keep Vulkan ICD
                 'rm -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json '
                 '/usr/lib/udev/rules.d/60-nvidia.rules /usr/lib/modprobe.d/nvidia-sleep.conf && '
                 'echo "blacklist nouveau" > /etc/modprobe.d/blacklist-nouveau.conf && '
                 'echo "blacklist nvidia-drm" > /etc/modprobe.d/blacklist-nvidia-drm.conf && '
                 'rm -f /etc/modprobe.d/nvidia.conf /etc/modules-load.d/nvidia.conf && '
                 f'install -m 755 "{PLUGIN_SCRIPTS}/xgm-auto" /usr/local/bin/xgm-auto && '
                 f'install -m 755 "{PLUGIN_SCRIPTS}/xgm-shutdown" /usr/local/bin/xgm-shutdown && '
                 f'install -m 644 "{PLUGIN_SYSTEMD}/xg-mobile-auto.service" /etc/systemd/system/xg-mobile-auto.service && '
                 f'install -m 644 "{PLUGIN_SYSTEMD}/xg-mobile-shutdown.service" /etc/systemd/system/xg-mobile-shutdown.service && '
                 'systemctl daemon-reload && systemctl enable xg-mobile-auto.service xg-mobile-shutdown.service',
                 critical=False)

            step(8, "Loading nvidia driver...",
                 "modprobe nvidia && modprobe nvidia-uvm && modprobe nvidia-drm modeset=1",
                 critical=False)

            # ── Verification (prefer nvidia-smi if available, fallback to sysfs) ──
            gpu_name = ""
            try:
                import glob as g
                for vendor_path in g.glob("/sys/bus/pci/devices/*/vendor"):
                    if _read(vendor_path) == "0x10de":
                        dev_path = os.path.dirname(vendor_path)
                        bdf = os.path.basename(dev_path)
                        # Try to get device name from lspci
                        rc_lspci, lspci_out = _run(f"lspci -s {bdf} 2>/dev/null")
                        if rc_lspci == 0 and lspci_out.strip():
                            gpu_name = lspci_out.strip().split(":", 2)[-1].strip() if ":" in lspci_out else bdf
                        else:
                            gpu_name = f"NVIDIA GPU [{bdf}]"
                        break
            except Exception:
                pass

            rc_mod2, _ = _run("lsmod | grep '^nvidia '")
            if gpu_name and rc_mod2 == 0:
                _progress(total, total, f"Done! {gpu_name}")
                return {"success": True, "gpu": gpu_name}

            if gpu_name:
                _progress(total, total, f"GPU on bus: {gpu_name}. Reboot to load driver.")
                return {"success": True, "gpu": gpu_name, "needs_reboot": True}

            # Module built but GPU not on bus — needs reboot with dock
            rc_modinfo, _ = _run("modinfo nvidia 2>/dev/null")
            if rc_modinfo == 0:
                _progress(total, total, "Module built. Reboot with dock connected.")
                return {"success": True, "needs_reboot": True}

            # Module didn't build — real failure
            rc_load, load_err = _run("modprobe nvidia 2>&1")
            _progress(total, total, f"Driver failed to load: {load_err[:200]}")
            return {"success": False, "error": f"Module built but won't load: {load_err[:300]}"}

        except StepError as e:
            _progress(total, total, f"Failed at step {e.step}: {e.msg}")
            return {"success": False, "error": f"Step {e.step} ({e.msg}) failed: {e.output[:300]}",
                    "failed_step": e.step}
        except Exception as e:
            error_msg = traceback.format_exc()
            _progress(total, total, f"Critical error: {str(e)}")
            return {"success": False, "error": f"{str(e)}\n{error_msg[:500]}"}
        finally:
            _operation = None
            _install_cleanup()

    async def activate_egpu(self):
        rc_sudo, _ = _run("echo ok", timeout=5)
        if rc_sudo != 0:
            return {"result": "error", "gpu_name": "", "error": "needs_password"}

        connected = _read("/sys/devices/platform/asus-nb-wmi/egpu_connected")
        if connected != "1":
            return {"result": "error", "gpu_name": "", "error": "Dock not connected"}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._activate_egpu_sync)

    def _activate_egpu_sync(self):
        try:
            import time

            # Skip ACPI write if already enabled (prevents I/O error on retry)
            already_enabled = _read("/sys/devices/platform/asus-nb-wmi/egpu_enable") == "1"
            if already_enabled:
                log.info("activate_egpu: already enabled, skipping ACPI write")
            else:
                log.info("activate_egpu: ACPI enable")
                rc1, out1 = _run("echo 1 > /sys/devices/platform/asus-nb-wmi/egpu_enable")
                # asus-nb-wmi returns I/O error even on success — verify via sysfs read
                enabled = _read("/sys/devices/platform/asus-nb-wmi/egpu_enable") == "1"
                if rc1 != 0 and not enabled:
                    log.error(f"activate_egpu: ACPI truly failed rc={rc1} out={out1[:200]}")
                    return {"result": "error", "gpu_name": "", "error": f"ACPI activation failed: {out1[:200]}"}
                if rc1 != 0:
                    log.info(f"activate_egpu: ACPI write returned rc={rc1} but egpu_enable=1 (OK)")

            log.info("activate_egpu: waiting 2s for PCIe link")
            time.sleep(2)

            log.info("activate_egpu: PCI rescan")
            rc, out = _run("echo 1 > /sys/bus/pci/rescan")
            log.info(f"activate_egpu: rescan rc={rc}")

            log.info("activate_egpu: waiting 2s for device enumeration")
            time.sleep(2)

            log.info("activate_egpu: loading nvidia modules")
            rc, out = _run("modprobe nvidia")
            log.info(f"activate_egpu: modprobe nvidia rc={rc} out={out[:200]}")
            rc, out = _run("modprobe nvidia-uvm")
            log.info(f"activate_egpu: modprobe nvidia-uvm rc={rc}")
            # nvidia-drm is blacklisted (won't auto-load at boot) but games need it at runtime
            rc, out = _run("modprobe nvidia-drm modeset=1")
            log.info(f"activate_egpu: modprobe nvidia-uvm rc={rc}")

            rc, smi = _run("nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null")
            gpu_name = smi.strip() if rc == 0 else ""
            log.info(f"activate_egpu: nvidia-smi rc={rc} gpu={gpu_name}")

            if gpu_name:
                return {"result": "ok", "gpu_name": gpu_name}

            # Check if at least on PCIe bus
            try:
                import glob as g
                for dev in g.glob("/sys/bus/pci/devices/*/vendor"):
                    if _read(dev) == "0x10de":
                        log.info("activate_egpu: GPU on PCIe, driver loading")
                        return {"result": "ok", "gpu_name": "GPU on PCIe (driver loading...)"}
            except Exception:
                pass

            log.error("activate_egpu: GPU not found on PCIe bus")
            return {"result": "error", "gpu_name": "", "error": "GPU not found on PCIe bus"}
        except Exception as e:
            log.error(f"activate_egpu EXCEPTION: {e}")
            return {"result": "error", "gpu_name": "", "error": str(e)}

    async def deactivate_egpu(self):
        try:
            rc_sudo, _ = _run("echo ok", timeout=5)
            if rc_sudo != 0:
                return {"result": "error", "error": "needs_password"}
            log.info("deactivate_egpu: starting")

            # 1. PCIe remove nvidia devices (must happen before module unload)
            removed = _pcie_remove_nvidia()
            log.info(f"deactivate_egpu: PCIe removed {removed} devices")

            # 2. Unload nvidia kernel modules
            _unload_nvidia()

            # 3. Check if modules actually unloaded
            rc_mod, _ = _run("lsmod | grep '^nvidia '")
            modules_left = rc_mod == 0

            # 4. ACPI disable
            rc, out = _run("echo 0 > /sys/devices/platform/asus-nb-wmi/egpu_enable")
            if rc != 0:
                log.warning(f"deactivate_egpu: ACPI disable rc={rc} (may be OK)")

            if modules_left:
                log.warning("deactivate_egpu: nvidia modules still loaded — reboot recommended")
                return {"result": "partial", "error": "eGPU deactivated. Reboot recommended to fully unload driver."}

            return {"result": "ok"}
        except Exception as e:
            return {"result": "error", "error": str(e)}

    async def uninstall_nvidia(self):
        """Remove nvidia driver and xgm-auto service via executor (non-blocking)."""
        log.info("uninstall_nvidia: called, checking sudo")
        rc_sudo, out_sudo = _run("echo ok", timeout=5)
        log.info(f"uninstall_nvidia: sudo check rc={rc_sudo}")
        if rc_sudo != 0:
            log.warning("uninstall_nvidia: needs_password")
            return {"success": False, "error": "needs_password",
                    "msg": "Password required for uninstall."}
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._uninstall_nvidia_sync)

    def _uninstall_nvidia_sync(self):
        global _operation
        _operation = "uninstalling"
        log.info("uninstall: starting _uninstall_nvidia_sync")
        try:
            # 1. Unlock filesystem — if this fails, everything else will too
            rc, out = _run("steamos-readonly disable")
            log.info(f"uninstall: steamos-readonly disable rc={rc} out={out[:200]}")
            if rc != 0:
                log.error("uninstall: CANNOT disable readonly — aborting")
                return {"success": False, "error": f"Cannot unlock filesystem: {out[:200]}"}

            # 2. Unload nvidia modules
            log.info("uninstall: unloading nvidia modules")
            _unload_nvidia()

            # 3. DKMS remove
            rc, out = _run("dkms remove nvidia --all 2>/dev/null")
            log.info(f"uninstall: dkms remove rc={rc}")

            # 4. Remove all nvidia packages in one pacman call to resolve deps
            pkgs_to_remove = []
            for pkg in ["nvidia-dkms", "opencl-nvidia", "nvidia-utils", "lib32-nvidia-utils"]:
                rc_q, _ = _run_user(f"pacman -Q {pkg} 2>/dev/null")
                if rc_q == 0:
                    pkgs_to_remove.append(pkg)
                else:
                    log.info(f"uninstall: skip {pkg} — not installed")

            if pkgs_to_remove:
                pkg_list = " ".join(pkgs_to_remove)
                rc_rm, out_rm = _run(f"pacman -Rn --noconfirm {pkg_list}")
                log.info(f"uninstall: remove [{pkg_list}] rc={rc_rm} out={out_rm[:500]}")
                if rc_rm != 0:
                    log.error(f"uninstall: pacman remove failed: {out_rm[:300]}")
            else:
                log.info("uninstall: no nvidia packages to remove")

            # 5. Remove orphaned DKMS kernel modules (dkms remove doesn't always clean .ko files)
            _run("rm -f /lib/modules/*/updates/dkms/nvidia*.ko*")
            _run("rm -rf /var/lib/dkms/nvidia/")
            _run("depmod -a")
            log.info("uninstall: orphaned DKMS modules cleaned")

            # 6. Clean up config files + nvidia-utils EGL/udev artifacts
            _run("rm -f /etc/modprobe.d/blacklist-nouveau.conf /etc/modprobe.d/nvidia.conf "
                 "/etc/modprobe.d/blacklist-nvidia-drm.conf")
            _run("rm -f /etc/modules-load.d/nvidia.conf")
            _run("rm -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json "
                 "/usr/lib/udev/rules.d/60-nvidia.rules /usr/lib/modprobe.d/nvidia-sleep.conf")
            log.info("uninstall: config files removed")

            # 7. Disable and remove services (auto + shutdown).
            # Also clean up legacy /usr/local/bin/gamescope wrapper from earlier
            # plugin versions and its config dir, so a stale wrapper can't
            # shadow /usr/bin/gamescope after uninstall.
            _run("systemctl disable xg-mobile-auto.service xg-mobile-shutdown.service 2>/dev/null")
            _run("rm -f /usr/local/bin/xgm-auto /usr/local/bin/xgm /usr/local/bin/xgm-shutdown "
                 "/usr/local/bin/gamescope "
                 "/etc/systemd/system/xg-mobile-auto.service /etc/systemd/system/xg-mobile-shutdown.service")
            _run("systemctl daemon-reload")
            _run_user("rm -rf /home/deck/.config/xgm")
            log.info("uninstall: service cleanup done")

            # 8. Verify removal — check module is gone
            rc, _ = _run("modinfo nvidia 2>/dev/null")
            if rc == 0:
                log.error("uninstall: FAILED — nvidia module still present")
                return {"success": False, "error": "nvidia module still present after uninstall"}

            log.info("uninstall: SUCCESS — nvidia module removed")
            return {"success": True}
        except Exception as e:
            log.error(f"uninstall EXCEPTION: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}
        finally:
            _operation = None
            _install_cleanup()

    async def get_launch_options(self):
        return 'DXVK_FILTER_DEVICE_NAME="RTX 4090" PROTON_ENABLE_NVAPI=1 DXVK_ENABLE_NVAPI=1 %command%'

    async def _main(self):
        pass

    async def _unload(self):
        pass
