#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BG_OPT=()

for ext in jpg jpeg png webp; do
    if [[ -f "${BASE_DIR}/assets/whale.${ext}" ]]; then
        BG_OPT=(
            -o "background_image=${BASE_DIR}/assets/whale.${ext}"
            -o "background_image_layout=scaled"
            -o "background_tint=0.14"
        )
        break
    fi
done

exec kitty \
    --start-as=fullscreen \
    -o "background=#05060a" \
    -o "foreground=#eceff4" \
    -o "font_size=7.0" \
    -o "window_padding_width=4" \
    -o "hide_window_decorations=yes" \
    -o "confirm_os_window_close=0" \
    -o "enable_audio_bell=no" \
    "${BG_OPT[@]}" \
    -e "${BASE_DIR}/.venv/bin/python" "${BASE_DIR}/src/app.py" "$@"
