#!/usr/bin/env python3
"""Визуальный интерфейс (PyQt6). Логика — в fc_core.py."""
import json
import os
import sys
import threading

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from fc_core import FcTool

MODES = [
    ("unprotect", "Снятие защиты (unprotect)"),
    ("erase", "Полное стирание (erase)"),
]

STATE_TEXT = {
    "wait_device": "Ожидание подключения платы",
    "dfu_entry": "Переход в режим DFU",
    "working": "Выполнение операции",
    "wait_disconnect": "Отключите плату от USB",
    "idle": "Остановлено",
}
BUSY_STATES = {"wait_device", "dfu_entry", "wait_disconnect"}


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def load_config():
    with open(resource_path("build_config.json"), encoding="utf-8") as f:
        return json.load(f)


def set_variant(widget, name):
    widget.setProperty("variant", name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Worker(QObject):
    log = pyqtSignal(str)
    state = pyqtSignal(str)
    progress = pyqtSignal(float, float)
    finished = pyqtSignal()

    def __init__(self, mode, stop_event):
        super().__init__()
        self.tool = FcTool(
            mode,
            log=self.log.emit,
            state=self.state.emit,
            progress=self.progress.emit,
            stop_event=stop_event,
        )

    def run(self):
        try:
            self.tool.run_forever()
        except Exception as e:
            self.log.emit(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.setWindowTitle(f"{cfg['app_name']} {cfg['version']}")
        self.resize(720, 520)
        self._thread = None
        self._worker = None
        self._stop_event = None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(cfg["app_name"])
        title.setObjectName("title")
        version = QLabel(f"v{cfg['version']}")
        version.setObjectName("muted")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(version)
        layout.addLayout(header)

        controls = QHBoxLayout()

        # Сегментированный переключатель режима
        self.mode_frame = QFrame()
        self.mode_frame.setObjectName("segmented")
        seg_layout = QHBoxLayout(self.mode_frame)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(0)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for key, text in MODES:
            btn = QPushButton(text)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("mode", key)
            self.mode_group.addButton(btn)
            seg_layout.addWidget(btn)

        # По умолчанию — полное стирание
        self.default_mode = "erase"
        for btn in self.mode_group.buttons():
            if btn.property("mode") == self.default_mode:
                btn.setChecked(True)

        self.toggle_btn = QPushButton("Запуск")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_variant(self.toggle_btn, "primary")
        self.toggle_btn.clicked.connect(self.on_toggle)

        controls.addWidget(self.mode_frame, 1)
        controls.addWidget(self.toggle_btn)
        layout.addLayout(controls)



        self.status_label = QLabel(STATE_TEXT["idle"])
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        layout.addWidget(self.log_view, 1)

    # ---------- управление ----------

    def current_mode(self):
        btn = self.mode_group.checkedButton()
        return btn.property("mode") if btn else self.default_mode


    def on_toggle(self):
        if self._worker is None:
            self.start()
        else:
            self.stop()

    def start(self):
        mode = self.current_mode()
        if mode == "erase":
            answer = QMessageBox.question(
                self, "Подтверждение",
                "Полное стирание основной Flash платы. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.log_view.clear()
        self._stop_event = threading.Event()
        self._thread = QThread(self)
        self._worker = Worker(mode, self._stop_event)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.append_log)
        self._worker.state.connect(self.set_state)
        self._worker.progress.connect(self.set_progress)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self.on_finished)

        self._thread.start()

        for btn in self.mode_group.buttons():
            btn.setEnabled(False)

        self.toggle_btn.setText("Стоп")
        set_variant(self.toggle_btn, "danger")

    def stop(self):
        if self._stop_event is not None:
            self._stop_event.set()
        self.toggle_btn.setEnabled(False)
        self.status_label.setText("Остановка...")

    # ---------- слоты ----------

    def append_log(self, text):
        self.log_view.appendPlainText(text)

    def set_state(self, state):
        self.status_label.setText(STATE_TEXT.get(state, state))
        if state in BUSY_STATES:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)

    def set_progress(self, elapsed, total):
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1000)
        if total > 0:
            self.progress_bar.setValue(int(elapsed / total * 1000))

    def on_finished(self):
        self._worker = None
        self._thread = None
        self._stop_event = None
        self.mode_box.setEnabled(True)
        self.toggle_btn.setEnabled(True)
        self.toggle_btn.setText("Запуск")
        set_variant(self.toggle_btn, "primary")
        self.status_label.setText(STATE_TEXT["idle"])
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)

    def closeEvent(self, event):
        if self._thread is not None:
            self._stop_event.set()
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    with open(resource_path("style.qss"), encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    win = MainWindow(load_config())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
