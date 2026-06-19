# ============================================================
# Ombre Brain Docker Build
# Docker 构建文件
#
# Build:
#   docker build -t ombre-brain .
# 本地运行:
#   docker run \
#     -e OMBRE_DASHBOARD_PASSWORD=xxx \
#     -e OMBRE_EMBED_API_KEY=your-gemini-key \
#     -p 8000:8000 ombre-brain
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (leverage Docker cache)
# 先装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files / 复制项目文件
COPY src/ ./src/
COPY frontend/ ./frontend/
COPY VERSION ./VERSION
COPY config.example.yaml ./config.default.yaml
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Persistent mount point: bucket data
# 持久化挂载点：记忆数据
VOLUME ["/app/buckets"]

# Default to streamable-http for container (remote access)
# 容器场景默认用 streamable-http
ENV OMBRE_TRANSPORT=streamable-http
ENV OMBRE_BUCKETS_DIR=/app/buckets
# Embedding 使用 API 后端（Gemini）
# 必须通过运行时 -e 或 docker-compose environment 传入 OMBRE_EMBED_API_KEY
ENV OMBRE_EMBED_BACKEND=api

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
