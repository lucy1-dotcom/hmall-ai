"""hmall-ai 服务入口。

用法：
    # 开发（改代码自动重启）
    uvicorn main:app --reload --port 8087

    # 或者直接跑
    python main.py

    # 生产
    uvicorn main:app --host 0.0.0.0 --port 8087 --workers 2
"""

from app.application import create_app

# uvicorn 通过 "main:app" 找到这个对象
app = create_app()


if __name__ == "__main__":
    import uvicorn

    from app.core.config import settings

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
