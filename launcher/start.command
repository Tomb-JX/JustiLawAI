#!/bin/bash
# macOS 双击启动 JustiLawAI（首次可能需要：右键 → 打开）
D="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$D/start.sh" ]; then exec bash "$D/start.sh" "$@"; else exec bash "$D/launcher/start.sh" "$@"; fi
