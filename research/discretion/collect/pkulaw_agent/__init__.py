"""法宝作业台（pkulaw_agent）：agent 友好的检索 / 下载 / 核对一体化工具。

设计文档：docs/04-plan/pkulaw-agent-design.md
- M0：可见浏览器会话 + 手动登录（session.py / `doctor` / `login`）
- M1：登录后侦察捕获 + 任意直调（recon.py / `recon` / `call` / `cluster`）
- M2+：search / probe / fetch / download / report（待 recon 固化字段映射后实现）

红线（见设计 §3）：只用官方检索/浏览/导出功能；不绕验证码与风控；单账号人类节奏；
凭据与 profile 不进仓库；正文只落 $JUSTILAW_DATA_DIR。
"""

__version__ = "0.1.0"
