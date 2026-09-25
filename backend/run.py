"""uvicorn 启动入口：python -m backend.run

默认仅监听 127.0.0.1（本地回环），避免密钥接口直接暴露在局域网。
如需对外提供，请通过环境变量 HOST 或命令行 --host 显式指定（如 0.0.0.0）并配合认证/CORS 限制。

- 端口：命令行 --port > 环境变量 PORT > 默认 8000
- 热重载：RELOAD=1 开启（仅开发用；默认关闭，避免 reload 父进程持有端口导致
  进程结束后端口仍被占用、以及代码改动被旧进程继续服务的问题）
"""
import logging
import argparse
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx 的 INFO 日志会打印含 key/ak 的完整查询 URL；生产日志仅保留警告。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="启动 trip-planner-agent 后端服务")
    parser.add_argument("--host", default=None, help="监听地址，默认 127.0.0.1（可用 HOST 环境变量覆盖）")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认 8000（可用 PORT 环境变量覆盖）")
    args = parser.parse_args()

    host = args.host or os.getenv("HOST", "127.0.0.1")
    port = args.port or int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "").strip().lower() in ("1", "true", "yes")
    uvicorn.run("backend.api.main:app", host=host, port=port, reload=reload)
