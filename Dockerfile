FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV WEBUI_HOST=0.0.0.0
ENV WEBUI_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:$WEBUI_PORT/api/config')" \
  || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8080"]
