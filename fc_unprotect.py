#!/usr/bin/env python3
"""Консольный запуск. Остановка: Ctrl+C."""
import argparse

from fc_core import FcTool


def cli_progress(elapsed, total):
    print(f"\rОжидание завершения операции: {elapsed:5.1f} / {total:.0f} c", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Снятие защиты/стирание FC Betaflight (STM32 DFU)")
    parser.add_argument("--mode", choices=["unprotect", "erase"], default="unprotect")
    args = parser.parse_args()

    tool = FcTool(args.mode, log=print, progress=cli_progress)
    try:
        tool.run_forever()
    except KeyboardInterrupt:
        pass
    print("Выход.")


if __name__ == "__main__":
    main()
