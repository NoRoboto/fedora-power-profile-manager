#!/usr/bin/python3
"""Small KDE-friendly power profile manager for NVIDIA and RyzenAdj."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

HELPER = "/usr/local/sbin/workstation-power-profile-helper"
ENERGY_SUMMARY = Path("/run/workstation-power-profile/energy-summary")
ENERGY_LOG_DIR = Path("/var/lib/workstation-power-profile/energy")
NVIDIA_QUERY = [
    "nvidia-smi",
    "--query-gpu=power.draw,power.limit,power.min_limit,power.max_limit",
    "--format=csv,noheader,nounits",
    "-i",
    "0",
]
PROFILES = (
    ("Quiet Coding | CPU 30 W, GPU minimum", "quiet"),
    ("Eco Dev | CPU 35 W, GPU minimum", "eco"),
    ("Balanced | CPU 45 W, GPU minimum", "balanced"),
    ("CPU Focus | CPU 50 W, GPU minimum", "cpu-focus"),
    ("Max CPU / Min GPU | CPU 75 W, GPU minimum", "cpu-max"),
    ("Local AI | CPU 45 W, GPU 180 W", "ai"),
    ("Max Performance | saved CPU stock, GPU maximum", "max"),
)


def run(command: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


class PowerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Workstation Power Profiles")
        self.setMinimumWidth(500)
        self.settings = QSettings("NoRoboto", "WorkstationPowerProfiles")

        self.power_label = QLabel("GPU: querying...")
        self.power_label.setStyleSheet("font-size: 18px; font-weight: 600; padding: 12px;")
        self.energy_label = QLabel("CPU + GPU energy: waiting for the first minute...")
        self.energy_label.setStyleSheet("font-size: 15px; padding: 8px 12px;")
        self.status_label = QLabel("Choose a profile.")
        self.status_label.setWordWrap(True)

        self.profile_combo = QComboBox()
        for label, key in PROFILES:
            self.profile_combo.addItem(label, key)
        apply_preset = QPushButton("Apply preset")
        apply_preset.setMinimumHeight(42)
        apply_preset.clicked.connect(self.apply_selected_profile)

        preset_row = QHBoxLayout()
        preset_row.addWidget(self.profile_combo, 1)
        preset_row.addWidget(apply_preset)

        self.cpu_input = QSpinBox()
        self.cpu_input.setRange(10, 75)
        self.cpu_input.setSuffix(" W")
        self.cpu_input.setValue(int(self.settings.value("custom_cpu_watts", 50)))
        self.gpu_input = QSpinBox()
        self.gpu_input.setRange(1, 1000)
        self.gpu_input.setSuffix(" W")
        self.gpu_input.setValue(int(self.settings.value("custom_gpu_watts", 150)))
        self.cpu_input.valueChanged.connect(
            lambda value: self.settings.setValue("custom_cpu_watts", value)
        )
        self.gpu_input.valueChanged.connect(
            lambda value: self.settings.setValue("custom_gpu_watts", value)
        )

        custom_form = QFormLayout()
        custom_form.addRow("CPU limit:", self.cpu_input)
        custom_form.addRow("GPU limit:", self.gpu_input)
        apply_custom = QPushButton("Apply custom limits")
        apply_custom.setMinimumHeight(42)
        apply_custom.clicked.connect(self.apply_custom_profile)
        custom_form.addRow(apply_custom)
        custom_group = QGroupBox("Custom profile")
        custom_group.setLayout(custom_form)

        layout = QVBoxLayout()
        layout.addWidget(self.power_label)
        layout.addWidget(self.energy_label)
        layout.addLayout(preset_row)
        layout.addWidget(custom_group)
        layout.addWidget(self.status_label)
        note = QLabel(
            "The GPU range comes from its VBIOS. Energy totals cover CPU package and GPU only. "
            f"Monthly CSV files: {ENERGY_LOG_DIR}"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(2000)
        self.refresh_status(show_dialog=True)

    def refresh_status(self, show_dialog: bool = False) -> None:
        self.refresh_energy()
        if shutil.which("nvidia-smi") is None:
            self.power_label.setText("GPU: unavailable")
            if show_dialog:
                QMessageBox.critical(
                    self,
                    "NVIDIA unavailable",
                    "nvidia-smi was not found. Install and load the proprietary NVIDIA driver.",
                )
            return

        try:
            result = run(NVIDIA_QUERY, timeout=5)
        except subprocess.TimeoutExpired:
            self.power_label.setText("GPU: query timed out")
            return

        if result.returncode != 0:
            self.power_label.setText("GPU: driver unavailable")
            if show_dialog:
                detail = result.stderr.strip() or result.stdout.strip()
                QMessageBox.critical(
                    self,
                    "NVIDIA unavailable",
                    "nvidia-smi could not communicate with the NVIDIA driver.\n\n" + detail,
                )
            return

        fields = [value.strip() for value in result.stdout.strip().splitlines()[0].split(",")]
        if len(fields) != 4:
            self.power_label.setText(f"GPU: {result.stdout.strip()}")
            return
        try:
            draw, limit, minimum, maximum = (float(value) for value in fields)
        except ValueError:
            self.power_label.setText("GPU: invalid nvidia-smi response")
            return

        self.power_label.setText(
            f"GPU now: {draw:.0f} W | limit: {limit:.0f} W | range: {minimum:.0f}-{maximum:.0f} W"
        )
        saved_gpu = self.gpu_input.value()
        self.gpu_input.setRange(round(minimum), round(maximum))
        self.gpu_input.setValue(max(round(minimum), min(saved_gpu, round(maximum))))

    def refresh_energy(self) -> None:
        try:
            summary = ENERGY_SUMMARY.read_text(encoding="utf-8").strip()
        except OSError:
            self.energy_label.setText("CPU + GPU energy: waiting for the first minute...")
            return
        self.energy_label.setText(f"CPU + GPU energy | {summary}")

    def prerequisites_available(self) -> bool:
        if not shutil.which("ryzenadj"):
            QMessageBox.critical(
                self,
                "RyzenAdj unavailable",
                "ryzenadj was not found in PATH. Install it before applying profiles.",
            )
            return False
        if not shutil.which("nvidia-smi"):
            self.refresh_status(show_dialog=True)
            return False
        if not shutil.which("sudo") or not Path(HELPER).is_file():
            QMessageBox.critical(
                self,
                "Incomplete installation",
                f"{HELPER} is missing. Run ./install.sh from the project directory.",
            )
            return False
        return True

    def apply_selected_profile(self) -> None:
        profile = str(self.profile_combo.currentData())
        self.apply_helper([profile])

    def apply_custom_profile(self) -> None:
        self.apply_helper(["custom", str(self.gpu_input.value()), str(self.cpu_input.value())])

    def apply_helper(self, arguments: list[str]) -> None:
        if not self.prerequisites_available():
            return
        self.status_label.setText("Applying profile...")
        QApplication.processEvents()
        try:
            result = run(["sudo", "-n", HELPER, *arguments], timeout=15)
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Timed out", "The helper did not finish within 15 seconds.")
            return

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            if "password" in detail.lower():
                detail += "\n\nRun ./install.sh again to refresh the restricted NOPASSWD rule."
            QMessageBox.critical(self, "Profile failed", detail)
            self.status_label.setText("Could not apply the profile.")
            return

        self.status_label.setText(result.stdout.strip() or "Profile applied.")
        self.refresh_status()


def main() -> int:
    app = QApplication(sys.argv)
    window = PowerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
