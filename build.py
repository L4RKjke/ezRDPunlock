#!/usr/bin/env python3
"""
Сборка EXE по build_config.json.
Используется build.bat (ручной режим) и GitHub Actions (автоматический режим).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "build_config.json").read_text(encoding="utf-8"))


def build():
    name = CFG["app_name"]
    version = CFG["version"]
    icon = ROOT / CFG.get("icon", "")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", name,
    ]

    if CFG.get("icon") and icon.exists():
        cmd += ["--icon", str(icon)]

    for item in CFG.get("data_files", []):
        cmd += ["--add-data", item]

    for module in CFG.get("hidden_imports", []):
        cmd += ["--hidden-import", module]

    for pkg in CFG.get("collect_all", []):
        cmd += ["--collect-all", pkg]

    cmd.append(CFG["entry_script"])

    print(f"Сборка {name} v{version}...", flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)

    dist = ROOT / "dist"
    src = dist / f"{name}.exe"
    dst = dist / f"{name}_v{version}.exe"
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))

    print(f"Готово: {dst}", flush=True)
    return dst


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError as e:
        print(f"ОШИБКА сборки: код {e.returncode}")
        sys.exit(e.returncode)
