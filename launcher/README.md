# JustiLawAI 单机版

**下载**：<https://github.com/Tomb-JX/JustiLawAI/releases/latest>（`JustiLawAI-local-<版本>.zip`，可用同名 `.sha256` 校验）

在自己电脑上运行完整的 JustiLawAI：网页、知识库、智能体、工作流都在本机，模型由本机的 Ollama 提供。**免登录**，数据只保存在本机。

## 三步开始

1. **安装 Ollama**：从 <https://ollama.com/download> 下载安装并打开（免费）。
2. **启动 JustiLawAI**：
   - Windows：双击 `Start-JustiLaw.bat`
   - macOS / Linux：在终端运行 `bash launcher/start.sh`（macOS 也可以右键 `start.command` → 打开）
3. **浏览器会自动打开** <http://127.0.0.1:8000>。首次使用时页面会出现「模型连接向导」，点「下载」获取推荐模型（对话模型约 6.6 GB，嵌入模型约 1.2 GB），完成后即可对话。

首次启动会自动准备 Python 环境并安装依赖，需要 1-3 分钟，之后再启动只需几秒。关闭启动窗口即停止服务。

## 常见问题

| 现象 | 处理 |
|---|---|
| 提示没有 Python | 按提示输入 `Y`，脚本会自动安装 [uv](https://docs.astral.sh/uv/) 并准备独立的 Python，不影响系统里已有的 Python；也可以自己装 Python 3.10+（安装时勾选 Add to PATH） |
| 依赖安装失败 | 脚本会自动换国内镜像重试；仍失败请检查网络或代理 |
| 网页里检测不到 Ollama | 确认 Ollama 已打开（Windows 托盘 / macOS 菜单栏有图标）后点「重新检测」；Ollama 不在默认地址时，在向导输入框里填写地址 |
| 端口 8000 被占用 | 脚本会自动改用下一个空闲端口，以窗口里显示的地址为准；也可以指定端口：`powershell -ExecutionPolicy Bypass -File launcher\start.ps1 -Port 9000` |
| 换电脑或重装 | 运行数据都在 `justilaw-api/store`，复制这个目录即可迁移 |

## 用 Docker 运行（可选）

已安装 Docker 时，在项目根目录执行：

```bash
docker compose up -d
```

然后打开 <http://127.0.0.1:8000>。容器通过 `host.docker.internal` 访问宿主机上的 Ollama。Linux 上需要让 Ollama 监听所有网卡（设置环境变量 `OLLAMA_HOST=0.0.0.0` 后重启 Ollama），否则容器连不上。

## 安全提示

单机模式没有登录，任何能访问这个地址的人都拥有管理员权限。启动脚本和 Docker 配置都只监听 `127.0.0.1`，请不要改成对局域网或公网开放。需要多人使用时请部署公网版并配置 Logto 登录（见 `docs/03-dev/setup.md`）。
