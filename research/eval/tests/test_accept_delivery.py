"""交付验收：三档结论与退回清单（合成交付目录，不读真实数据）。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "justilaw-api" / "tests" / "discretion"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import accept_delivery as A  # noqa: E402
from test_records import delivery  # noqa: E402


def write_delivery(folder: Path, main: list[dict], only: list[dict]) -> None:
    sums = []
    for name, rows in ((A.MAIN, main), (A.ONLY, only)):
        p = folder / name
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
        sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}")
    (folder / "SHA256SUMS").write_text("\n".join(sums) + "\n", "utf-8")


def records(n: int, start: int = 1) -> list[dict]:
    out = []
    for i in range(start, start + n):
        r = delivery()
        r["id"], r["event_id"] = f"W-{i:06d}", f"E-{i}"
        out.append(r)
    return out


def test_clean_delivery_passes(tmp_path):
    src = tmp_path / "d"
    src.mkdir()
    write_delivery(src, records(3), records(1, start=10))
    rep = A.accept(src, out_root=tmp_path / "out")
    assert rep["verdict"] == "通过" and rep["accepted_main"] == 3
    assert not (src / "r6_report.json").exists()
    assert (Path(rep["out_dir"]) / "acceptance.md").exists()
    gaps = rep["gate_stats_on_accepted"]["gaps"]
    assert any("金标目标" in g for g in gaps)
    A.accept(src, out_root=tmp_path / "out")      # 重验同一交付：索引只追加
    rows = (tmp_path / "out" / "INDEX.csv").read_text("utf-8").splitlines()
    assert rows[0].startswith("checked_at,delivery_version") and len(rows) == 3
    assert rows[1].split(",")[1] == "d" and rows[1].split(",")[4] == "通过"


def test_bad_record_is_rejected_but_batch_partially_passes(tmp_path):
    src = tmp_path / "d"
    src.mkdir()
    main = records(3)
    main[1]["outcome"]["fine"] = 99999          # 超出旧法罚款上限，且与"拘留"类型不符
    write_delivery(src, main, [])
    rep = A.accept(src, out_root=tmp_path / "out")
    assert rep["verdict"] == "部分通过" and rep["rejected"] == 1 and rep["accepted_main"] == 2
    rejected = (Path(rep["out_dir"]) / "rejected.csv").read_text("utf-8")
    assert "W-000002" in rejected and "fine_over_limit" in rejected


def test_file_changed_after_release_fails(tmp_path):
    src = tmp_path / "d"
    src.mkdir()
    write_delivery(src, records(2), [])
    with (src / A.MAIN).open("a", encoding="utf-8") as f:   # 发布后又被改写
        f.write(json.dumps(records(1, start=5)[0], ensure_ascii=False) + "\n")
    rep = A.accept(src, out_root=tmp_path / "out")
    assert rep["verdict"] == "不通过"
    assert any(b["code"] == "file_sha_mismatch" for b in rep["batch_checks"])


def test_duplicate_ids_fail_the_batch(tmp_path):
    src = tmp_path / "d"
    src.mkdir()
    write_delivery(src, records(2), records(1))           # outcomes 文件里的 W-000001 与主文件重号
    rep = A.accept(src, out_root=tmp_path / "out")
    assert rep["verdict"] == "不通过"
    assert any(b["code"] == "duplicate_id" for b in rep["batch_checks"])
