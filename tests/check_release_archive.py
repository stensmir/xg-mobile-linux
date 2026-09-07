"""Validate the actual archive consumed by Decky's ZIP-only installer."""
import json
import sys
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as archive:
    assert archive.testzip() is None, "Corrupt ZIP member"
    names = set(archive.namelist())
    assert {n for n in names if n.endswith("/plugin.json")} == {"XG-Mobile/plugin.json"}
    for member in ("main.py", "dist/index.js", "package.json", "scripts/xgm-auto",
                   "scripts/xgm-shutdown", "scripts/xgm-patch-nvidia",
                   "patches/nvidia-575.64.05-linux-6.18.patch",
                   "systemd/xg-mobile-auto.service", "systemd/xg-mobile-shutdown.service"):
        assert "XG-Mobile/" + member in names, member
    assert all(n.startswith("XG-Mobile/") and ".." not in n.split("/") for n in names)
    assert not any("node_modules" in n or "__pycache__" in n for n in names)
    assert json.loads(archive.read("XG-Mobile/plugin.json"))["name"] == "XG Mobile"
    print("Decky ZIP archive verified:", json.loads(archive.read("XG-Mobile/package.json"))["version"])
