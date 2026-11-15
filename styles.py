DARK_QSS = """
QWidget {
    background-color: #1e1f22;
    color: #d7d9de;
    font-family: "Segoe UI", "Ubuntu", "Helvetica", sans-serif;
    font-size: 10pt;
}

QMainWindow {
    background-color: #1e1f22;
}

QLabel#title {
    font-size: 16pt;
    font-weight: 600;
    color: #ffffff;
}

QLabel#status {
    color: #9aa0a6;
}

QLabel#status[error="true"] {
    color: #ff6b6b;
}

QGroupBox {
    border: 1px solid #2e3035;
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #8b9099;
}

QCheckBox {
    spacing: 10px;
    padding: 4px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4a4d55;
    border-radius: 4px;
    background: #2a2c31;
}

QCheckBox::indicator:checked {
    background: #4c8bf5;
    border-color: #4c8bf5;
}

QCheckBox:disabled {
    color: #5c6069;
}

QPushButton {
    background: #2a2c31;
    border: 1px solid #3a3d44;
    border-radius: 6px;
    padding: 10px;
}

QPushButton:hover {
    background: #33363d;
}

QPushButton:disabled {
    color: #5c6069;
    background: #232428;
    border-color: #2a2c31;
}

QPushButton#primary {
    background: #4c8bf5;
    border: none;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primary:hover {
    background: #5d97f7;
}

QPushButton#primary:disabled {
    background: #2b3a55;
    color: #7d8799;
}

QProgressBar {
    background: #2a2c31;
    border: 1px solid #3a3d44;
    border-radius: 6px;
    min-height: 26px;
    text-align: center;
    color: #ffffff;
}

QProgressBar::chunk {
    background: #4c8bf5;
    border-radius: 5px;
}

QProgressBar[state="done"]::chunk {
    background: #3fb950;
}
"""


def apply_style(app):
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)


def repolish(widget):
    """Перерисовать виджет после смены динамического свойства."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
