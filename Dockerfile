FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先只複製安裝需要的檔案,改 src 以外的東西時不用重裝相依
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# 不用 root 跑
RUN useradd --create-home --uid 1000 app
USER app

# 設定全走環境變數:app 設定(GOOGLE_CLIENT_ID 等,無前綴)由 config.Settings 讀,FASTMCP_* 由 FastMCP 自己讀。
# 用 --env-file .env 帶入;.env 不會被打包進 image(見 .dockerignore),容器內沒有 .env 檔可讀。
# 容器內一定要綁 0.0.0.0,不然 host 連不進來;--env-file 會蓋掉這裡的值,.env 裡別把 FASTMCP_HOST 設成 127.0.0.1。
ENV FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000

EXPOSE 8000

CMD ["authcode-mcp"]
