"""数据湖基建（T-L1）。

四个基础件：
- blob：正文/附件的 zstd 内容寻址存储；
- manifest：产物清单与内容寻址 id；
- catalog：SQLite 元数据与血缘；
- verify：全量校验（blob、manifest、记录引用）。

设计见 docs/02-design/data-lake-design-2026-10-17.md（v0.2）。
"""

__version__ = "0.1.0"
