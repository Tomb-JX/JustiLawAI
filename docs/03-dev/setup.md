# 环境搭建指南

> 版本 v0.1 · 2026-10-14 · 工程初始化后（M1）补充具体命令与排错条目

## 1. 基础环境

| 软件 | 版本要求 | 说明 |
|---|---|---|
| Node.js | ≥ 20 LTS | 建议用 nvm-windows / fnm 管理版本 |
| pnpm | ≥ 9 | `corepack enable` 或 `npm i -g pnpm` |
| Git | ≥ 2.40 | 配置 `user.name` / `user.email`；Windows 建议 Git Bash |
| VS Code | 最新 | 推荐插件见下 |

**VS Code 推荐插件**：ESLint、Prettier、Tailwind CSS IntelliSense、i18n Ally、Error Lens、GitLens。

## 2. 获取代码

```bash
git clone https://github.com/Tomb-JX/JustiLawAI.git
cd JustiLawAI/justilaw-web
pnpm install
pnpm dev        # 开发服务器，默认 http://localhost:5173
```

## 3. 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `VITE_API_BASE_URL` | 后端接口地址 | `/api/v1`（开发模式经 vite proxy 转发到 `localhost:8000`） |
| `VITE_USE_MOCK` | 是否启用内置 Mock 层 | `true`（后端未交付前） |
| `VITE_LOGTO_ENDPOINT` | Logto 租户地址 | `https://oglnok.logto.app/` |
| `VITE_LOGTO_APP_ID` | Logto SPA 应用 ID（公开信息） | 已写入 `.env.development` |
| `VITE_LOGTO_RESOURCE` | 后端 API Resource 标识；配置后请求才携带 JWT | 空 |

- 本地覆盖写在 `.env.development.local`（**不入库**）
- Mock 方案：`src/mocks/` 内置模拟层（含 SSE 流式模拟），与真实 API 在 `src/api/` 层按开关切换，组件代码无感知；后端每组接口交付后设 `VITE_USE_MOCK=false` 即切换联调

### 3.1 Logto 登录配置

登录由 Logto 托管（Mock 模式下同样需要真实登录）。在 [Logto Console](https://cloud.logto.io/) › Applications › JustiLaw 应用中登记：

| 配置项 | 值（本地开发） |
|---|---|
| Redirect URIs | `http://localhost:5173/callback` |
| Post sign-out redirect URIs | `http://localhost:5173/` |
| CORS allowed origins | 可不填（Redirect URI 所在源默认放行） |

- 部署到新域名时需追加对应 URI，否则 Logto 报 `redirect_uri` 不匹配
- 前端对接后端时：Console › API resources 创建资源（如 `https://api.justilaw.ai`），把标识填入 `VITE_LOGTO_RESOURCE`
- 管理员：Console › Roles 创建名为 `admin` 的角色并分配给用户

## 4. 常用脚本（M1 定义）

```bash
pnpm dev        # 开发
pnpm build      # 生产构建
pnpm lint       # ESLint 检查
pnpm test       # Vitest 单测
```

## 5. 常见问题（持续补充）

- **pnpm install 慢**：`pnpm config set registry https://registry.npmmirror.com`
- **Node 版本不符**：`node -v` 检查，nvm 切换到 20+
- **Windows 换行符警告**：`git config --global core.autocrlf true`

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-14 | v0.1 | 初稿（占位，M1 补充） | 前端组 |
| 2026-10-14 | v0.2 | 新增 Logto 环境变量与 Console 配置说明 | 前端组 |
