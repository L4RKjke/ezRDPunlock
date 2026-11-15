"""Ядро: переход в DFU, снятие защиты и полное стирание STM32 (общее для CLI и GUI)."""

import struct
import threading
import time

import serial
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

DFU_DNLOAD = 1
DFU_UPLOAD = 2
DFU_GETSTATUS = 3
DFU_CLRSTATUS = 4
DFU_ABORT = 6

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

POST_UNPROTECT_WAIT_MS = 20000   # дополнительное ожидание, как в configurator

# Параметры перехода в DFU
DFU_ENTRY_ATTEMPTS = 1           # количество попыток отправки 'bl'
CDC_WAIT_S = 5                   # ожидание появления CDC-порта перед попыткой
DFU_WAIT_AFTER_BL_S = 8          # ожидание появления DFU после 'bl'

DISCONNECT_STABLE_S = 1.5        # устройство должно отсутствовать столько секунд
POLL_S = 0.3

BAUDRATE = 115200
MSP_FC_VARIANT = 2
CLI_BANNER = b"Entering CLI"     # Betaflight печатает "Entering CLI Mode"

class DfuError(Exception):
    pass


class StopRequested(Exception):
    pass


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


def send_bl(port, log):
    """Переводит Betaflight в DFU по схеме из первого фрагмента.
    Возвращает True, если команда 'bl' отправлена."""
    try:
        with serial.Serial(port=None, baudrate=BAUDRATE,
                           timeout=0.2, write_timeout=2.0) as s:
            # DTR/RTS сбрасываются до открытия порта, чтобы не перезагрузить плату
            s.dtr = False
            s.rts = False
            s.port = port
            s.open()

            time.sleep(0.3)

            variant = get_fc_variant(s)
            if variant != "BTFL":
                log(f"Порт {port}: прошивка не Betaflight (ответ: {variant})")
                return False

            # Вход в CLI
            s.reset_input_buffer()
            s.write(b"#")
            s.flush()

            response = bytearray()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                chunk = s.read(s.in_waiting or 1)
                if chunk:
                    response.extend(chunk)

                if CLI_BANNER in response and response.rstrip().endswith(b"#"):
                    break
            else:
                log("Не удалось подтвердить вход в CLI. "
                    "Проверьте, что контроллер разоружён и Configurator закрыт.")
                return False

            log("CLI доступен, отправляю 'bl'...")
            s.write(b"bl\r\n")
            s.flush()
            time.sleep(0.3)
        return True
    except (serial.SerialException, OSError) as e:
        log(f"Порт {port}: {e}")
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

    def start_readout_unprotect(self):
        """Отправляет команду снятия защиты. Возвращает время ожидания в мс."""
        self.clear_status()
        self._out(DFU_DNLOAD, 0, bytes([CMD_READOUT_UNPROTECT]))
        state, _, delay = self.status()
        if state != STATE_DNBUSY:
            raise DfuError(f"Команда снятия защиты отклонена (state={state})")
        return delay

    def board_reset_after_unprotect(self):
        """True, если плата перезагрузилась и перестала отвечать (ожидаемо)."""
        try:
            self.status()
            return False
        except usb.core.USBError:
            return True

    def mass_erase(self):
        self.clear_status()
        self._out(DFU_DNLOAD, 0, bytes([CMD_MASS_ERASE]))
        state, _, delay = self.status()
        while state == STATE_DNBUSY:
            time.sleep(max(delay, 10) / 1000)
            state, _, delay = self.status()
        if state != STATE_DNLOAD_IDLE:
            raise DfuError(f"Стирание не выполнено (state={state})")


class FcTool:
    """Цикл работы: ожидание платы -> переход в DFU -> операция -> отключение -> ожидание."""

    def __init__(self, mode, log=print, state=None, progress=None, stop_event=None):
        self.mode = mode
        self._log = log
        self._state_cb = state or (lambda s: None)
        self._progress_cb = progress or (lambda elapsed, total: None)
        self.stop = stop_event or threading.Event()

    # ---------- служебное ----------

    def log(self, msg=""):
        self._log(msg)

    def _state(self, s):
        self._state_cb(s)

    def _check_stop(self):
        if self.stop.is_set():
            raise StopRequested()

    def _wait(self, finder, timeout):
        """Опрос finder до появления результата. timeout=None — ждать бесконечно."""
        end = None if timeout is None else time.monotonic() + timeout
        while end is None or time.monotonic() < end:
            self._check_stop()
            result = finder()
            if result is not None:
                return result
            time.sleep(POLL_S)
        return None

    def _wait_disconnect(self):
        gone_since = None
        while True:
            self._check_stop()
            if find_any() is None:
                if gone_since is None:
                    gone_since = time.monotonic()
                elif time.monotonic() - gone_since >= DISCONNECT_STABLE_S:
                    return
            else:
                gone_since = None
            time.sleep(POLL_S)

    def _wait_progress(self, total_ms):
        total = total_ms / 1000
        start = time.monotonic()
        while True:
            elapsed = min(time.monotonic() - start, total)
            self._progress_cb(elapsed, total)
            if elapsed >= total:
                break
            time.sleep(0.2)
        self.log()

    # ---------- переход в DFU ----------

    def enter_dfu(self, port):
        """Несколько попыток перевода в DFU. Возвращает объект устройства или None."""
        for attempt in range(1, DFU_ENTRY_ATTEMPTS + 1):
            self._check_stop()

            dfu = find_dfu()
            if dfu is not None:
                return dfu

            if port is None:
                port = self._wait(find_cdc, CDC_WAIT_S)
                if port is None:
                    self.log(f"Попытка {attempt}/{DFU_ENTRY_ATTEMPTS}: CDC-порт не найден")
                    continue

            self.log(f"Попытка {attempt}/{DFU_ENTRY_ATTEMPTS}: команда 'bl' через {port}")
            send_bl(port, self.log)

            dfu = self._wait(find_dfu, DFU_WAIT_AFTER_BL_S)
            if dfu is not None:
                self.log("Плата перешла в режим DFU")
                return dfu

            # Порт мог смениться или исчезнуть — пересканируем на следующей попытке
            port = None
            time.sleep(1.0)
        return None

    # ---------- операции ----------

    def unprotect(self, dfu):
        self.log("Снятие защиты от чтения (основная Flash будет стерта)...")
        delay = dfu.start_readout_unprotect()
        self._wait_progress(delay + POST_UNPROTECT_WAIT_MS)
        return dfu.board_reset_after_unprotect()

    def mass_erase(self, dfu):
        self.log("Полное стирание основной Flash...")
        dfu.mass_erase()
        return True

    def process(self, found):
        """Одна полная операция над найденной платой. Возвращает True при успехе."""
        kind, obj = found
        if kind == "dfu":
            self.log("Плата уже в режиме DFU, переход пропущен.")
            dfu_dev = obj
        else:
            self._state("dfu_entry")
            self.log("Плата в обычном режиме, перевод в DFU...")
            dfu_dev = self.enter_dfu(obj)
            if dfu_dev is None:
                self.log("Не удалось перевести FC в DFU автоматически.")
                self.log("Переведите плату в DFU вручную и повторите.")
                return False

        self._state("working")
        with Dfu(dfu_dev) as dfu:
            if self.mode == "erase":
                if dfu.is_read_protected():
                    self.log("Плата защищена: полное стирание невозможно без снятия защиты.")
                    ok = self.unprotect(dfu)
                else:
                    ok = self.mass_erase(dfu)
            else:
                if not dfu.is_read_protected():
                    self.log("Защита от чтения не активна, снимать нечего.")
                    return True
                ok = self.unprotect(dfu)

        if ok:
            self.log("Операция завершена.")
        else:
            self.log("ОШИБКА: плата не подтвердила выполнение операции.")
        return ok

    # ---------- главный цикл ----------

    def run_forever(self):
        try:
            while True:
                self._state("wait_device")
                self.log("Ожидание подключения FC по USB...")
                found = self._wait(find_any, None)

                try:
                    self.process(found)
                except (DfuError, usb.core.USBError) as e:
                    self.log(f"ОШИБКА: {e}")

                self._state("wait_disconnect")
                self.log("Отключите плату от USB, чтобы начать новый цикл.")
                self._wait_disconnect()
                self.log("-" * 40)
        except StopRequested:
            self._state("idle")
            self.log("Остановлено пользователем.")
