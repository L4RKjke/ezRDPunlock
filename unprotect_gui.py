#!/usr/bin/env python3
"""
GUI для снятия защиты от чтения FC Betaflight (STM32 DFU).
Использует функции из fc_unprotect.py (исходный скрипт не изменяется).
"""
import sys
import time

import usb.core
from PyQt6.QtCore import QProcess, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import fc_unprotect as core
from styles import apply_style, repolish

WAIT_DISCONNECT_S = 3  # сколько секунд платы не должно быть, чтобы считать ее отключенной


class OperationWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int)        # 0..100; -1 = неопределенный прогресс
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def _wait_progress(self, total_ms):
        """Подменяет core.wait_with_progress: вместо печати шлет прогресс в GUI."""
        total = total_ms / 1000
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= total:
                break
            self.progress.emit(min(int(elapsed / total * 100), 99))
            time.sleep(0.2)

    def run(self):
        core.log = lambda *a, **k: None          # лог не выводим
        core.wait_with_progress = self._wait_progress
        try:
            self._operate()
        except core.DfuError as e:
            self.failed.emit(str(e))
        except usb.core.USBError as e:
            self.failed.emit(f"Ошибка USB: {e}")

    def _operate(self):
        # 1. Поиск USB
        self.status.emit("Поиск USB...")
        self.progress.emit(0)
        found = core.wait_for(core.find_any, 30)
        if found is None:
            raise core.DfuError("плата не найдена. Подключите FC по USB и повторите.")

        kind, obj = found
        if kind == "dfu":
            dfu_dev = obj
        else:
            self.status.emit("Перевод платы в DFU...")
            dfu_dev = None
            if core.enter_dfu_via_cli(obj):
                dfu_dev = core.wait_for(core.find_dfu, core.DFU_WAIT_AFTER_CLI_S)
            if dfu_dev is None:
                raise core.DfuError("не удалось перевести плату в DFU. Переведите вручную и повторите.")

        # 2. Операция
        with core.Dfu(dfu_dev) as dfu:
            if self.mode == "erase":
                if dfu.is_read_protected():
                    self.status.emit("Снятие защиты...")
                    ok = dfu.unprotect()
                else:
                    self.status.emit("Полное стирание основной Flash...")
                    self.progress.emit(-1)
                    dfu.mass_erase()
                    ok = True
            else:
                if not dfu.is_read_protected():
                    self.succeeded.emit("Защита от чтения не активна, снимать нечего.")
                    return
                self.status.emit("Снятие защиты...")
                ok = dfu.unprotect()

        if not ok:
            raise core.DfuError("плата не подтвердила выполнение операции.")
        self.succeeded.emit("Операция завершена.")


class DisconnectWatcher(QThread):
    """Ждет, пока плату отключат, затем сигнализирует о перезапуске."""
    gone = pyqtSignal()

    def run(self):
        absent_since = None
        while True:
            if core.find_any() is None:
                if absent_since is None:
                    absent_since = time.monotonic()
                elif time.monotonic() - absent_since >= WAIT_DISCONNECT_S:
                    self.gone.emit()
                    return
            else:
                absent_since = None
            time.sleep(0.5)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Журнал снятия прошивок")
        self.resize(560, 380)
        self.worker = None
        self.watcher = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Журнал снятия прошивок")
        title.setObjectName("title")
        layout.addWidget(title)

        # Режимы (взаимоисключающие галочки)
        group = QGroupBox("Режим")
        group_layout = QVBoxLayout(group)
        self.cb1 = QCheckBox("1 - Снять защиту от чтения (RDP1 - RDP0, стирание основной Flash)")
        self.cb2 = QCheckBox("2 - Полное стирание основной Flash")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.cb1, 1)
        self.mode_group.addButton(self.cb2, 2)
        self.cb1.setChecked(True)
        group_layout.addWidget(self.cb1)
        group_layout.addWidget(self.cb2)
        layout.addWidget(group)

        self.btn = QPushButton("Снять защиту")
        self.btn.setObjectName("primary")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.start)
        layout.addWidget(self.btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        layout.addWidget(self.progress)

        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.set_status("Подключите FC по USB и нажмите «Снять защиту».")
        layout.addWidget(self.status_label)

        layout.addStretch()

    # --- helpers ---------------------------------------------------------
    def set_status(self, text, error=False):
        self.status_label.setText(text)
        self.status_label.setProperty("error", error)
        repolish(self.status_label)

    def set_busy(self, busy):
        self.btn.setEnabled(not busy)
        self.cb1.setEnabled(not busy)
        self.cb2.setEnabled(not busy)

    def reset_bar(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setProperty("state", "")
        repolish(self.progress)

    # --- flow ------------------------------------------------------------
    def start(self):
        mode = "erase" if self.mode_group.checkedId() == 2 else "unprotect"
        self.set_busy(True)
        self.reset_bar()
        self.set_status("Запуск...")

        self.worker = OperationWorker(mode)
        self.worker.status.connect(self.set_status)
        self.worker.progress.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_progress(self, value):
        if value < 0:
            self.progress.setRange(0, 0)  # неопределенный режим (стирание)
            return
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(value)

    def on_success(self, msg):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100% - Плату можно отключить")
        self.progress.setProperty("state", "done")
        repolish(self.progress)
        self.set_status(f"{msg} Отключите плату, программа перезапустится.")

        # Ждем отключения платы, затем перезапускаем программу (шаг 1: поиск USB)
        self.watcher = DisconnectWatcher()
        self.watcher.gone.connect(self.restart)
        self.watcher.start()

    def on_failed(self, msg):
        self.reset_bar()
        self.set_busy(False)
        self.set_status(f"ОШИБКА: {msg}", error=True)

    def restart(self):
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, sys.argv[1:])
        else:
            QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    apply_style(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
