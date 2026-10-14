#!/usr/bin/env bash
# JustiLawAI 单机一键启动（macOS / Linux）：准备 Python 环境 → 检测 Ollama → 启动服务 → 打开浏览器。
# 用法：bash launcher/start.sh [端口]     （macOS 也可双击 start.command）
# 首次运行会创建 justilaw-api/.venv 并安装依赖；没有 Python 3.10+ 时可自动安装 uv 并用它准备 Python。
# 模型的下载与配置在网页里的「模型连接向导」完成，本脚本不拉取模型。
set -euo pipefail

PORT="${1:-8000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(basename "$HERE")" = "launcher" ]; then ROOT="$(dirname "$HERE")"; else ROOT="$HERE"; fi
API="$ROOT/justilaw-api"
VENV="$API/.venv"
VENV_PY="$VENV/bin/python"
WEB_DIST="$ROOT/justilaw-web/dist"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m%s\033[0m\n' "$1"; }
warn() { printf '    \033[33m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m[错误] %s\033[0m\n' "$1"; exit 1; }
# 本机地址不能走系统代理
get() { curl -fsS --noproxy '*' -m 3 "$1" 2>/dev/null; }
open_url() { if command -v open >/dev/null; then open "$1"; elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1 || true; fi; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
# 端口上是不是"单机版 JustiLawAI"：鉴权关闭且托管了网页（开发用的后端只提供 API，不能当成已在运行）
is_local_justilaw() {
  get "http://127.0.0.1:$1/api/v1/health" | grep -q '"auth_enabled":false' &&
    curl -fsS --noproxy '*' -m 3 -o /dev/null -w '%{content_type}' "http://127.0.0.1:$1/" 2>/dev/null | grep -q '^text/html'
}

echo "JustiLawAI 单机版"
echo "目录：$ROOT"

# ---------- 1. 已在运行则直接打开 ----------
if is_local_justilaw "$PORT"; then
  ok "服务已在运行：http://127.0.0.1:$PORT"
  open_url "http://127.0.0.1:$PORT"
  exit 0
fi
if port_busy "$PORT"; then
  ORIG="$PORT"
  while port_busy "$PORT"; do PORT=$((PORT + 1)); done
  warn "端口 $ORIG 被其他程序占用，改用 $PORT"
fi
[ -f "$WEB_DIST/index.html" ] || fail "缺少网页文件 $WEB_DIST/index.html。请使用发布包，或先在 justilaw-web 目录执行 pnpm install && pnpm build"

# ---------- 2. Python 环境 ----------
step "准备 Python 环境"
if [ ! -x "$VENV_PY" ]; then
  PY=""
  for c in python3 python; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -n "$PY" ]; then
    ok "使用 Python：$PY"
    "$PY" -m venv "$VENV"
  else
    warn "没有找到 Python 3.10 或更高版本。"
    if ! command -v uv >/dev/null; then
      read -r -p "是否自动安装 uv（Astral 官方工具，用于下载独立的 Python）？[Y/n] " ans
      case "$ans" in [nN]*) fail "请先安装 Python 3.10+ 后重新运行" ;; esac
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
      command -v uv >/dev/null || fail "uv 安装失败，请手动安装 Python 3.10+ 后重试"
    fi
    uv venv --python 3.12 "$VENV"
  fi
  [ -x "$VENV_PY" ] || fail "创建 Python 虚拟环境失败"
fi

install_deps() {
  if command -v uv >/dev/null; then uv pip install --python "$VENV_PY" -r "$API/requirements.txt" "$@"
  else "$VENV_PY" -m pip install --disable-pip-version-check -r "$API/requirements.txt" "$@"; fi
}
HASH="$( (sha256sum "$API/requirements.txt" 2>/dev/null || shasum -a 256 "$API/requirements.txt") | cut -d' ' -f1)"
STAMP="$VENV/.requirements.sha256"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$HASH" ]; then
  step "安装依赖（首次运行约 1-3 分钟）"
  install_deps || { warn "默认源安装失败，改用国内镜像重试…"; install_deps -i "$MIRROR" || fail "依赖安装失败，请检查网络后重试"; }
  echo "$HASH" > "$STAMP"
fi
ok "Python 环境就绪"

# ---------- 3. Ollama ----------
step "检测 Ollama"
if V="$(get http://127.0.0.1:11434/api/version)"; then
  ok "Ollama 已运行：$V"
elif [ "$(uname)" = "Darwin" ] && [ -d /Applications/Ollama.app ]; then
  warn "Ollama 已安装但未运行，正在启动…"; open -a Ollama
elif command -v ollama >/dev/null; then
  warn "Ollama 已安装但未运行，正在后台启动 ollama serve…"; (nohup ollama serve >/dev/null 2>&1 &)
else
  warn "没有检测到 Ollama。将打开下载页：安装后网页里的向导会自动连接（服务照常启动）。"
  open_url "https://ollama.com/download"
fi

# ---------- 4. 启动服务 ----------
step "启动服务：http://127.0.0.1:$PORT"
export PYTHONIOENCODING=utf-8 WEB_DIST_DIR="$WEB_DIST"
( for _ in $(seq 1 60); do
    if get "http://127.0.0.1:$PORT/api/v1/health" >/dev/null; then open_url "http://127.0.0.1:$PORT"; exit 0; fi
    sleep 0.5
  done ) &
echo "    按 Ctrl+C 或关闭终端即停止服务。数据保存在 justilaw-api/store。"
cd "$API"
exec "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
