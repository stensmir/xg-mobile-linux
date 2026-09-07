"""Host-only recovery checks. No root, real sysfs writes, or driver changes."""
import importlib.util
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "decky-plugin/XG-Mobile"


class RecoveryTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("XGM_NVIDIA_SOURCE"), "Set XGM_NVIDIA_SOURCE to pristine 575.64.05 source for the Linux patch integration check")
    def test_patch_against_pristine_driver_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            names = ["conftest.sh", "nvidia-drm/nvidia-drm-drv.c", "nvidia-drm/nvidia-drm-fb.c",
                     "nvidia-drm/nvidia-drm-fb.h", "nvidia-drm/nvidia-drm-gem-user-memory.c"]
            for name in names:
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(os.environ["XGM_NVIDIA_SOURCE"]) / name, source / name)
            original = {name: (source / name).read_bytes() for name in names}

            def apply(kernel):
                return subprocess.run(["bash", str(PLUGIN / "scripts/xgm-patch-nvidia"), kernel,
                                       "575.64.05", str(source)], capture_output=True, text=True)

            self.assertEqual(apply("6.16.12-valve18").returncode, 0)
            self.assertEqual(original, {name: (source / name).read_bytes() for name in names})
            first = apply("6.18.46-valve1")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            patched = {name: (source / name).read_bytes() for name in names}
            self.assertNotEqual(original, patched)
            self.assertEqual(apply("6.18.46-valve1").returncode, 0)
            self.assertEqual(patched, {name: (source / name).read_bytes() for name in names})
            self.assertNotEqual(apply("6.16.12-valve18").returncode, 0)
            # A mismatched file must prevent changes to the other four files.
            for name, data in original.items():
                (source / name).write_bytes(data)
            (source / names[-1]).write_text("incompatible source\n")
            before = {name: (source / name).read_bytes() for name in names}
            self.assertNotEqual(apply("6.18.46-valve1").returncode, 0)
            self.assertEqual(before, {name: (source / name).read_bytes() for name in names})

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"HOME": cls.temp.name}):
            spec = importlib.util.spec_from_file_location("xgm", PLUGIN / "main.py")
            cls.backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.backend)

    @classmethod
    def tearDownClass(cls):
        cls.backend._fh.close()
        cls.temp.cleanup()

    def test_runtime_unbind_failure_never_removes_device(self):
        b = self.backend
        with patch("glob.glob", return_value=["/sys/bus/pci/devices/0000:01:00.1/vendor"]), \
             patch.object(b, "_read", return_value="0x10de"), \
             patch.object(b.os.path, "islink", return_value=True), \
             patch.object(b, "_run", return_value=(1, "busy")) as run:
            with self.assertRaises(RuntimeError):
                b._pcie_remove_nvidia()
            self.assertEqual(run.call_count, 1)
            self.assertIn("/driver/unbind", run.call_args.args[0])

    def test_installer_failure_preserves_display_workaround(self):
        b = self.backend
        commands = []

        def run(cmd, **kwargs):
            commands.append(cmd)
            return (1, "package hook failed") if cmd.startswith("pacman -S ") else (0, "")

        with patch.object(b, "_run_user", return_value=(0, "6.18.46-valve1-1-neptune-618-g2e13b4367b17")), \
             patch.object(b, "_run", side_effect=run), \
             patch.object(b, "_progress"), patch.object(b, "_install_cleanup"), \
             patch.object(b.os.path, "islink", return_value=False), \
             patch.object(b.os.path, "exists", return_value=False):
            result = b.Plugin()._install_nvidia_sync()
        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step"], 5)
        self.assertIn("nvidia-config-backup", commands[-1])
        self.assertFalse(any("--overwrite" in cmd for cmd in commands))

    def test_relocated_directories_stop_before_package_changes(self):
        b = self.backend
        with patch.object(b, "_run_user", return_value=(0, "6.18.46-valve1-1-neptune-618-g2e13b4367b17")), \
             patch.object(b, "_run") as run, patch.object(b, "_progress"), \
             patch.object(b, "_install_cleanup"), patch.object(b.os.path, "islink", return_value=True):
            result = b.Plugin()._install_nvidia_sync()
        self.assertFalse(result["success"])
        run.assert_not_called()

    def test_initramfs_failure_is_not_install_success(self):
        b = self.backend

        def user(cmd, **kwargs):
            return (0, "6.18.46-valve1-1-neptune-618-g2e13b4367b17" if cmd == "uname -r" else "nvidia-dkms 575.64.05-1")

        commands = []

        def run(cmd, **kwargs):
            commands.append(cmd)
            return (1, "initramfs failed") if "mkinitcpio -P" in cmd else (0, "")

        with patch.object(b, "_run_user", side_effect=user), patch.object(b, "_run", side_effect=run), \
             patch.object(b, "_progress"), patch.object(b, "_install_cleanup"), \
             patch.object(b.os.path, "islink", return_value=False), \
             patch.object(b.os.path, "exists", return_value=False):
            result = b.Plugin()._install_nvidia_sync()
        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step"], 7)
        self.assertTrue(any("xgm-patch-nvidia" in cmd for cmd in commands))
        self.assertFalse(any(cmd.startswith("modprobe ") for cmd in commands))

    def test_shutdown_leaves_power_on_if_teardown_fails(self):
        for failure in ("none", "unbind", "modules"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                dev = root / "sys/bus/pci/devices/0000:01:00.1"
                dev.mkdir(parents=True)
                (dev / "vendor").write_text("0x10de")
                (dev / "remove").write_text("")
                enable = root / "sys/devices/platform/asus-nb-wmi/egpu_enable"
                enable.parent.mkdir(parents=True)
                enable.write_text("1")
                if failure == "unbind":
                    driver = root / "driver"
                    driver.mkdir()
                    (driver / "unbind").touch()
                    (dev / "driver").symlink_to(driver)
                bindir = root / "bin"
                bindir.mkdir()
                for name in ("lsmod", "modprobe", "pkill", "sleep", "timeout"):
                    body = "exit 0"
                    if name == "lsmod" and failure == "modules":
                        body = "echo 'nvidia 100 1'"
                    if name == "timeout":
                        body = 'shift; exec "$@"'
                    exe = bindir / name
                    exe.write_text("#!/bin/sh\n" + body + "\n")
                    exe.chmod(0o755)
                source = (PLUGIN / "scripts/xgm-shutdown").read_text()
                source = source.replace("/sys/", str(root / "sys") + "/")
                source = source.replace("/home/deck/.config/xgm/vendor", str(root / "vendor"))
                source = source.replace("/var/log/xgm-shutdown.log", str(root / "shutdown.log"))
                env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
                subprocess.run(["bash", "-c", source], env=env, check=True, capture_output=True, timeout=10)
                self.assertEqual(enable.read_text().strip(), "0" if failure == "none" else "1")
                self.assertEqual((dev / "remove").read_text().strip(), "1" if failure == "none" else "")


if __name__ == "__main__":
    unittest.main()
