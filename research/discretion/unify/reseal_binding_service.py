"""Copy the frozen v1 weights into a new, source-pinned binding-v1.1 release.

No model is trained or called. The old artifact directory is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import binding_service


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_files(root: Path) -> dict[str, str]:
    paths = {Path(module.__file__).resolve() for module in sys.modules.values()
             if getattr(module, "__file__", None)
             and Path(module.__file__).resolve().parent == root
             and Path(module.__file__).name != "reseal_binding_service.py"}
    return {p.name: sha(p) for p in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.out.resolve()
    if out.exists() or out == source or source in out.parents:
        raise ValueError("output_must_be_a_new_separate_directory")
    old_bytes = (source / "MANIFEST.json").read_bytes()
    old = json.loads(old_bytes)
    if old.get("version") != "binding-v1":
        raise ValueError("expected_binding_v1_source")
    for rel, expected in old["files"].items():
        path = (source / rel).resolve()
        if source not in path.parents or sha(path) != expected:
            raise ValueError("source_artifact_hash_mismatch:" + rel)
    root = Path(binding_service.__file__).resolve().parent
    engine_root = args.engine_root.resolve()
    engine_paths = sorted((engine_root / "app/discretion").glob("*.py"))
    eval_root = engine_root.parent / "research/eval"
    eval_paths = [eval_root / name for name in ("normalization_spec.py", "evidence_contract.py", "binding_rules.py")]
    if not engine_paths or not (engine_root / "app/discretion/binding.py").is_file():
        raise ValueError("engine_source_missing")
    if any(not path.is_file() for path in eval_paths):
        raise ValueError("engine_eval_source_missing")
    out.mkdir(parents=True)
    for rel in old["files"]:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dest)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest = {**old, "version": binding_service.VERSION, "code_revision": revision,
                "source_manifest_sha256": hashlib.sha256(old_bytes).hexdigest(),
                "policy": "amounts bound only when all three routes select the same candidate and typed range; "
                          "all other cases unresolved for review",
                "runtime_files": runtime_files(root),
                "engine_files": {p.relative_to(engine_root).as_posix(): sha(p) for p in engine_paths},
                "eval_files": {p.name: sha(p) for p in eval_paths}}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"version": manifest["version"], "code_revision": revision,
                      "runtime_files": len(manifest["runtime_files"]),
                      "engine_files": len(manifest["engine_files"]),
                      "eval_files": len(manifest["eval_files"]), "out": str(out)}))


if __name__ == "__main__":
    main()
