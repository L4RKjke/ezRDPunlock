import time

import serial
from serial.tools import list_ports


BAUDRATE = 115200
SCAN_INTERVAL = 1.0
RETRY_INTERVAL = 5.0

MSP_FC_VARIANT = 2


def read_exact(port, size, deadline):
    result = bytearray()

    while len(result) < size and time.monotonic() < deadline:
        chunk = port.read(size - len(result))
        if chunk:
            result.extend(chunk)

    return bytes(result)


def get_fc_variant(port):
    """Запрашивает идентификатор прошивки через MSP v1."""
    port.reset_input_buffer()

    # MSP_FC_VARIANT без данных:
    # заголовок + длина + команда + XOR-контрольная сумма.
    port.write(b"$M<" + bytes([0, MSP_FC_VARIANT, MSP_FC_VARIANT]))
    port.flush()

    deadline = time.monotonic() + 2.0
    header = bytearray()

    while time.monotonic() < deadline:
        byte = port.read(1)
        if not byte:
            continue

        header.extend(byte)
        if len(header) > 3:
            del header[0]

        if bytes(header) != b"$M>":
            continue

        metadata = read_exact(port, 2, deadline)
        if len(metadata) != 2:
            return None

        size, command = metadata
        body = read_exact(port, size + 1, deadline)
        if len(body) != size + 1:
            return None

        payload = body[:-1]
        checksum = size ^ command

        for value in payload:
            checksum ^= value

        if checksum != body[-1]:
            return None

        if command == MSP_FC_VARIANT:
            return payload.decode("ascii", errors="replace")

        header.clear()

    return None


def enter_dfu(port):
    """Входит в Betaflight CLI и отправляет команду bl."""
    port.reset_input_buffer()
    port.write(b"#")
    port.flush()

    response = bytearray()
    deadline = time.monotonic() + 3.0

    while time.monotonic() < deadline:
        chunk = port.read(port.in_waiting or 1)
        if chunk:
            response.extend(chunk)

        if b"Entering CLI" in response and response.rstrip().endswith(b"#"):
            break
    else:
        raise RuntimeError(
            "Не удалось подтвердить вход в CLI. "
            "Проверьте, что контроллер разоружён и Configurator закрыт."
        )

    print("CLI доступен. Отправляю команду bl...")
    port.write(b"bl\r\n")
    port.flush()


def wait_for_port_removal(device, timeout=10.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        devices = {item.device for item in list_ports.comports()}
        if device not in devices:
            return True
        time.sleep(0.5)

    return False


def main():
    print("Ожидание USB-контроллера с Betaflight...")
    print("Для выхода нажмите Ctrl+C.")

    last_attempt = {}

    while True:
        for info in list_ports.comports():
            # Не трогаем обычные UART и Bluetooth COM-порты.
            if info.vid is None:
                continue

            now = time.monotonic()
            if now - last_attempt.get(info.device, -RETRY_INTERVAL) < RETRY_INTERVAL:
                continue

            last_attempt[info.device] = now

            try:
                with serial.Serial(
                    port=None,
                    baudrate=BAUDRATE,
                    timeout=0.2,
                    write_timeout=2.0,
                ) as port:
                    port.dtr = False
                    port.rts = False
                    port.port = info.device
                    port.open()

                    time.sleep(0.3)
                    variant = get_fc_variant(port)

                    if variant != "BTFL":
                        continue

                    print(
                        f"Найден Betaflight: {info.device} "
                        f"({info.description})"
                    )
                    enter_dfu(port)

            except (serial.SerialException, OSError, RuntimeError) as exc:
                print(f"{info.device}: {exc}")
                continue

            if wait_for_port_removal(info.device):
                print(
                    "COM-порт исчез после команды перезагрузки.\n"
                    "Проверьте появление DFU / STM32 BOOTLOADER "
                    "в диспетчере устройств или Configurator."
                )
            else:
                print(
                    "COM-порт не исчез. Переход в DFU не подтверждён.\n"
                    "Возможно, эта плата или версия прошивки "
                    "не поддерживает такой способ."
                )

            return

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
