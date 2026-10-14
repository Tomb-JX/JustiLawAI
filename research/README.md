# research/：裁量引擎的研究资料、训练与评测

与线上服务（`justilaw-api/`）分开存放，避免训练依赖（LightGBM、NumPyro、PEFT 等）进入 API。

| 路径 | 内容 | 入库 |
|---|---|---|
| `papers/manifest.csv` | 文献清单（128 条，arXiv 链接固定版本号） | 是 |
| `papers/fetch_papers.py` | 按清单下载 PDF 并生成校验和 | 是 |
| `papers/checksums.tsv` | 每个 PDF 的 SHA-256 | 是 |
| `papers/pdf/` | 论文 PDF | **否**（arXiv 许可只授权 arXiv 分发） |
| `discretion/collect/` | 数据采集脚本与来源台账（数据链路负责，见[分工](../docs/04-plan/workstreams.md)） | 是 |
| `.venv/` | 研究用虚拟环境（训练、评测依赖） | **否** |
| `eval/metrics.py` | 门禁文档 §3 全部指标的唯一实现（只依赖 numpy） | 是 |
| `eval/tests/` | 指标与 scikit-learn、pytrec_eval、CAIL 官方公式的一致性测试 | 是 |
| `eval/anchor_a2/` | 公开锚点 A2（CAIL2018 赌博子集）：数据准备、划分 id、基线与探针；讲解见 [学习笔记](../docs/05-research/notes/A2-baselines.md) | 是（只含 id，不含文书） |
| `eval/leaderboard.csv` | 冻结基线与各门禁结果 | 是 |
| `eval/access-log.csv` | 封存测试集访问记录 | 是 |

说明文档在 [`docs/05-research/`](../docs/05-research/)：

- [文献与资料库](../docs/05-research/reference-library.md)：每条文献的出处、级别、选择依据和用途
- [固定对照与阶段门禁](../docs/05-research/sota-baselines-and-gates.md)：方法选型、公开锚点、冻结基线、各阶段硬性指标
- [偏离日志](../docs/05-research/deviation-log.md)

下载论文（在仓库根目录）：

```bash
python research/papers/fetch_papers.py
```

只核对本地文件是否与入库的校验和一致：

```bash
python research/papers/fetch_papers.py --verify
```

研究环境（Python 3.12，在仓库根目录）：

```bash
uv venv research/.venv --python 3.12
```

```bash
uv pip install --python research/.venv/Scripts/python.exe numpy scipy scikit-learn pytest pyyaml pydantic pytrec-eval-terrier
```

运行指标一致性测试：

```bash
research/.venv/Scripts/python.exe -m pytest research/eval/tests -q
```
