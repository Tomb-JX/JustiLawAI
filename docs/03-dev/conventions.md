# 开发规范

> 版本 v0.2 · 2026-10-15 · 全员遵守

## 1. Git 规范

### 分支模型
```
main          # 主干，始终保持可运行
feature/*     # 功能分支：feature/chat-streaming
fix/*         # 修复分支：fix/sse-reconnect（小修复可直接提交 main）
docs/*        # 文档分支：docs/api-contract（小改动可直接提交 main）
```

### 什么时候直接提交 main，什么时候走 PR

| 直接 push 到 main | 开分支走 PR |
|---|---|
| 文档修改、错别字、注释 | 新功能、新页面、新接口 |
| 范围明确的小 bug 修复 | 改动 API 契约 / 数据结构 / 鉴权 |
| 配置、依赖版本、脚本的小调整 | 跨前后端或多个模块的改动 |
| | 需要队友知情或评审的改动 |

- 直接提交前必须本地通过：前端 `pnpm build`（含类型检查），改了后端至少确认 `python -c "import app.main"` 能导入
- 提交前 `git pull --rebase origin main`，避免无意义 merge 节点
- 走 PR 时自查第 5 节清单后即可自行合并；涉及他人负责模块时请对方复核
- 合并后删除功能分支（建议在 GitHub 仓库 Settings › General 勾选 Automatically delete head branches）

### 发布

单机版发布：在 main 上打 `v*` 标签并推送，CI 自动打包并创建 GitHub Release（见 `docs/03-dev/setup.md` §5.2）。

### Commit 信息（Conventional Commits）
```
<type>(<scope>): <简述>

type 取值：
  feat     新功能
  fix      修复
  docs     文档
  style    格式（不影响逻辑）
  refactor 重构
  test     测试
  chore    构建/工具/依赖

示例：
  feat(chat): 会话列表支持置顶与搜索
  fix(sse): 断线后停止生成按钮未复位
  docs(contract): 修订 hit-testing 响应结构
```

### 大文件纪律
仓库**严禁**提交：数据集（`*.zip`、CAIL 解压目录）、`node_modules`、构建产物、密钥/`.env.local`。详见根目录 `.gitignore`（M1 建立）。

## 2. 代码规范（前端）

- **TypeScript strict 模式**；`any` 需注释说明原因
- **命名**：组件/类型 `PascalCase`；函数/变量 `camelCase`；文件名组件 `PascalCase.tsx`、其余 `kebab-case.ts`；hooks `useXxx`
- **目录**：业务代码放 `features/<模块>/`，就近组织（components/hooks/store 同目录）；跨模块复用才上移到 `components/`、`hooks/`
- **样式**：一律 Tailwind 类名；主题色只用 CSS 变量 token（`bg-primary` 等），禁止硬编码色值
- **接口调用**：只经 `src/api/` 层，组件不得直接 `fetch`；错误统一由拦截器归一化 + toast
- **状态**：服务端数据一律 TanStack Query，不手工同步进 Zustand
- **注释**：只写"为什么"，不写"做了什么"；公开函数写 TSDoc

## 3. 接口联调规范

1. 后端交付接口 = 代码 + 在 `api-contract.md` 中的最终定义 + 联调环境地址
2. 前端发现契约偏差：先改文档 → 群内 @ 后端确认 → 再改代码
3. 联调顺序（与里程碑对齐）：auth → chat(SSE) → datasets → agents → workflows
4. 联调环境变量：`.env.development.local` 配置 `VITE_API_BASE_URL`（不入库）

## 4. 文档规范

见 [文档中心 README](../README.md) §文档管理规范。要点：先改文档再写码（契约/架构）；文档改动 commit 用 `docs:` 前缀；每个文档维护变更日志。

## 5. 代码评审清单（提交 / PR 自查）

- [ ] 符合命名/目录/样式规范，无硬编码色值与 magic number
- [ ] 无被注释掉的死代码、无 console.log 遗留
- [ ] 接口调用走 api 层，错误有兜底
- [ ] 新增依赖有必要性说明
- [ ] 涉及契约/架构变更的，文档已同步更新

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-14 | v0.1 | 初稿：main 只接受 PR 合入 | 前端组 |
| 2026-10-15 | v0.2 | 提交规则改为「小改动直接提交 main，大功能走 PR」；PR 自查后可自行合并；新增发布规则 | 模型组 |
