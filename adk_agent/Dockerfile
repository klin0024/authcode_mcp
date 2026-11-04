FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先只裝相依,改 agent 程式碼時不用重裝
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 每個子資料夾是一個 agent;各自的 .env 不會被打包進 image(見 .dockerignore)
COPY gmail_agent ./agents/gmail_agent
COPY gmail_skills_agent ./agents/gmail_skills_agent

# 暫不使用:部署到多個網址時,取消下面兩行和最後的 ENTRYPOINT 註解,
# 就能用 A2A_BASE_URL 改寫 agent.json 的 url(見 docker-entrypoint.sh)。
# COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# # Windows 上編輯過的話可能是 CRLF,sh 會讀不懂
# RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

# 不用 root 跑;agents/ 交給 app,ADK 才能在各 agent 底下寫 .adk/session.db
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

# 只有互動式 terminal 才會問要不要開 telemetry,這裡明確關掉,docker run -it 時也不會卡住
RUN adk telemetry disable

# 預設 3000,跟 gmail_skills_agent/agent.json 的 url 一致;Cloud Run 會注入自己的 PORT 蓋掉
ENV PORT=3000
EXPOSE 3000

# 模型認證用環境變數帶入(--env-file),二選一:
#   - Google AI Studio:GOOGLE_API_KEY=...
#   - Vertex AI:GOOGLE_GENAI_USE_VERTEXAI=TRUE、GOOGLE_CLOUD_PROJECT=...,加上 ADC / service account
# adk web 會開網頁介面;正式環境只要 API 的話改成 adk api_server。
# --a2a:有 agent.json 的 agent 會多一個 A2A endpoint /a2a/<資料夾名稱>(JSON-RPC),
# card 在 /a2a/<資料夾名稱>/.well-known/agent-card.json。
# agent.json 的 url 目前寫死;要改用 A2A_BASE_URL 時取消下一行註解(連同上方 COPY/RUN)。
# ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec adk web --a2a --host 0.0.0.0 --port ${PORT} /app/agents"]
