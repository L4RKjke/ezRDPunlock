#!/usr/bin/env python3
"""Читает build_config.json и сравнивает версию с предыдущим состоянием репозитория.
Пишет outputs в GITHUB_OUTPUT и release_notes.md."""
import json
import os
import subprocess

CONFIG = "build_config.json"


def previous_version():
    base = os.environ.get("BASE_SHA", "").strip()
    if not base or set(base) == {"0"}:
        base = "HEAD~1"
    try:
        out = subprocess.run(
            ["git", "show", f"{base}:{CONFIG}"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        return json.loads(out).get("version")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def main():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    version = str(cfg["version"]).strip()
    changed = version != previous_version()
    print(f"version={version} changed={str(changed).lower()}")

    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")
            f.write(f"changed={str(changed).lower()}\n")

    with open("release_notes.md", "w", encoding="utf-8") as f:
        f.write(cfg.get("description", "").strip() + "\n")


if __name__ == "__main__":
    main()
