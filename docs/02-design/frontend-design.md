# JustiLawAI 前端设计方案

> 版本 v1.5 · 2026-10-22 · 配套文档：[API 契约](./api-contract.md) · [产品需求](../01-product/requirements.md) · [里程碑计划](../04-plan/milestones.md)

## 1. 项目定位

面向法律场景的**大模型智能体工作平台**（Legal LLM Agent Platform）：
用户可以在平台上对话问答、创建/使用法律智能体、编排 AI 工作流、管理法律知识库。
后端由本项目后端提供核心模型 API，前端负责全部产品交互层。

**对标产品形态**：Dify（工作流/知识库编排）+ LobeChat（对话体验）+ Coze（智能体市场），并叠加法律领域定制（判决预测、类案检索、文书起草等）。

**设计目标**
- 覆盖常见 AI 应用的全部功能：对话、智能体、工作流、知识库（RAG）、提示词库、模型管理、用户体系、管理后台
- 法律特色：内置法律智能体与工作流模板，结合 CAIL2018 语料做判决预测/类案检索场景
- 现代观感：类 ChatGPT 的简洁界面，明暗双主题
- 与后端并行开发：接口先行（Mock），不阻塞进度

---

## 2. 总体架构

```
┌────────────────────────── 浏览器 SPA ──────────────────────────┐
│  页面层  对话 / 智能体 / 工作流画布 / 知识库 / 提示词 / 管理后台   │
│  业务层  features/*（组件 + hooks + store）                     │
│  数据层  TanStack Query(服务端状态) + Zustand(客户端状态)        │
│  通信层  REST(axios) + SSE(fetch-event-source 流式对话)         │
│  Mock层  MSW —— 按 API 契约先行为后端接口打桩                    │
└──────────────────────────────┬─────────────────────────────────┘
                               │  /api/v1  (JWT Bearer)
                    ┌──────────▼──────────┐
                    │   JustiLawAI 后端    │
                    │  模型 API / RAG 引擎 │
                    └─────────────────────┘
```

---

## 3. 技术选型

| 领域 | 选型 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript 5 + Vite | 生态最全、参考项目均为 React 系 |
| UI 组件 | **shadcn/ui**（Radix UI 无头组件） | 代码归项目所有、可深度定制，类 ChatGPT 观感 |
| 样式 | **Tailwind CSS** + CSS 变量主题 token | 明暗主题、设计一致性、开发效率 |
| 路由 | React Router v7 | 标准选择，支持嵌套布局与懒加载 |
| 服务端状态 | TanStack Query v5 | 列表缓存、失效重取、加载态管理 |
| 客户端状态 | Zustand | 轻量，适合对话流式缓冲与 UI 状态 |
| 流式通信 | @microsoft/fetch-event-source | 支持带请求头/POST 的 SSE（原生 EventSource 不支持） |
| 表单 | react-hook-form + zod | 智能体创建、节点配置等复杂表单校验 |
| 画布 | @xyflow/react (React Flow 12) | 工作流可视化编排的成熟方案（Dify 同款思路） |
| Markdown | react-markdown + remark-gfm + rehype-highlight (highlight.js) + rehype-katex | 表格/公式/代码高亮，默认转义 HTML 防 XSS |
| 表格 | TanStack Table | 文档列表、用户管理 |
| 图表 | Recharts | shadcn 官方配套，用量统计 |
| 命令面板 | cmdk | 全局搜索 Ctrl+K |
| 通知 | sonner | 轻量 toast |
| 虚拟列表 | @tanstack/react-virtual | 长会话消息列表性能 |
| 上传 | react-dropzone | 知识库/对话附件拖拽上传 |
| i18n | i18next + react-i18next | 中文优先，预留英文 |
| Mock | 内置 Mock 层（`src/mocks/`，`VITE_USE_MOCK` 开关） | 按 API 契约先行模拟（含 SSE），无需 service worker；后续如需网络级拦截可换 MSW |
| 工程规范 | ESLint + Prettier + husky + lint-staged；Vitest + Testing Library | 质量保障 |

环境要求：Node 20+，包管理 pnpm。

**设计规范（Design Tokens）**
- 主色「法典蓝」：深蓝系（primary ≈ #1E40AF），强调色金色（#D97706）用于引用标注与徽标点缀
- 圆角：卡片 rounded-xl；字体：Inter / system-ui 中文回退，代码 JetBrains Mono
- 明暗双主题：Tailwind `dark:` class 策略，主题色收敛在 CSS 变量中

---

## 4. 功能模块设计

### 4.1 对话中心（Chat）——核心模块
- **多会话管理**：新建/重命名/置顶/归档/删除、按时间分组、搜索历史会话
- **流式输出**：SSE 增量渲染 + 打字机效果；停止生成 / 重新生成 / 继续输出
- **消息渲染**：Markdown、表格、代码高亮（一键复制）、KaTeX 公式、思维链折叠展示（可选）
- **消息操作**：复制、编辑并重发、删除、点赞点踩（反馈数据）
- **模型与参数**：模型切换下拉（读后端 `/models`）、temperature / top_p / max_tokens 参数面板
- **上下文管理**：Token 用量统计、清空上下文、历史消息截断提示
- **增强能力开关**：知识库检索（RAG，显示引用标注 [1][2]，点开来源卡片）、联网搜索（预留）、文件/图片上传理解（多模态预留）
- **快捷指令**：输入框 `/` 唤起提示词模板；`⏎` 发送、`⇧⏎` 换行、`Ctrl+K` 全局搜索
- **语音**：语音输入（ASR）与朗读（TTS）预留接口

### 4.2 智能体（Agents）
- **智能体广场**：卡片瀑布流，分类（咨询/检索/文书/合同…）、搜索、使用量排序
- **创建向导**（左侧分步表单 + 右侧实时调试预览对话）：
  1. 基本信息（头像、名称、分类、简介）
  2. 人设与提示词（系统提示词、开场白、推荐问题）
  3. 能力配置（挂载工具、开关联网/检索）
  4. 知识库挂载（多选）
  5. 发布（私有 / 组织可见 / 公开到广场）
- **生命周期**：草稿 → 调试 → 发布 → 下架
- **使用**：从广场一键「开始对话」，进入绑定该智能体的会话

### 4.3 工作流编排（Workflow）
- **可视化画布**（React Flow）：节点拖拽、连线、框选、对齐吸附、缩放、小地图、撤销重做、快捷键
- **节点库**：
  - 开始（输入变量定义）
  - LLM（模型选择、提示词模板、变量引用 `{{node.var}}`）
  - 知识检索（数据集、top-k、相似度阈值）
  - 条件分支（IF/ELSE）
  - 变量聚合、模板转换（文本拼接）
  - HTTP 请求（调用外部 API，如 CAIL 判决预测模型）
  - 代码执行（沙箱，预留）
  - 结束 / 直接回复
- **节点配置面板**：右侧抽屉，动态表单（zod schema 驱动）
- **试运行**：单节点测试 + 全流程试运行；底部日志抽屉按节点展示状态与耗时
- **DSL**：画布序列化为 `{ nodes, edges }` JSON 存后端；工作流可发布为智能体

### 4.4 知识库（Knowledge Base / RAG）
- **知识库管理**：创建（名称、描述、分段设置：分段长度/重叠、检索设置：top-k/阈值）
- **文档管理**：拖拽上传（PDF / DOCX / TXT / MD）、解析状态轮询（排队/解析中/完成/失败）、分段预览与启用禁用
- **命中测试**：输入 query → 返回 top-k 片段与相似度分数，用于检索调优
- **引用对话**：对话中 RAG 命中以 [n] 标注，点击展开来源卡片（文档名、原文片段、分数）
- **法律语料预置**：CAIL2018 案例库、法律法规库（由后端导入，前端展示）

### 4.5 提示词库（Prompts）
- 提示词 CRUD、分类标签、收藏；对话输入框 `/` 快捷插入；智能体创建时可引用

### 4.6 模型管理（Models）
- 模型列表（后端提供）、默认参数、连通性测试；对话中的模型切换数据源

### 4.7 用户体系与管理后台
- 登录 / 注册：接入 **Logto**（OIDC + PKCE），由 Logto 托管登录页（账号密码、邮箱验证码、社交登录均在 Logto Console 配置）；路由守卫
- 个人中心：资料、我的智能体 / 知识库 / 会话历史
- 角色权限：普通用户 / 管理员
- 管理后台（admin）：用户管理、智能体审核、调用用量统计（图表）

### 4.8 系统基础
- 明暗主题切换；响应式布局（桌面优先，移动端适配对话页）
- 全局命令面板（Ctrl+K：搜会话/智能体/知识库/跳转）
- 全局 ErrorBoundary、错误码归一化提示、403/404 页面
- 国际化（zh-CN 优先）

---

## 5. 法律场景定制设计

### 内置智能体（结合 CAIL2018 数据集与法律业务）
| 智能体 | 功能 | 输出形式 |
|---|---|---|
| 法律咨询助手 | 多轮法律问答，检索法条与案例辅助回答 | Markdown + 引用标注 |
| 判决预测 | 输入案情事实 → 预测罪名/法条/刑期（对接 CAIL 微调模型） | **结构化卡片**：罪名+置信度、适用法条、刑期区间 |
| 类案检索 | 输入案情 → 语义检索相似案例 | **案例卡片列表**：案号、法院、案由、相似度 |
| 法条解释 | 定位条文、通俗解释、关联条文、典型案例 | Markdown + 关联跳转 |
| 合同审查 | 上传合同 → 风险条款识别 | **风险清单卡片**：条款位置、风险等级、修改建议 |
| 文书起草 | 分步收集要素 → 生成起诉状/答辩状/法律意见书 | 文书预览，支持导出 |

**结构化输出卡片机制**：消息增加 `content_type` 字段（`markdown` | `card`），`card_type` 决定渲染哪种专属卡片（预测卡/案例列表卡/风险清单卡）。这是本平台区别于通用 AI 应用的关键设计。

### 工作流模板（预置 3 套）
1. **案情分析流水线**：开始 → 要素抽取(LLM) → 法条检索 → 类案检索 → 综合分析(LLM) → 回复
2. **合同风险扫描**：上传 → 分块 → 逐块审查(LLM) → 风险聚合 → 报告输出
3. **判决预测**：事实输入 → 要素抽取 → CAIL 模型(HTTP 节点) → 法条核对(检索) → 结论汇总

---

## 6. 页面结构与路由

```
/login                                 登录引导页（跳转 Logto 登录 / 注册）
/callback                              Logto 登录回调（无需鉴权）
/  → AppLayout（左侧主导航 + 顶栏）
├── /chat                              对话中心（左会话列表 + 右对话窗）
│   └── /chat/:conversationId          ?agentId= 可带入智能体
├── /agents                            智能体广场
│   ├── /agents/create                 创建向导（表单 + 调试预览）
│   └── /agents/:agentId               详情 + 试用对话
├── /workflows                         我的工作流
│   └── /workflows/:id/edit            画布编辑器（全屏布局）
├── /datasets                          知识库列表
│   └── /datasets/:id                  文档与分段管理（Tab：文档 / 命中测试 / 设置）
├── /prompts                           提示词库
├── /models                            模型管理
├── /admin/*                           管理后台（admin 角色可见）
└── /settings                          个人设置
```

路由全部懒加载（React.lazy），鉴权路由统一守卫。

### 关键页面布局

**对话页（双栏）**
```
┌──────────┬──────────────────────────────────────────┐
│ Logo     │ 模型选择 ▾   参数 ⚙   知识库开关   ⌘K 搜索 │
├──────────┼──────────────────────────────────────────┤
│ + 新对话  │  ▸ 用户：故意伤害致人轻伤怎么量刑？        │
│ 🔍 搜索   │                                          │
│──────────│  ◂ 助手：根据《刑法》第234条……            │
│ 📌 置顶   │    └ 引用 [1]刑法§234 (0.91) [2](2018)…  │
│ 今天      │                                          │
│ 7 天内    │──────────────────────────────────────────│
│ 更早      │ [📎] 输入消息…（/ 唤起提示词） [🎙] [发送] │
└──────────┴──────────────────────────────────────────┘
```

**智能体创建（三栏）**
```
┌───────────┬──────────────────────────┬───────────────┐
│ 步骤导航   │ 表单区                    │ 调试预览       │
│ ①基本信息  │ 名称/头像/分类            │ ┌───────────┐ │
│ ②提示词    │ 系统提示词（大文本）       │ │ 对话实时测试│ │
│ ③能力配置  │ 开场白/推荐问题           │ │ 改动即生效 │ │
│ ④知识库    │ 工具开关/知识库挂载        │ └───────────┘ │
│ ⑤发布     │                          │               │
└───────────┴──────────────────────────┴───────────────┘
```

**工作流编辑器（全屏四区）**
```
┌────────┬───────────────────────────────┬──────────────┐
│ 节点库  │      React Flow 画布          │ 节点配置面板   │
│ □开始   │ (开始)→(要素抽取)→(法条检索)   │ 模型/温度     │
│ □LLM   │       →(LLM)→(回复)          │ 提示词模板    │
│ □检索   │  拖拽/连线/缩放/小地图/撤销    │ 变量引用      │
│ □分支   ├───────────────────────────────┴──────────────┤
│ □HTTP  │ ▶ 试运行  日志：[抽取 ✓ 320ms][检索 ✓ 2.1s]…  │
└────────┴──────────────────────────────────────────────┘
```

---

## 7. 前端工程结构

```
justilaw-web/
├── src/
│   ├── api/                     # 接口层，与后端契约一一对应
│   │   ├── client.ts            #   axios 实例（token 注入、错误归一化）
│   │   ├── sse.ts               #   fetch-event-source 封装（事件分发）
│   │   └── auth.ts chat.ts agents.ts workflows.ts datasets.ts models.ts
│   ├── mocks/                   # MSW mock（按契约先行实现）
│   ├── components/
│   │   ├── ui/                  # shadcn/ui 基础组件
│   │   ├── markdown/            # MarkdownRenderer / CodeBlock / CitationCard
│   │   ├── upload/              # FileDropzone
│   │   └── common/              # EmptyState / PageHeader / AvatarMenu …
│   ├── features/                # 业务模块（组件 + hooks + store 就近放置）
│   │   ├── auth/
│   │   ├── chat/                #   MessageList / ChatInput / ParamPanel / useChatStream
│   │   ├── agents/              #   广场 / 创建向导 / 详情
│   │   ├── workflows/           #   画布 / nodes/（各节点组件）/ 配置面板 / 运行日志
│   │   ├── datasets/
│   │   ├── prompts/
│   │   ├── models/
│   │   └── admin/
│   ├── hooks/                   # useTheme / useAuth / useHotkeys
│   ├── layouts/                 # AppLayout / AuthLayout / FlowLayout(画布全屏)
│   ├── router/                  # 路由表 + 守卫
│   ├── stores/                  # authStore / settingsStore / uiStore
│   ├── lib/                     # cn() 等工具
│   ├── styles/                  # globals.css（Tailwind + 主题 CSS 变量）
│   ├── types/                   # API 契约类型
│   ├── i18n/
│   ├── App.tsx / main.tsx
├── .env.development             # VITE_API_BASE_URL（Mock 模式）
├── vite.config.ts / tsconfig.json / package.json
```

**状态管理划分**
- 服务端状态（TanStack Query）：会话列表、消息历史、智能体/知识库/文档列表——缓存 + 失效重取
- 客户端状态（Zustand）：`authStore`（token/user）、`settingsStore`（主题/语言/默认参数）、`chatStore`（当前流式消息缓冲、生成中状态）、`uiStore`（侧栏/面板开合）

---

## 8. API 契约

前后端接口规范单独成文，见 **[API 契约](./api-contract.md)**（唯一对接依据，变更需先改文档再实现）。核心要点：
- REST + SSE 混合：列表/管理类走 REST，对话补全与工作流运行走 SSE 流式
- SSE 事件协议：`message`（文本增量）/ `citations`（引用）/ `tool_call` / `workflow`（节点进度）/ `card`（结构化卡片）/ `done` / `error`

---

## 9. 关键技术方案

1. **流式渲染**：fetch-event-source 发起 POST SSE；增量写入 Zustand 缓冲区，requestAnimationFrame 批量 flush 再触发渲染，避免逐 token re-render；`AbortController` 实现"停止生成"；断线自动提示并支持重试
2. **Markdown 安全**：react-markdown 管线默认转义 HTML + DOMPurify 兜底；外链强制 `rel="noopener noreferrer"`
3. **长会话性能**：消息列表虚拟化（@tanstack/react-virtual）；流式期间仅重渲染输出中的那条消息（memo 隔离）
4. **画布方案**：React Flow 自定义节点组件；DSL 即 `{ nodes, edges }` JSON；配置面板由 zod schema 驱动动态表单
5. **Mock 解耦**：MSW 按 API 契约打桩（SSE 用 ReadableStream 模拟增量），后端就绪后仅切换 `VITE_API_BASE_URL`
6. **鉴权**：`@logto/react` 管理登录态与 token 刷新（refresh token 存 localStorage，由 SDK 维护）；`RequireAuth` 路由守卫；api 层通过注入的 token getter 为 axios / SSE 请求附加 `Authorization`，遇 401 自动重新登录；按钮级权限（admin）读 ID Token 的 `roles` 声明，最终以后端为准

---

## 10. 开源参考清单

| 项目 | 借鉴点 |
|---|---|
| LobeChat | 对话 UI 交互细节、消息操作、插件生态设计 |
| Dify | 工作流节点编排与 DSL 设计、知识库产品形态、应用发布流程 |
| FastGPT | RAG 分段管理与命中测试交互 |
| Coze | 智能体市场卡片、创建向导体验 |
| Open WebUI | 模型参数面板 |
| React Flow 官方示例 | 画布交互（连线校验、自动布局） |

---

## 11. 实施路线

见 [里程碑计划](../04-plan/milestones.md)（M1-M6 / 12 周，含任务拆解与进度跟踪）。

并行分工建议：A 负责 Chat + Agents，B 负责 Datasets + Workflows，公共组件（Markdown 渲染、上传、布局）M1 期间由 A 先行产出。

---

## 12. 视觉语言与动效规范（v1.4 新增）

> 目标：在"类 ChatGPT 的简洁界面"基础上建立有辨识度的视觉语言。选型原则：**客户端渲染优先、零动画依赖、法律专业感优先于花哨**。
> 效果算力全部发生在用户浏览器，服务端仅增加一次性静态资源下载（约 +5KB CSS），与 Ollama 推理瓶颈无关。

### 12.1 效果清单与落点

| 效果 | 实现（globals.css 效果层） | 落点 |
|---|---|---|
| 文字流光 Shimmer | `.shimmer-text`（渐变背景扫光） | 消息"深度思考中…"生成态 |
| 骨架屏扫光 | `.skeleton-shimmer`（替代纯透明度脉冲） | `Skeleton` 组件、消息列表加载 |
| Aurora 极光背景 | `.aurora`（两个 blur 渐变 blob 缓慢漂移） | 登录页、聊天欢迎页 |
| 毛玻璃卡片 | `.glass`（backdrop-filter，全站 ≤ 2 层） | 登录卡片、欢迎页模型向导卡 |
| 光标聚光灯卡片 | `.spotlight-card` + `SpotlightCard` 组件（CSS 变量跟随鼠标） | 智能体广场卡片、聊天欢迎页快捷入口 |
| 流光边框 | `.flow-border`（conic-gradient 旋转，@property 驱动） | 生成中的对话输入框、知识库解析中的文档卡片 |
| 列表入场 stagger | `.stagger-item` + 内联 `--stagger-delay` | 欢迎页推荐问题/快捷入口、智能体广场、Admin 统计卡 |
| 数字滚动 | `CountUp` 组件（rAF easeOutCubic，IntersectionObserver 触发） | Admin 统计页 Bento 卡 |
| Bento Grid | 纯 CSS grid 跨行跨列 | 聊天欢迎页快捷入口（首卡 2 列跨行）、Admin 统计页 |
| 路由转场 | React Router `viewTransition` + `::view-transition-*` **仅作用于内容区**（`app-content` 命名组；root 动画关闭，侧栏原地不动） | 侧边导航、会话切换、卡片跳转（渐进增强，不支持的浏览器自动忽略） |
| 连线流动 | React Flow `animated` 边 | 工作流试运行时（"数据在流"的可视暗示） |
| 打字光标 | `.stream-caret`（已有，保留） | 流式消息输出 |

效果原语组件集中于 `src/components/common/effects.tsx`（SpotlightCard / CountUp）；其余全部为 CSS 类，不引入任何动画依赖。

### 12.2 性能护栏（硬性约定）

1. **动画属性白名单**：只允许 `transform / opacity / background-position`（合成器属性），禁止 width/height/top/left 动画；
2. **毛玻璃限量**：`backdrop-filter` 元素全站不超过 2 个固定层（当前：登录卡、欢迎页向导卡，均叠在 aurora 彩色底层上）；禁止列表卡片逐个 blur；
3. **依赖预算**：效果类不新增 npm 依赖；首屏 JS 增量 > 50KB gz 的方案必须评审；
4. **降级**：全局响应 `prefers-reduced-motion`——所有动画关闭、shimmer 退化为纯色文字（见 globals.css 末尾媒体查询）；
5. **浏览器兼容**：`@property`（flow-border）与 View Transitions 均为渐进增强，不支持的浏览器得到静态边框/瞬时切换，无功能损失；
6. **布局稳定性（防整页跳动）**：AppLayout 外壳（侧栏/顶栏）永远先渲染，`RequireAuth` 只门控内容区（包住 `<Outlet/>` 的 `[data-vt-content]`）——刷新或恢复登录态时，加载态/跳转只出现在内容区局部，外壳不卸载；View Transition 同理只命名内容区（`view-transition-name: app-content`），root 不挂动画。

### 12.3 服务器体量评估结论（选型依据）

- 公网链路为单台 VPS + nginx（限流 10r/s，无 CDN）：效果全部为客户端渲染，服务端零新增计算；
- 本次新增静态资源约 +5KB CSS + ~1KB JS（effects.tsx），已同步在 `ops/nginx-justilaw.conf` 开启 gzip（text/css、js、json、svg 等）；
- 真正的容量瓶颈是宿主机 Ollama 推理（9B 模型）与 RAG 嵌入，与本层无关；
- 明确不做（体积/算力/调性三杀）：Three.js 3D 场景、视频背景、全屏粒子引擎、中文 web 字体（MB 级）、neon 全屏发光。

### 12.4 后续可选增强（第二档，需评审）

Motion（Framer Motion）微交互、canvas-confetti 文书导出庆祝、Lottie 天平动画（登录页点睛）。引入前按护栏 3 评估包体。

---

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-14 | v1.0 | 初稿 | 前端组 |
| 2026-10-14 | v1.1 | M1 提前交付：Mock 改为内置模拟层（VITE_USE_MOCK）；代码高亮定为 rehype-highlight；登录/多用户按决策暂缓 | 前端组 |
| 2026-10-14 | v1.2 | M1-M6 前端全量交付：新增编辑重发/附件/思维链、知识库 CRUD 与分段管理、智能体创建向导与发布流、React Flow 工作流画布（模拟试运行）、管理后台、Ctrl+K 命令面板 | 前端组 |
| 2026-10-14 | v1.3 | 多用户登录接入 Logto（OIDC），替代自建账号密码 + JWT 方案；新增 /callback 路由 | 前端组 |
| 2026-10-16 | v1.4 | 新增 §12 视觉语言与动效规范并全量落地：Shimmer 思考态/骨架扫光、登录页与欢迎页 Aurora + 毛玻璃、聚光灯卡片、流光边框（生成中输入框/解析中文档）、Bento 快捷入口与 Admin 统计卡、CountUp 数字滚动、View Transitions 路由转场、工作流运行时连线流动；配套 ops nginx 开启 gzip；全部零动画依赖、prefers-reduced-motion 全局降级 | 前端组 |
| 2026-10-22 | v1.5 | 修复整页跳动：AppLayout 外壳即时渲染，RequireAuth 鉴权门控从整树下移到内容区（刷新时侧栏/顶栏不再卸载重挂）；View Transition 作用域从 root 收窄为 `app-content` 命名组（路由切换仅内容区过渡）；§12 效果表与性能护栏第 6 条同步更新 | 前端组 |
