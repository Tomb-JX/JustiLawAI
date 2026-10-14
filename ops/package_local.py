"""打包 JustiLawAI 单机版发布包（Windows / macOS / Linux 通用，本地与 CI 共用）。

产物：release/JustiLawAI-local-<版本>.zip 及同名 .sha256
包内：justilaw-api（不含 store / .venv / .env / 测试样例）、构建好的 justilaw-web/dist、启动脚本与使用说明。
Python 依赖不打包，首次启动时由启动脚本安装。

zip 内记录 Unix 权限：.sh / .command 带可执行位，macOS / Linux 解压后可直接运行或双击。

用法：
  python ops/package_local.py                  # 构建前端并打包，版本取 git describe
  python ops/package_local.py --version v0.1.0 --skip-build
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "justilaw-web"
API = ROOT / "justilaw-api"
LAUNCHER = ROOT / "launcher"
OUT = ROOT / "release"
TOP = "JustiLawAI"   # 解压后的顶层目录名

API_EXCLUDE_DIRS = {"store", ".venv", "__pycache__"}
API_EXCLUDE_FILES = {".env"}
EXECUTABLE = {".sh", ".command"}


def run(cmd: list[str], cwd: Path):
    print("  $", " ".join(cmd))
    # Windows 上 pnpm 是 .cmd，需要经 shell 解析
    subprocess.run(cmd, cwd=cwd, check=True, shell=sys.platform == "win32")


def git_version() -> str:
    try:
        return subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "dev"


def api_files():
    for p in sorted(API.rglob("*")):
        rel = p.relative_to(API)
        if p.is_dir() or any(part in API_EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name in API_EXCLUDE_FILES or p.suffix == ".pyc" or (p.name.startswith("test-") and p.suffix == ".json"):
            continue
        yield p, f"{TOP}/justilaw-api/{rel.as_posix()}"


def package_entries():
    yield from api_files()
    dist = WEB / "dist"
    for p in sorted(dist.rglob("*")):
        if p.is_file():
            yield p, f"{TOP}/justilaw-web/dist/{p.relative_to(dist).as_posix()}"
    for name in ("start.ps1", "start.sh"):
        yield LAUNCHER / name, f"{TOP}/launcher/{name}"
    # 双击入口放在包根目录，使用说明作为 README
    for name in ("Start-JustiLaw.bat", "start.command"):
        yield LAUNCHER / name, f"{TOP}/{name}"
    yield LAUNCHER / "README.md", f"{TOP}/README.md"


def read_for_zip(src: Path) -> bytes:
    data = src.read_bytes()
    # 不依赖检出方式（Windows 上 autocrlf 可能把 sh 转成 CRLF）：sh 强制 LF，bat / ps1 强制 CRLF
    if src.suffix in EXECUTABLE:
        data = data.replace(b"\r\n", b"\n")
    elif src.suffix in (".bat", ".ps1"):
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="版本号（默认 git describe），用于文件名")
    ap.add_argument("--skip-build", action="store_true", help="复用已有的 justilaw-web/dist")
    args = ap.parse_args()
    version = args.version or git_version()

    if not args.skip_build:
        print("==> 构建前端")
        run(["pnpm", "install", "--frozen-lockfile"], WEB)
        run(["pnpm", "build"], WEB)
    if not (WEB / "dist" / "index.html").exists():
        sys.exit("缺少 justilaw-web/dist，请去掉 --skip-build 重新打包")

    print("==> 打包")
    OUT.mkdir(exist_ok=True)
    zip_path = OUT / f"JustiLawAI-local-{version}.zip"
    zip_path.unlink(missing_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in package_entries():
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3   # Unix：让 external_attr 里的权限位生效
            mode = 0o755 if src.suffix in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, read_for_zip(src))
            count += 1

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (OUT / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n", "utf-8")
    size = zip_path.stat().st_size / 1024 / 1024
    print(f"完成：{zip_path}（{count} 个文件，{size:.1f} MB）\nSHA256：{digest}")


if __name__ == "__main__":
    main()
