#!/usr/bin/env python3
"""
Снятие защиты от чтения (RDP1 -> RDP0) с полетного контроллера Betaflight (STM32 DFU).

Режимы:
  unprotect - снять защиту от чтения (как в configurator; основная Flash стирается)
  erase     - полное стирание основной Flash (mass erase). Если плата защищена,
              выполняется снятие защиты, которое стирает Flash само по себе.
"""
import argparse
import struct
import sys
import time

import serial.tools.list_ports
import usb.core
import usb.util

try:
    import libusb_package
    USB_BACKEND = libusb_package.get_libusb1_backend()
except ImportError:
    USB_BACKEND = None

DFU_IDS = [(0x0483, 0xDF11), (0x2E3C, 0xDF11)]  # STM32 и AT32 ROM DFU
CDC_IDS = [(0x0483, 0x5740)]                    # виртуальный COM-порт Betaflight

# DFU-запросы
DFU_DNLOAD = 1
DFU_UPLOAD = 2
DFU_GETSTATUS = 3
DFU_CLRSTATUS = 4
DFU_ABORT = 6

# Состояния DFU
STATE_IDLE = 2
STATE_DNBUSY = 4
STATE_DNLOAD_IDLE = 5
STATE_UPLOAD_IDLE = 9
STATE_ERROR = 10

OPTION_BYTES_ADDR = 0x1FFFC000
OPTION_BYTES_SIZE = 16
CMD_SET_ADDRESS = 0x21
CMD_READOUT_UNPROTECT = 0x92
CMD_MASS_ERASE = 0x41
POST_UNPROTECT_WAIT_MS = 20000  # дополнительное ожидание после команды, как в configurator
DFU_WAIT_AFTER_CLI_S = 10


class DfuError(Exception):
    pass


def log(msg=""):
    print(msg, flush=True)


def find_dfu():
    for vid, pid in DFU_IDS:
        dev = usb.core.find(idVendor=vid, idProduct=pid, backend=USB_BACKEND)
        if dev is not None:
            return dev
    return None


def find_cdc():
    for port in serial.tools.list_ports.comports():
        if port.vid is not None and (port.vid, port.pid) in CDC_IDS:
            return port.device
    return None


def find_any():
    dev = find_dfu()
    if dev is not None:
        return "dfu", dev
    port = find_cdc()
    if port is not None:
        return "cdc", port
    return None


def wait_for(finder, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = finder()
        if found is not None:
            return found
        time.sleep(0.5)
    return None


def wait_with_progress(total_ms):
    total = total_ms / 1000
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= total:
            break
        print(f"\rОжидание завершения операции: {elapsed:5.1f} / {total:.0f} c", end="", flush=True)
        time.sleep(0.5)
    print()


def enter_dfu_via_cli(port):
    """Одна попытка: CLI-команда 'bl' перезагружает плату в загрузчик."""
    try:
        with serial.Serial(port, 115200, timeout=1) as s:
            s.write(b"#\n")
            time.sleep(0.5)
            s.reset_input_buffer()
            s.write(b"bl\n")
            time.sleep(0.2)
        return True
    except serial.SerialException as e:
        log(f"Ошибка порта {port}: {e}")
        return False


class Dfu:
    def __init__(self, dev):
        self.dev = dev

    def __enter__(self):
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass  # уже сконфигурировано
        usb.util.claim_interface(self.dev, 0)
        return self

    def __exit__(self, *exc):
        try:
            usb.util.release_interface(self.dev, 0)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)

    def _out(self, request, value=0, data=b""):
        self.dev.ctrl_transfer(0x21, request, value, 0, data, timeout=5000)

    def _in(self, request, length, value=0):
        return bytes(self.dev.ctrl_transfer(0xA1, request, value, 0, length, timeout=5000))

    def status(self):
        d = self._in(DFU_GETSTATUS, 6)
        delay_ms = d[1] | (d[2] << 8) | (d[3] << 16)
        return d[4], d[0], delay_ms  # state, status, poll timeout

    def clear_status(self):
        for _ in range(100):
            state, _, delay = self.status()
            if state == STATE_IDLE:
                return
            if state in (STATE_DNLOAD_IDLE, STATE_UPLOAD_IDLE):
                self._out(DFU_ABORT)
            elif state == STATE_ERROR:
                self._out(DFU_CLRSTATUS)
            else:
                time.sleep(max(delay, 1) / 1000)
        raise DfuError("Устройство не перешло в состояние dfuIDLE")

    def set_address(self, address):
        self._out(DFU_DNLOAD, 0, struct.pack("<BI", CMD_SET_ADDRESS, address))
        state, _, delay = self.status()
        if state == STATE_DNBUSY:
            time.sleep(delay / 1000)
            state, _, _ = self.status()
        return state == STATE_DNLOAD_IDLE

    def is_read_protected(self):
        self.clear_status()
        try:
            if not self.set_address(OPTION_BYTES_ADDR):
                return True
            self.clear_status()
            self._in(DFU_UPLOAD, OPTION_BYTES_SIZE, value=2)
            state, _, _ = self.status()
            return state != STATE_UPLOAD_IDLE
        except usb.core.USBError:
            return True  # при защите чтение option bytes отклоняется

    def unprotect(self):
        log("Снятие защиты от чтения (основная Flash будет стерта)...")
        self.clear_status()
        self._out(DFU_DNLOAD, 0, bytes([CMD_READOUT_UNPROTECT]))
        state, _, delay = self.status()
        if state != STATE_DNBUSY:
            raise DfuError(f"Команда снятия защиты отклонена (state={state})")

        wait_with_progress(delay + POST_UNPROTECT_WAIT_MS)

        try:
            self.status()
        except usb.core.USBError:
            return True  # ожидаемо: плата перезагрузилась и перестала отвечать
        return False

    def mass_erase(self):
        log("Полное стирание основной Flash...")
        self.clear_status()
        self._out(DFU_DNLOAD, 0, bytes([CMD_MASS_ERASE]))
        state, _, delay = self.status()
        while state == STATE_DNBUSY:
            time.sleep(max(delay, 10) / 1000)
            state, _, delay = self.status()
        if state != STATE_DNLOAD_IDLE:
            raise DfuError(f"Стирание не выполнено (state={state})")


def run(mode, timeout):
    log("Ожидание подключения FC по USB...")
    found = wait_for(find_any, timeout)
    if found is None:
        log("ОШИБКА: плата Betaflight не найдена. Подключите FC по USB и повторите.")
        return 1

    kind, obj = found
    if kind == "dfu":
        log("Плата уже в режиме DFU, переход пропущен.")
        dfu_dev = obj
    else:
        log("Плата в обычном режиме, пробуем перевести в DFU программно (1 попытка)...")
        dfu_dev = None
        if enter_dfu_via_cli(obj):
            dfu_dev = wait_for(find_dfu, DFU_WAIT_AFTER_CLI_S)

        if dfu_dev is None:
            log("Не удалось перевести FC в DFU программно.")
            log("Переведите плату в DFU вручную и запустите скрипт снова.")
            log("Операция завершена, можете отключить плату.")
            return 2

    with Dfu(dfu_dev) as dfu:
        if mode == "erase":
            if dfu.is_read_protected():
                log("Плата защищена: полное стирание невозможно без снятия защиты.")
                ok = dfu.unprotect()
            else:
                dfu.mass_erase()
                ok = True
        else:
            if not dfu.is_read_protected():
                log("Защита от чтения не активна, снимать нечего.")
                log("Операция завершена, можете отключить плату.")
                return 0
            ok = dfu.unprotect()

    if not ok:
        log("ОШИБКА: плата не подтвердила выполнение операции.")
        return 1

    log("")
    log("Операция завершена, можете отключить плату.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Снятие защиты от чтения FC Betaflight (STM32 DFU)")
    parser.add_argument("--mode", choices=["unprotect", "erase"], default="unprotect")
    parser.add_argument("--timeout", type=int, default=30, help="ожидание подключения платы, с")
    args = parser.parse_args()

    try:
        code = run(args.mode, args.timeout)
    except DfuError as e:
        log(f"ОШИБКА: {e}")
        code = 1
    except usb.core.USBError as e:
        log(f"ОШИБКА USB: {e}")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
