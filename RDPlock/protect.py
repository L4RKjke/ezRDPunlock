import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def find_cli(explicit_path):
    if explicit_path:
        resolved = shutil.which(explicit_path)
        if resolved:
            return resolved

        path = Path(explicit_path).expanduser()
        if path.is_file():
            return str(path.resolve())

        sys.exit("Ошибка: указанный STM32_Programmer_CLI не найден.")

    for name in ("STM32_Programmer_CLI", "STM32_Programmer_CLI.exe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/"
          "STM32_Programmer_CLI.exe",
        Path.home()
        / "STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/"
          "STM32_Programmer_CLI",
        Path(
            "/Applications/STMicroelectronics/STM32Cube/"
            "STM32CubeProgrammer/STM32CubeProgrammer.app/"
            "Contents/MacOs/bin/STM32_Programmer_CLI"
        ),
    ]

    for path in candidates:
        if path.is_file():
            return str(path)

    sys.exit(
        "Ошибка: STM32CubeProgrammer CLI не найден.\n"
        "Установи STM32CubeProgrammer и укажи путь через --cli."
    )


def run_cli(cli, arguments, timeout):
    try:
        result = subprocess.run(
            [cli, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        sys.exit(
            "Ошибка: время ожидания истекло.\n"
            "Если запись уже началась, состояние RDP неизвестно.\n"
            "Не выполняй Read Unprotect: это сотрёт Flash."
        )
    except OSError as exc:
        sys.exit(f"Ошибка запуска STM32CubeProgrammer: {exc}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Установка RDP1 на STM32F405 через USB DFU."
    )
    parser.add_argument("--cli", help="Путь к STM32_Programmer_CLI")
    parser.add_argument(
        "--confirm-f405-rdp1",
        action="store_true",
        help="Подтвердить STM32F405 и установку RDP1",
    )
    args = parser.parse_args()

    if not args.confirm_f405_rdp1:
        sys.exit(
            "Запись не выполнялась.\n"
            "Этот скрипт предназначен для STM32F405 в режиме DFU.\n"
            "Снятие RDP1 впоследствии стирает основную Flash.\n"
            "Для запуска добавь --confirm-f405-rdp1."
        )

    cli = find_cli(args.cli)

    print("1/3. Поиск FC в режиме USB DFU...", flush=True)
    listing = run_cli(cli, ["-l", "usb"], timeout=30)

    if listing.returncode != 0:
        print(listing.stdout)
        sys.exit("Ошибка: не удалось получить список USB DFU-устройств.")

    # STM32CubeProgrammer отображает порты как USB1, USB2 и т. д.
    ports = sorted(set(re.findall(r"\bUSB\d+\b", listing.stdout)))

    if not ports:
        print(listing.stdout)
        sys.exit(
            "USB DFU-устройство не обнаружено.\n"
            "Переведи FC в DFU и проверь драйвер и USB-кабель.\n"
            "Обычный COM-порт для этой операции не подходит."
        )

    if len(ports) != 1:
        sys.exit(
            f"Найдено несколько DFU-устройств: {', '.join(ports)}.\n"
            "Отключи остальные устройства, чтобы не защитить другую плату."
        )

    port = ports[0]
    print(f"Обнаружено устройство: {port}")
    print("2/3. Подключение и установка RDP Level 1...", flush=True)

    result = run_cli(
        cli,
        ["-c", f"port={port}", "-ob", "RDP=0xBB"],
        timeout=120,
    )
    print(result.stdout)

    if result.returncode != 0:
        sys.exit(
            "Программатор сообщил об ошибке; успех не подтверждён.\n"
            "При применении защиты USB-соединение могло разорваться,\n"
            "поэтому защита могла уже установиться.\n"
            "Не выполняй Read Unprotect и не меняй RDP на 0xAA."
        )

    print("3/3. Операция завершена: CLI сообщил об успешном выполнении.")
    print("Отключи USB и заново подай питание на FC.")
    print("Независимая проверка фактического уровня RDP не выполнялась.")


if __name__ == "__main__":
    main()
