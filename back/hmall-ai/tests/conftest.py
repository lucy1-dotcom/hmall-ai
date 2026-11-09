"""测试环境初始化。

必须在任何 test 模块导入 app 之前设置环境变量：
- 记忆用内存模式，避免测试往仓库里写 SQLite 文件
- 关掉 Nacos 注册，避免测试去连真实的注册中心
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MEMORY_BACKEND", "memory")
os.environ.setdefault("NACOS_ENABLED", "false")
os.environ.setdefault("LLM_API_KEY", "")
