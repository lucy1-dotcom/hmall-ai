# hmall-ai 的镜像构建
# 构建：docker build -t hmall-ai:1.0.0 .
# 运行：docker run -d --name hmall-ai -p 8087:8087 --env-file .env hmall-ai:1.0.0

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，利用镜像层缓存：只改代码时不用重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8087

# 生产模式：不开 --reload，多 worker 由外部参数决定
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8087"]
