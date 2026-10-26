# 共享事件登记（2026-10-18）

> 解决的问题：协调看板靠协调线手抄，工作树又看不到别的分支；引擎/后处理读到的是 84KB 的 `collab-log`，信息必然落后。
> 方案：**append-only 事件日志 + 零依赖 CLI + 自动渲染**。各线自己登记，CURRENT 自动生成；协调只维护 schema 和里程碑快照。

## 1. 权威层级

| 层级 | 位置 | 用途 |
|---|---|---|
| 实时状态源 | `$DATA/coordination/events.jsonl` | 唯一实时事件流；只追加 |
| 自动视图 | `$DATA/coordination/CURRENT.md`、`BOARD.generated.md` | 每次 append 自动重渲染 |
| 共享镜像 | `$DATA/handoff/2026-10-18/CURRENT.md` | 各工作树直接读，不依赖 git 分支 |
| 提交快照 | 协调分支 `docs/04-plan/BOARD.md` | 里程碑时从 `BOARD.generated.md` 提交 |
| 历史 | `collab-log.md`、续跑单、`workstreams.md` | 只作历史/归属参考，不作为当前状态 |

**规则：实时状态只看 CURRENT；BOARD 落后几分钟是允许的，但不再手工补状态。**

## 2. 事件 schema

```json
{
  "schema": 1,
  "id": "evt-20261018120301-9b631e",
  "ts": "2026-10-18T12:03:01+08:00",
  "line": "engine|postprocessing|coordination|data|user",
  "type": "commit|artifact|handoff|ack|blocker|resolved|metric|note|loop",
  "summary": "<=300 字符，不换行，不含正文/个人信息",
  "status": "done|wip|blocked|open|current|stale|planned|closed|null",
  "refs": {"commit": "...", "branch": "...", "path": "...", "hash": "...", "name": "...", "value": "...", "handoff_id": "...", "blocker_id": "..."},
  "tags": ["gate-a2", "binding"]
}
```

`refs` 只放可核对引用；细节放产物路径，不把长文塞进事件。

## 3. CLI

运行时副本：`$DATA/coordination/coord_event.py`（各线直接执行）。
仓库快照：`docs/04-plan/tools/coord_event.py`（只作版本留存，不作为第二实现）。

```bash
# 提交：自动带当前工作树 commit/branch/dirty
python $DATA/coordination/coord_event.py commit --line engine --summary "..." --tag binding

# 产物 / 交接 / ack / 阻塞 / 指标 / 循环
python .../coord_event.py artifact --line postprocessing --summary "..." --path ... --hash ...
python .../coord_event.py handoff  --line coordination --summary "..." --to postprocessing --accept "..." --deadline ...
python .../coord_event.py ack      --line postprocessing --handoff-id ho-... --summary "..."
python .../coord_event.py blocker  --line engine --id BIND-01 --summary "..." --owner postprocessing --next "..."
python .../coord_event.py resolve  --line postprocessing --blocker-id BIND-01 --summary "..."
python .../coord_event.py metric   --line postprocessing --name binding_unresolved --value 1647 --summary "..."
python .../coord_event.py loop     --line coordination --summary "..." --owner postprocessing --next "..."

# 查看
python .../coord_event.py tail --limit 20
python .../coord_event.py render
```

## 4. 各线职责

| 角色 | 做什么 | 不做什么 |
|---|---|---|
| 引擎 | 自己登记 commit/artifact/blocker/metric；交付时写 handoff | 不改 events 旧行；不替后处理登记 |
| 后处理 | 自己登记 commit/artifact/ack/blocker/metric；消费 handoff | 不手改 CURRENT |
| 协调 | 维护 CLI/schema；里程碑把 `BOARD.generated.md` 提交为 BOARD；处理冲突 | 不再逐条手抄各线状态 |
| 用户 | 只看 CURRENT；按 refs 打开产物 | 不需要在会话间转述状态 |

## 5. 并发、隐私、回滚

- **并发**：append 使用文件锁（Windows `msvcrt` / POSIX `flock`）；一条事件一行 JSONL；渲染读全量后原子覆盖。
- **隐私**：不写原始正文、人名、证件、电话、登录态；只写 ID、路径、哈希、结论。
- **回滚**：事件只追加，不删除；错误用新的 `note`/`resolve` 更正，保留审计轨迹。
- **备份**：`events.jsonl` 在 `$DATA` 外置目录；协调在里程碑把当前视图提交到 git。

## 6. 当前种子（2026-10-18 12:03）

- 引擎 `971fdc3`：Gate B 绑定规则（shared_fact/target_specific/needs_review，231 passed，已推送）。
- 后处理 `4b7680d`：Gate A2 主路径改用 E-05 归一化。
- A2 212 诊断：normalizer resolved 1704；binding unresolved 1647；approx 失败 97→11；e05 parse failed 5。
- 后处理绑定适配 WIP：`element_contract` 增加 `binding_rules/classify_bindings`（未提交）。
- 未关闭：BIND-01、CONTRACT-01。

## 7. 迁移步骤

1. 各线开始用 `coord_event.py` 登记，不再往 `collab-log` 追加状态。
2. 协调在循环结束/里程碑执行 `render`，把 `BOARD.generated.md` 提交为 `BOARD.md`。
3. 旧文档只保留历史；新会话先读 `$DATA/handoff/2026-10-18/CURRENT.md`。
