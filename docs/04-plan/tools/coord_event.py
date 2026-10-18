#!/usr/bin/env python3
"""共享事件登记（append-only JSONL）+ 自动看板渲染。

各线只需 append 自己的事件；CURRENT.md / BOARD.generated.md 自动生成。
事件日志：$DATA/coordination/events.jsonl
渲染输出：
  $DATA/coordination/CURRENT.md
  $DATA/coordination/BOARD.generated.md
  $DATA/handoff/2026-10-18/CURRENT.md

约定：
- 只追加，不修改旧事件；不写原文、个人信息、登录态、原始正文。
- summary <= 300 字符；refs 只放 commit/path/hash/id/命令等可核对信息。
- 事件类型：commit/artifact/handoff/ack/blocker/resolved/metric/note/loop。
- 冲突处理：append 用文件锁；渲染读取全部事件，后写覆盖前写。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(os.environ.get("JUSTILAW_DATA_DIR", r"D:/02_Dev/Data/justilaw-research"))
COORD = DATA_ROOT / "coordination"
EVENTS = COORD / "events.jsonl"
LOCK = COORD / "events.lock"
CURRENT = COORD / "CURRENT.md"
BOARD = COORD / "BOARD.generated.md"
MIRROR = DATA_ROOT / "handoff" / "2026-10-18" / "CURRENT.md"

LINES = ("engine", "postprocessing", "coordination", "data", "user")
TYPES = ("commit", "artifact", "handoff", "ack", "blocker", "resolved", "metric", "note", "loop")
STATUSES = ("done", "wip", "blocked", "open", "current", "stale", "planned", "closed")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id(prefix: str = "evt") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def git_info() -> dict:
    """Capture the caller worktree's commit/branch/dirty state, if available."""
    try:
        def run(*args: str) -> str:
            return subprocess.check_output(
                ["git", *args], text=True, stderr=subprocess.DEVNULL, cwd=os.getcwd()
            ).strip()

        dirty = bool(run("status", "--porcelain"))
        return {
            "commit": run("rev-parse", "--short", "HEAD"),
            "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": "true" if dirty else "false",
        }
    except Exception:
        return {}


@contextmanager
def locked():
    """Serialize appends across worktrees. Windows: msvcrt; POSIX: flock."""
    COORD.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def validate(ev: dict) -> dict:
    if ev.get("line") not in LINES:
        raise SystemExit(f"line 必须是 {LINES}")
    if ev.get("type") not in TYPES:
        raise SystemExit(f"type 必须是 {TYPES}")
    if ev.get("status") is not None and ev["status"] not in STATUSES:
        raise SystemExit(f"status 必须是 {STATUSES} 或省略")
    summary = str(ev.get("summary") or "").strip()
    if not summary:
        raise SystemExit("summary 不能为空")
    if "\n" in summary or "\r" in summary:
        raise SystemExit("summary 不能换行")
    if len(summary) > 300:
        raise SystemExit("summary 超过 300 字符；细节放 refs/path")
    ev["summary"] = summary
    refs = ev.get("refs") or {}
    if not isinstance(refs, dict):
        raise SystemExit("refs 必须是对象")
    ev["refs"] = {str(k): str(v) for k, v in refs.items() if v is not None}
    tags = ev.get("tags") or []
    if not isinstance(tags, list):
        raise SystemExit("tags 必须是数组")
    ev["tags"] = [str(t) for t in tags][:10]
    return ev


def append(ev: dict) -> dict:
    ev = {
        "schema": 1,
        "id": ev.get("id") or new_id(),
        "ts": now(),
        **{k: v for k, v in ev.items() if k not in ("schema", "id", "ts")},
    }
    ev = validate(ev)
    COORD.mkdir(parents=True, exist_ok=True)
    line = json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n"
    with locked():
        with open(EVENTS, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
    render()
    return ev


def read_events() -> list[dict]:
    if not EVENTS.exists():
        return []
    out = []
    for line in EVENTS.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def render() -> Path:
    events = read_events()
    latest: dict = {}
    latest_meaningful: dict = {}
    for e in events:
        line = e.get("line")
        latest[line] = e
        if e.get("type") not in ("metric", "artifact"):
            latest_meaningful[line] = e

    handoffs: dict[str, dict] = {}
    blockers: dict[str, dict] = {}
    metrics: dict[str, dict] = {}
    artifacts: dict[str, dict] = {}
    for e in events:
        refs = e.get("refs") or {}
        if e["type"] == "handoff":
            hid = refs.get("handoff_id") or e["id"]
            if e.get("status") in ("closed", "done"):
                handoffs.pop(hid, None)
            else:
                handoffs[hid] = e
        elif e["type"] == "ack":
            hid = refs.get("handoff_id")
            if hid:
                handoffs.pop(hid, None)
        elif e["type"] == "blocker":
            bid = refs.get("blocker_id") or e["id"]
            if e.get("status") not in ("done", "closed", "resolved"):
                blockers[bid] = e
        elif e["type"] == "resolved":
            bid = refs.get("blocker_id")
            if bid:
                blockers.pop(bid, None)
        elif e["type"] == "metric" and refs.get("name"):
            metrics[refs["name"]] = e
        elif e["type"] == "artifact" and refs.get("path"):
            artifacts[refs["path"]] = e

    loop = next((e for e in reversed(events) if e["type"] == "loop"), None) or latest.get("coordination")

    def esc(value) -> str:
        return str(value).replace("|", "\\|")

    def refs_str(e: dict) -> str:
        return "; ".join(f"{k}={v}" for k, v in (e.get("refs") or {}).items())

    lines = [
        "# CURRENT（自动生成，勿手改）\n",
        f"> 生成：{now()}；事件源：`{EVENTS}`（{len(events)} 条）。",
        "> 修改请 append，不要手改本文件；权威提交快照见协调分支 `BOARD.md`。\n",
        "## 当前循环\n",
    ]
    if loop:
        refs = loop.get("refs") or {}
        lines.append(f"- **状态**：{loop.get('status') or ''}")
        lines.append(f"- **摘要**：{loop.get('summary', '')}")
        if refs.get("owner"):
            lines.append(f"- **Owner**：{refs['owner']}")
        if refs.get("next"):
            lines.append(f"- **下一步**：{refs['next']}")
    else:
        lines.append("- 暂无 loop 事件。")

    lines += ["\n## 各线最新\n", "| 线 | 时间 | 类型 | 状态 | 摘要 | 引用 |", "|---|---|---|---|---|---|"]
    for line in LINES:
        e = latest_meaningful.get(line) or latest.get(line)
        if e:
            lines.append(
                f"| {line} | {e.get('ts', '')} | {e.get('type', '')} | {e.get('status') or '-'} | "
                f"{esc(e.get('summary', ''))} | {esc(refs_str(e))} |"
            )

    lines.append("\n## 待 ack 交接\n")
    if handoffs:
        for hid, e in handoffs.items():
            refs = e.get("refs") or {}
            lines.append(
                f"- `{hid}` {e['summary']}（{e.get('ts', '')}）to={refs.get('to', '')} "
                f"accept={refs.get('accept', '')}"
            )
    else:
        lines.append("- 无")

    lines.append("\n## 未关闭阻塞\n")
    if blockers:
        for bid, e in blockers.items():
            refs = e.get("refs") or {}
            lines.append(
                f"- `{bid}` {e['summary']}；owner={refs.get('owner', '')}；next={refs.get('next', '')}"
            )
    else:
        lines.append("- 无")

    lines += ["\n## 指标\n", "| 指标 | 值 | 时间 | 说明 |", "|---|---|---|---|"]
    for name, e in metrics.items():
        refs = e.get("refs") or {}
        lines.append(
            f"| {esc(name)} | {esc(refs.get('value', ''))} | {e.get('ts', '')} | {esc(e['summary'])} |"
        )

    lines.append("\n## 最近产物\n")
    if artifacts:
        for path, e in list(artifacts.items())[-10:]:
            refs = e.get("refs") or {}
            lines.append(
                f"- `{path}` {refs.get('version', '')} `{refs.get('hash', '')}` — "
                f"{e['summary']}（{e.get('status', '')}）"
            )
    else:
        lines.append("- 无")

    lines.append("\n## 最近事件\n")
    for e in events[-12:]:
        lines.append(
            f"- {e.get('ts', '')} **{e.get('line', '')}/{e.get('type', '')}** "
            f"{e.get('summary', '')} [{e.get('status') or '-'}]"
        )

    text = "\n".join(lines) + "\n"
    write_atomic(CURRENT, text)
    write_atomic(BOARD, text)
    write_atomic(MIRROR, text)
    return CURRENT


def parse_refs(raw: list[str]) -> dict:
    refs = {}
    for item in raw:
        if "=" not in item:
            raise SystemExit(f"--ref 需要 key=value：{item}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise SystemExit("--ref key 不能为空")
        refs[key.strip()] = value
    return refs


def base_event(args) -> dict:
    refs = parse_refs(getattr(args, "ref", []) or [])
    if getattr(args, "owner", None):
        refs["owner"] = args.owner
    if getattr(args, "next", None):
        refs["next"] = args.next
    return {
        "line": args.line,
        "type": args.type,
        "summary": args.summary,
        "status": getattr(args, "status", None),
        "refs": refs,
        "tags": getattr(args, "tag", []) or [],
    }


def cmd_append(args) -> dict:
    return base_event(args)


def cmd_commit(args) -> dict:
    ev = base_event(args)
    refs = git_info()
    refs.update(ev["refs"])
    ev["refs"] = refs
    return ev


def cmd_artifact(args) -> dict:
    ev = base_event(args)
    ev["refs"].update({"path": args.path, "hash": args.hash})
    if args.version:
        ev["refs"]["version"] = args.version
    return ev


def cmd_handoff(args) -> dict:
    ev = base_event(args)
    hid = args.id or new_id("ho")
    ev["refs"].update({"handoff_id": hid, "to": args.to, "accept": args.accept})
    if args.deadline:
        ev["refs"]["deadline"] = args.deadline
    print(f"handoff_id={hid}")
    return ev


def cmd_ack(args) -> dict:
    ev = base_event(args)
    ev["refs"]["handoff_id"] = args.handoff_id
    return ev


def cmd_blocker(args) -> dict:
    ev = base_event(args)
    bid = args.id or new_id("blk")
    ev["refs"]["blocker_id"] = bid
    ev["refs"]["owner"] = args.owner
    ev["refs"]["next"] = args.next
    print(f"blocker_id={bid}")
    return ev


def cmd_resolve(args) -> dict:
    ev = base_event(args)
    ev["refs"]["blocker_id"] = args.blocker_id
    return ev


def cmd_metric(args) -> dict:
    ev = base_event(args)
    ev["refs"].update({"name": args.name, "value": args.value})
    if not args.summary:
        ev["summary"] = f"{args.name}={args.value}"
    return ev


def cmd_loop(args) -> dict:
    ev = base_event(args)
    ev["refs"]["owner"] = args.owner
    ev["refs"]["next"] = args.next
    return ev


def cmd_tail(args) -> int:
    events = read_events()
    for e in events[-args.limit:]:
        print(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
    return 0


def cmd_render(_args) -> int:
    print(render())
    return 0


def add_common(p, *, status=True, owner=False, next_=False, tags=True) -> None:
    p.add_argument("--line", required=True, choices=LINES)
    p.add_argument("--summary", required=True)
    if status:
        p.add_argument("--status", default=None, choices=STATUSES)
    if owner:
        p.add_argument("--owner")
    if next_:
        p.add_argument("--next")
    if tags:
        p.add_argument("--tag", action="append", default=[])
    p.add_argument("--ref", action="append", default=[])


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="通用事件")
    add_common(p, owner=True, next_=True)
    p.add_argument("--type", required=True, choices=TYPES)
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("commit", help="登记提交；自动带当前工作树 commit/branch/dirty")
    add_common(p, next_=True)
    p.set_defaults(func=cmd_commit, type="commit", status="done")

    p = sub.add_parser("artifact", help="登记产物路径/哈希")
    add_common(p)
    p.add_argument("--path", required=True)
    p.add_argument("--hash", required=True)
    p.add_argument("--version")
    p.set_defaults(func=cmd_artifact, type="artifact", status="current")

    p = sub.add_parser("handoff", help="登记跨线交接")
    add_common(p)
    p.add_argument("--to", required=True)
    p.add_argument("--accept", required=True)
    p.add_argument("--deadline")
    p.add_argument("--id")
    p.set_defaults(func=cmd_handoff, type="handoff", status="open")

    p = sub.add_parser("ack", help="交接 ack/结果")
    add_common(p)
    p.add_argument("--handoff-id", required=True)
    p.set_defaults(func=cmd_ack, type="ack", status="done")

    p = sub.add_parser("blocker", help="登记未关闭阻塞")
    add_common(p, owner=False, next_=False)
    p.add_argument("--owner", required=True)
    p.add_argument("--next", required=True)
    p.add_argument("--id")
    p.set_defaults(func=cmd_blocker, type="blocker", status="open")

    p = sub.add_parser("resolve", help="关闭阻塞")
    add_common(p)
    p.add_argument("--blocker-id", required=True)
    p.set_defaults(func=cmd_resolve, type="resolved", status="done")

    p = sub.add_parser("metric", help="登记核心指标")
    add_common(p, status=False)
    p.add_argument("--name", required=True)
    p.add_argument("--value", required=True)
    p.set_defaults(func=cmd_metric, type="metric")

    p = sub.add_parser("loop", help="登记当前循环")
    add_common(p, owner=False, next_=False)
    p.add_argument("--owner", required=True)
    p.add_argument("--next", required=True)
    p.set_defaults(func=cmd_loop, type="loop", status="wip")

    p = sub.add_parser("note", help="普通状态/备注")
    add_common(p, next_=True)
    p.set_defaults(func=cmd_append, type="note")

    p = sub.add_parser("tail", help="查看最近事件")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_tail)

    p = sub.add_parser("render", help="重新渲染 CURRENT/BOARD.generated")
    p.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    if args.cmd == "tail":
        return args.func(args)
    if args.cmd == "render":
        return args.func(args)
    ev = args.func(args)
    saved = append(ev)
    print(json.dumps({"id": saved["id"], "current": str(CURRENT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
