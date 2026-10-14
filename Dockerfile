# JustiLawAI 单机镜像：前端静态文件由后端直接托管，一个端口提供网页与 API。
# Ollama 不打包进镜像，运行在宿主机上（GPU 驱动由宿主机提供），容器经 host.docker.internal 访问。
# 用法见 docker-compose.yml：docker compose up -d → http://127.0.0.1:8000

FROM node:22-slim AS web
WORKDIR /web
RUN npm i -g pnpm@12.11.2
COPY justilaw-web/package.json justilaw-web/pnpm-lock.yaml justilaw-web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY justilaw-web/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app/justilaw-api
COPY justilaw-api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY justilaw-api/ ./
COPY --from=web /web/dist /app/justilaw-web/dist
ENV PYTHONIOENCODING=utf-8 \
    WEB_DIST_DIR=/app/justilaw-web/dist \
    DATA_DIR=/data \
    OLLAMA_BASE_URL=http://host.docker.internal:11434
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
