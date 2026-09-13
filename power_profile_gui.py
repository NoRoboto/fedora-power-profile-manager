#!/usr/bin/python3
"""Small KDE-friendly power profile manager for NVIDIA + RyzenAdj."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

HELPER = "/usr/local/sbin/workstation-power-profile-helper"
ENERGY_SUMMARY = Path("/run/workstation-power-profile/energy-summary")
ENERGY_LOG_DIR = Path("/var/lib/workstation-power-profile/energy")
NVIDIA_QUERY = [
    "nvidia-smi",
    "--query-gpu=power.draw,power.limit",
    "--format=csv,noheader,nounits",
    "-i",
    "0",
]


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
        self.setWindowTitle("Perfiles de energia")
        self.setMinimumWidth(430)

        self.power_label = QLabel("GPU: consultando...")
        self.power_label.setStyleSheet("font-size: 18px; font-weight: 600; padding: 12px;")
        self.status_label = QLabel("Selecciona un perfil.")
        self.status_label.setWordWrap(True)
        self.energy_label = QLabel("Energía CPU+GPU: esperando el primer minuto...")
        self.energy_label.setStyleSheet("font-size: 15px; padding: 8px 12px;")
        self.energy_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self.power_label)
        layout.addWidget(self.energy_label)

        profiles = (
            ("Eco Dev Mode — GPU objetivo 90 W / CPU 35 W", "eco"),
            ("Balanced AI — GPU objetivo 120 W / CPU 45 W", "balanced"),
            ("Max Performance — GPU max / CPU stock", "max"),
        )
        for label, profile in profiles:
            button = QPushButton(label)
            button.setMinimumHeight(48)
            button.clicked.connect(lambda _checked=False, p=profile: self.apply_profile(p))
            layout.addWidget(button)

        layout.addWidget(self.status_label)
        note = QLabel(
            "Energía medida: CPU package + GPU. No incluye placa, RAM, discos ni pérdidas de la fuente. "
            f"CSV mensual: {ENERGY_LOG_DIR}"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_gpu)
        self.timer.start(2000)
        self.refresh_gpu(show_dialog=True)

    def refresh_gpu(self, show_dialog: bool = False) -> None:
        self.refresh_energy()
        if shutil.which("nvidia-smi") is None:
            message = "No se encontro nvidia-smi. Instala y carga el controlador NVIDIA propietario."
            self.power_label.setText("GPU: no disponible")
            if show_dialog:
                QMessageBox.critical(self, "NVIDIA no disponible", message)
            return

        try:
            result = run(NVIDIA_QUERY, timeout=5)
        except subprocess.TimeoutExpired:
            self.power_label.setText("GPU: consulta agotada")
            return

        if result.returncode != 0:
            self.power_label.setText("GPU: modulo/controlador no disponible")
            if show_dialog:
                detail = result.stderr.strip() or result.stdout.strip()
                QMessageBox.critical(
                    self,
                    "NVIDIA no disponible",
                    "nvidia-smi no pudo comunicarse con el controlador NVIDIA.\n\n" + detail,
                )
            return

        first_gpu = result.stdout.strip().splitlines()[0]
        fields = [value.strip() for value in first_gpu.split(",")]
        if len(fields) == 2:
            self.power_label.setText(f"GPU actual: {fields[0]} W   |   limite: {fields[1]} W")
        else:
            self.power_label.setText(f"GPU: {first_gpu}")

    def refresh_energy(self) -> None:
        try:
            summary = ENERGY_SUMMARY.read_text(encoding="utf-8").strip()
        except OSError:
            self.energy_label.setText("Energía CPU+GPU: esperando el primer minuto...")
            return
        self.energy_label.setText(f"Energía CPU+GPU — {summary}")

    def apply_profile(self, profile: str) -> None:
        if not shutil.which("ryzenadj"):
            QMessageBox.critical(
                self,
                "RyzenAdj no disponible",
                "No se encontro ryzenadj en PATH. Instalalo antes de aplicar perfiles.",
            )
            return
        if not shutil.which("nvidia-smi"):
            self.refresh_gpu(show_dialog=True)
            return
        if not shutil.which("sudo") or not Path(HELPER).is_file():
            QMessageBox.critical(
                self,
                "Instalacion incompleta",
                f"Falta {HELPER}. Ejecuta ./install.sh desde la carpeta del proyecto.",
            )
            return

        self.status_label.setText("Aplicando perfil...")
        QApplication.processEvents()
        try:
            result = run(["sudo", "-n", HELPER, profile], timeout=15)
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Tiempo agotado", "El helper no termino en 15 segundos.")
            return

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            if "password" in detail.lower() or "contrasena" in detail.lower():
                detail += "\n\nReinstala con ./install.sh para crear la regla NOPASSWD limitada al helper."
            QMessageBox.critical(self, "No se pudo aplicar", detail)
            self.status_label.setText("Error al aplicar el perfil.")
            return

        self.status_label.setText(result.stdout.strip() or f"Perfil {profile} aplicado.")
        self.refresh_gpu()


def main() -> int:
    app = QApplication(sys.argv)
    window = PowerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
