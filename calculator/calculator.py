# Basic calculator app with a GUI using PyQt5.
# It allows users to input mathematical equations, evaluates them, and displays the results in a scrollable area.
# Each result is assigned a variable name for future reference.

import sys
import math
from typing import Generator, Any
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QScrollArea,
    QSizeGrip,
    QPushButton,
)
from PyQt5.QtCore import Qt

# Base font size used throughout the app
FONT_SIZE = 14


def generate_var_names() -> Generator[str, Any, None]:
    """Generator: a, b, ... , z, a1, b1, ... , z1, a2, ..."""
    suffix = 0
    while True:
        for i in range(26):
            letter = chr(ord('a') + i)
            yield letter if suffix == 0 else f"{letter}{suffix}"
        suffix += 1


class ResultRow(QWidget):
    """A single non-editable result row: 'equation = result'"""

    def __init__(self, equation: str, result: str, var_name: str) -> None:
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)
        expr_label = QLabel()
        expr_label.setText(f"{equation} = <b>{result}</b>")
        expr_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        expr_label.setStyleSheet(f"color: white; font-size: {FONT_SIZE}px;")

        var_label = QLabel(str(var_name))
        var_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        var_label.setStyleSheet(f"color: white; font-size: {FONT_SIZE}px;")

        layout.addWidget(expr_label, stretch=1)
        layout.addWidget(var_label, stretch=0)
        self.setLayout(layout)


class Calculator(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowOpacity(0.8)
        self.resize(400, 250)
        self._var_gen = generate_var_names()
        self._namespace = {"_builtins_": {}}
        for name in dir(math):
            if not name.startswith("_"):
                self._namespace[name] = getattr(math, name)
        self._old_pos = None
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(2)

        # --- First row: input editor + spacing + quit button ---
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Type an equation, press Enter")
        self.input_edit.setStyleSheet(
            f"background-color: black; color: white; " f"border: 1px solid #555; font-size: {FONT_SIZE}px;"
        )
        self.input_edit.returnPressed.connect(self._on_enter)
        top_row.addWidget(self.input_edit, stretch=1)
        top_row.addSpacing(20)

        # Cross / quit button
        self.quit_btn = QPushButton("\u2716")  # X symbol
        self.quit_btn.setFixedSize(FONT_SIZE + 12, FONT_SIZE + 12)
        self.quit_btn.setStyleSheet(
            f"background-color: black; color: white; " f"border: 1px solid #555; font-size: {FONT_SIZE}px;"
        )
        self.quit_btn.clicked.connect(QApplication.instance().quit)
        top_row.addWidget(self.quit_btn, stretch=0)
        main_layout.addLayout(top_row)

        # --- Scroll area holding the result rows ---
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background-color: black; border: none;")

        self.rows_container = QWidget()
        self.rows_container.setStyleSheet("background-color: black;")
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.rows_container.setLayout(self.rows_layout)
        self.scroll.setWidget(self.rows_container)
        main_layout.addWidget(self.scroll, stretch=1)

        # --- Size grip (bottom-right) to allow resizing ---
        grip_layout = QHBoxLayout()
        grip_layout.addStretch(1)
        grip = QSizeGrip(self)
        grip_layout.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        main_layout.addLayout(grip_layout)

        self.setLayout(main_layout)
        self.setStyleSheet("background-color: black;")
        self.setMinimumSize(200, 120)

    def _on_enter(self) -> None:
        equation = self.input_edit.text().strip()
        if not equation:
            return
        try:
            result = eval(equation, self._namespace)
        except Exception as e:
            self._insert_row(equation, f"Error: {str(e)}", "")
            self.input_edit.clear()
            return

        var_name = next(self._var_gen)
        self._namespace[var_name] = result
        self._insert_row(equation, str(result), var_name)
        self.input_edit.clear()

    def _insert_row(self, equation: str, result: str, var_name: str) -> None:
        row = ResultRow(equation, result, var_name)
        self.rows_layout.insertWidget(0, row)
        self.scroll.verticalScrollBar().setValue(0)

    # --- Enable moving the window by dragging anywhere ---
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._old_pos = event.globalPos()

    def mouseMoveEvent(self, event) -> None:
        if self._old_pos is not None:
            delta = event.globalPos() - self._old_pos
            self.move(self.pos() + delta)
            self._old_pos = event.globalPos()

    def mouseReleaseEvent(self, event) -> None:
        self._old_pos = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    calc = Calculator()
    calc.show()
    sys.exit(app.exec_())
