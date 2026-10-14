# 环境搭建指南

> 版本 v0.3 · 2026-10-14 · 前端 + 模型服务后端（justilaw-api）+ 部署

## 1. 基础环境

| 软件 | 版本要求 | 说明 |
|---|---|---|
| Node.js | ≥ 20 LTS | 建议用 nvm-windows / fnm 管理版本 |
| pnpm | ≥ 9 | `corepack enable` 或 `npm i -g pnpm`；pnpm ≥ 10 需允许 esbuild 构建脚本（已在 `justilaw-web/pnpm-workspace.yaml` 配置） |
| Python | ≥ 3.10 | 后端 justilaw-api |
| Ollama | 最新 | 本地模型推理；对话 `qwen3.5:9b`，嵌入 `bge-m3` |
| Git | ≥ 2.40 | 配置 `user.name` / `user.email`；Windows 建议 Git Bash |
| VS Code | 最新 | 推荐插件见下 |

**VS Code 推荐插件**：ESLint、Prettier、Tailwind CSS IntelliSense、i18n Ally、Error Lens、GitLens。

## 2. 获取代码与启动前端

```bash
git clone https://github.com/Tomb-JX/JustiLawAI.git
cd JustiLawAI/justilaw-web
pnpm install
pnpm dev        # 开发服务器，默认 http://localhost:5173
```

## 3. 前端环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `VITE_API_BASE_URL` | 后端接口地址 | `/api/v1`（开发模式经 vite proxy 转发到 `127.0.0.1:8000`） |
| `VITE_USE_MOCK` | 是否启用内置 Mock 层 | `.env.development` 与 `.env.production` 均为 `false`（走真实后端） |
| `VITE_LOGTO_ENDPOINT` | Logto 租户地址 | `https://oglnok.logto.app/` |
| `VITE_LOGTO_APP_ID` | Logto SPA 应用 ID（公开信息） | 已写入 `.env.development` / `.env.production` |
| `VITE_LOGTO_RESOURCE` | 后端 API Resource 标识。填了发 access token（resource 模式），留空发 ID Token（idtoken 模式），见 api-contract §1.3 | 空 |

- 本地覆盖写在 `.env.development.local`（**不入库**）
- Mock 方案：`src/mocks/` 内置模拟层（含 SSE 流式模拟），与真实 API 在 `src/api/` 层按开关切换，组件代码无感知。没有后端时设 `VITE_USE_MOCK=true` 即可单独开发前端

### 3.1 Logto 登录配置

登录由 Logto 托管（Mock 模式下同样需要真实登录）。在 [Logto Console](https://cloud.logto.io/) › Applications › JustiLaw 应用中登记：

| 配置项 | 值 |
|---|---|
| Redirect URIs（每个访问源都要登记） | `http://localhost:5173/callback`、`http://localhost:5174/callback`、部署域名 `http://law.huanghaiyang.com/callback` |
| Post sign-out redirect URIs | 同上各源的 `/` |
| CORS allowed origins | 可不填（Redirect URI 所在源默认放行） |

- 部署到新域名时需追加对应 URI，否则 Logto 报 `redirect_uri` 不匹配
- Logto 免费版无法创建 API Resource：前端 `VITE_LOGTO_RESOURCE` 留空，后端配 `LOGTO_APP_ID` 走 idtoken 模式
- 升级后改用 resource 模式：Console › API resources 创建资源（如 `https://api.justilaw.ai`），前端填 `VITE_LOGTO_RESOURCE`，后端填 `LOGTO_API_RESOURCE`，两边必须一致
- 管理员：后端 `ADMIN_SUBS` 填 Logto 用户 ID（sub），或在 Console › Roles 创建 `admin` 角色并分配给用户

## 4. 模型服务后端（justilaw-api）

### 4.1 安装与启动

```bash
cd JustiLawAI/justilaw-api
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS / Linux：.venv/bin/pip
cp .env.example .env                              # 按需修改，.env 不入库
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 启动后访问 `http://127.0.0.1:8000/api/v1/health` 查看默认模型和告警（如默认嵌入模型不存在）
- 运行数据（会话、知识库、向量、上传文件）保存在 `justilaw-api/store/`，**不入库**；可用 `DATA_DIR` 改位置。换机器或重装前先备份这个目录
- Windows 控制台中文乱码时，启动前设 `PYTHONIOENCODING=utf-8`

### 4.2 后端环境变量（`justilaw-api/.env`）

| 变量 | 说明 | 默认 |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama 地址（不要填 `0.0.0.0`，那是监听地址） | `http://127.0.0.1:11434` |
| `DEFAULT_CHAT_MODEL` / `DEFAULT_EMBED_MODEL` | 默认对话 / 嵌入模型（平台模型 ID）。前端「模型服务」页修改后存进 `store/settings.json`，优先于这里 | `ollama/qwen3.5:9b` / `ollama/bge-m3` |
| `LOGTO_ENDPOINT` | 填了才启用鉴权；留空为单用户本地模式（所有请求视为本地管理员） | 空 |
| `LOGTO_API_RESOURCE` | resource 模式的 API Resource 标识 | 空 |
| `LOGTO_APP_ID` | idtoken 模式校验的 `aud`（即前端 SPA 的 App ID） | 空 |
| `ADMIN_SUBS` | 管理员的 Logto 用户 ID，逗号分隔 | 空 |
| `CORS_ORIGINS` | 允许的前端源，逗号分隔 | `localhost` / `127.0.0.1` 的 5173、5174 |
| `API_HOST` / `API_PORT` | 监听地址 | `127.0.0.1` / `8000` |
| `DATA_DIR` | 运行数据目录 | `justilaw-api/store` |

### 4.3 准备模型

```bash
ollama pull qwen3.5:9b
ollama pull bge-m3
```

- Ollama 的模型启动时自动发现；之后新 pull 的模型在「模型服务」页点「同步模型」即可看到
- 其他模型（含云端嵌入模型）在「模型服务」页添加 OpenAI 兼容供应商，注册模型时勾选能力（对话 / 嵌入 / 视觉 / 工具 / 思维链）
- **代理环境**：系统设了 `HTTP(S)_PROXY` 时，`ollama pull` 可能报 `something went wrong`（请求被代理截走）。临时取消代理再拉，或直接调 API：`curl --noproxy '*' http://127.0.0.1:11434/api/pull -d '{"model":"bge-m3"}'`。后端访问回环地址时已自动绕过代理

### 4.4 导入语料

```bash
.venv/Scripts/python -m app.seed_corpus <文件或目录> <知识库 ID>
```

只导入**有出处的真实材料**（法条全文、裁判文书等）。检索结果会被当作类案和法条引用给用户，不要导入手写的示例文本。

## 5. 部署（公网）

| 组件 | 说明 |
|---|---|
| `ops/nginx-justilaw.conf` | 两个入口：公网 `law.huanghaiyang.com:80`，回环 `127.0.0.1:8101`（SSH 隧道访问）。静态文件在 `/opt/justilaw/web`，`/api/` 反代到 `127.0.0.1:8100`。SSE 依赖 `proxy_buffering off` 和 600s 读超时 |
| `ops/nginx-ratelimit.conf` | `/api/` 按 IP 限流 10 r/s（放在 nginx `http` 块） |
| `ops/justilaw-tunnel.ps1` | 把本机 Ollama 反向隧道到服务器 `172.17.0.1:11434`，服务器后端的 `OLLAMA_BASE_URL` 指向这个地址。`-Status` 查看、`-Stop` 关闭、`-Install` 登录 Windows 时自启；依赖本机的 astrbot-ops 脚本 |

- 前端用 `pnpm build` 生成（读取 `.env.production`，同源部署，API 走相对路径），把 `dist/` 上传到 `/opt/justilaw/web`
- 部署新版本后，已打开的旧页面加载懒加载文件失败时会自动刷新一次
- 后端在服务器上以 `API_PORT=8100` 启动，`.env` 里配好 Logto 鉴权

## 6. 常用脚本（justilaw-web）

```bash
pnpm dev        # 开发
pnpm build      # 类型检查 + 生产构建
pnpm typecheck  # 仅类型检查
pnpm preview    # 本地预览构建产物
```

## 7. 常见问题（持续补充）

- **pnpm install 慢**：`pnpm config set registry https://registry.npmmirror.com`
- **Node 版本不符**：`node -v` 检查，nvm 切换到 20+
- **Windows 换行符警告**：`git config --global core.autocrlf true`
- **登录后请求一直 401 / 保存没反应**：检查后端 `LOGTO_APP_ID`（或 `LOGTO_API_RESOURCE`）是否与前端一致，以及服务器能否访问 `https://oglnok.logto.app/oidc/jwks`
- **对话报模型不存在**：`/api/v1/health` 看告警，确认 Ollama 在运行且模型已 pull

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-14 | v0.1 | 初稿（占位，M1 补充） | 前端组 |
| 2026-10-14 | v0.2 | 新增 Logto 环境变量与 Console 配置说明 | 前端组 |
| 2026-10-14 | v0.3 | 新增后端安装、环境变量、模型准备、语料导入与公网部署说明；Logto 补充 idtoken 模式 | 模型组 |
