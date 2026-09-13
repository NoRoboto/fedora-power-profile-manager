#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${EUID} -ne 0 ]]; then
    exec pkexec env POWER_PROFILE_USER="${USER}" "${PROJECT_DIR}/install.sh"
fi

readonly TARGET_USER="${POWER_PROFILE_USER:-$(getent passwd "${PKEXEC_UID:-0}" | cut -d: -f1)}"
readonly TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
readonly SUDOERS_FILE="/etc/sudoers.d/workstation-power-profile-${TARGET_USER}"
SUDOERS_TEMP=""

cleanup() {
    [[ -z ${SUDOERS_TEMP} ]] || rm -f -- "${SUDOERS_TEMP}"
}
trap cleanup EXIT

id "${TARGET_USER}" >/dev/null 2>&1 || {
    printf 'Invalid user: %s\n' "${TARGET_USER}" >&2
    exit 1
}
[[ ${TARGET_USER} =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
    printf 'Nombre de usuario no compatible con sudoers: %s\n' "${TARGET_USER}" >&2
    exit 1
}

command -v python3 >/dev/null || { printf 'python3 is missing.\n' >&2; exit 1; }
python3 -c 'import PyQt6' >/dev/null 2>&1 || {
    printf 'PyQt6 is missing. Install it with: sudo dnf install python3-pyqt6\n' >&2
    exit 1
}
command -v nvidia-smi >/dev/null || { printf 'nvidia-smi or the NVIDIA driver is missing.\n' >&2; exit 1; }
[[ -x /usr/local/bin/ryzenadj ]] || command -v ryzenadj >/dev/null \
    || { printf 'ryzenadj is missing.\n' >&2; exit 1; }

install -o root -g root -m 0755 \
    "${PROJECT_DIR}/workstation-power-profile-helper" \
    /usr/local/sbin/workstation-power-profile-helper
install -o root -g root -m 0755 \
    "${PROJECT_DIR}/power_profile_gui.py" \
    /usr/local/bin/workstation-power-profile-gui
install -o root -g root -m 0755 \
    "${PROJECT_DIR}/workstation-power-metrics" \
    /usr/local/sbin/workstation-power-metrics
install -o root -g root -m 0644 \
    "${PROJECT_DIR}/workstation-power-profile.service" \
    /etc/systemd/system/workstation-power-profile.service
install -o root -g root -m 0644 \
    "${PROJECT_DIR}/workstation-power-metrics.service" \
    /etc/systemd/system/workstation-power-metrics.service
install -o root -g root -m 0644 \
    "${PROJECT_DIR}/ryzen_smu.conf" \
    /etc/modules-load.d/ryzen_smu.conf
install -o root -g root -m 0644 \
    "${PROJECT_DIR}/workstation-power-profile.desktop" \
    /usr/share/applications/workstation-power-profile.desktop
install -D -o "${TARGET_USER}" -g "$(id -gn "${TARGET_USER}")" -m 0644 \
    "${PROJECT_DIR}/workstation-power-profile.desktop" \
    "${TARGET_HOME}/.config/autostart/workstation-power-profile.desktop"
install -D -o "${TARGET_USER}" -g "$(id -gn "${TARGET_USER}")" -m 0755 \
    "${PROJECT_DIR}/gpu-watts-panel" \
    "${TARGET_HOME}/.local/bin/gpu-watts-panel"

if [[ ! -r /var/lib/workstation-power-profile/stock.env ]]; then
    /usr/local/sbin/workstation-power-profile-helper capture-defaults
fi

sudoers_line="${TARGET_USER} ALL=(root) NOPASSWD: /usr/local/sbin/workstation-power-profile-helper quiet, /usr/local/sbin/workstation-power-profile-helper eco, /usr/local/sbin/workstation-power-profile-helper balanced, /usr/local/sbin/workstation-power-profile-helper cpu-focus, /usr/local/sbin/workstation-power-profile-helper ai, /usr/local/sbin/workstation-power-profile-helper custom *, /usr/local/sbin/workstation-power-profile-helper max"
SUDOERS_TEMP="$(mktemp)"
printf '%s\n' "${sudoers_line}" >"${SUDOERS_TEMP}"
visudo -cf "${SUDOERS_TEMP}" >/dev/null
install -o root -g root -m 0440 "${SUDOERS_TEMP}" "${SUDOERS_FILE}"
systemctl daemon-reload
systemctl enable workstation-power-metrics.service
systemctl restart workstation-power-metrics.service

printf '\nInstalled. The GUI starts with KDE and appears as "Workstation Power Profiles".\n'
printf 'Optional Eco profile at boot: sudo systemctl enable --now workstation-power-profile.service\n'
