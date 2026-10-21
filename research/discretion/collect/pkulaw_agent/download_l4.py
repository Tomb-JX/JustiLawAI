"""L4 Word 补救下载：CDP 连接常驻 Chrome，逐条开详情页→点「下载WORD」→收文件。

用法：
    python -m pkulaw_agent.download_l4 [--cap 320] [--interval 2.5]

自动读取 inbox/pkulaw/20261018-P2/runs/l4-word-download/results.jsonl。
下载到 inbox/pkulaw/20261018-P2/word/。
断点续传：已下载的 gid 跳过。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pkulaw_agent.session import data_dir


def main():
    ap = argparse.ArgumentParser(description="L4 Word 补救下载（CDP）")
    ap.add_argument("--cap", type=int, default=400, help="最大下载数")
    ap.add_argument("--interval", type=float, default=2.5, help="最小请求间隔秒")
    ap.add_argument("--run-dir", default="", help="含 results.jsonl 的目录")
    ap.add_argument("--out-dir", default="", help="Word 文件保存目录")
    args = ap.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else data_dir() / "inbox" / "pkulaw" / "20261018-P2" / "runs" / "l4-word-download"
    out_dir = Path(args.out_dir) if args.out_dir else data_dir() / "inbox" / "pkulaw" / "20261018-P2" / "word"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载 worklist
    results_file = run_dir / "results.jsonl"
    if not results_file.exists():
        print(f"未找到 {results_file}")
        return 1
    records = [json.loads(l) for l in results_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"加载 {len(records)} 条 L4 记录")

    # 断点续传
    done_file = out_dir / "download_done.jsonl"
    done_ids: set[str] = set()
    if done_file.exists():
        for line in done_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done_ids.add(json.loads(line).get("gid", ""))
        print(f"已下载 {len(done_ids)} 条，跳过")

    remaining = [r for r in records if r["gid"] not in done_ids]
    if not remaining:
        print("全部已下载")
        return 0

    # 连接 CDP
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()

    done_log = done_file.open("a", encoding="utf-8")
    last_time = 0.0
    ok_count = 0
    fail_count = 0

    # 单页复用，不弹新标签
    page = ctx.new_page()

    try:
        for i, rec in enumerate(remaining, 1):
            if ok_count >= args.cap:
                print(f"\n达到上限 {args.cap}，停止")
                break

            url = rec.get("url", "")
            if not url:
                continue

            # 限速
            elapsed = time.time() - last_time
            if elapsed < args.interval:
                time.sleep(args.interval - elapsed)
            last_time = time.time()

            label = rec.get("doc_no") or rec.get("title") or rec["gid"]
            print(f"  [{i}/{len(remaining)}] {rec['gid']} {label[:40]}…", end="", flush=True)

            saved = None
            try:
                page.goto(url, wait_until="load", timeout=30_000)
                page.wait_for_timeout(2500)

                # 安全验证检查
                if "安全验证" in page.title():
                    print("\n⚠️ 安全验证页，请在浏览器中完成验证后按 Enter")
                    input()
                    page.goto(url, wait_until="load", timeout=30_000)
                    page.wait_for_timeout(2500)

                # 点「下载WORD」
                link = page.locator('a:has-text("下载WORD")')
                if link.count() > 0 and link.first.is_visible():
                    with page.expect_download(timeout=15_000) as dl_info:
                        link.first.click()
                    dl = dl_info.value
                    fname = dl.suggested_filename or f"{rec['gid']}.doc"
                    dst = out_dir / fname
                    n = 1
                    while dst.exists():
                        dst = out_dir / f"{Path(fname).stem}-{n}{Path(fname).suffix}"
                        n += 1
                    dl.save_as(str(dst))
                    saved = str(dst)
                    ok_count += 1
                    print(f" ✓ {dst.name}")
                else:
                    link2 = page.locator('a:has-text("下载PDF")')
                    if link2.count() > 0 and link2.first.is_visible():
                        with page.expect_download(timeout=15_000) as dl_info:
                            link2.first.click()
                        dl = dl_info.value
                        fname = dl.suggested_filename or f"{rec['gid']}.pdf"
                        dst = out_dir / fname
                        dl.save_as(str(dst))
                        saved = str(dst)
                        ok_count += 1
                        print(f" ✓ PDF {dst.name}")
                    else:
                        fail_count += 1
                        print(" ✗ 无下载链接")

            except Exception as exc:
                fail_count += 1
                print(f" ✗ {type(exc).__name__}: {str(exc)[:60]}")

            done_log.write(json.dumps({
                "gid": rec["gid"], "doc_no": rec.get("doc_no", ""),
                "ok": saved is not None, "file": saved or ""
            }, ensure_ascii=False) + "\n")
            done_log.flush()

    except KeyboardInterrupt:
        print(f"\n手动中断，已成功 {ok_count}")
    finally:
        done_log.close()
        try:
            browser.close()
        except Exception:
            pass
        pw.stop()

    print(f"\n✓ 完成：{ok_count} 成功 / {fail_count} 失败 / {len(remaining)} 总计")
    print(f"  文件目录：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())