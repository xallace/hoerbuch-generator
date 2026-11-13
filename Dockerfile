FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOERBUCH_HOST=0.0.0.0 \
    HOERBUCH_PORT=7865

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 hoerbuch
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=hoerbuch:hoerbuch hoerbuch.py web.py config.json LICENSE ./
COPY --chown=hoerbuch:hoerbuch hb ./hb
COPY --chown=hoerbuch:hoerbuch tests ./tests

RUN mkdir -p /app/out /app/published && chown -R hoerbuch:hoerbuch /app/out /app/published

USER hoerbuch
EXPOSE 7865

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7865/api/health', timeout=3)" || exit 1

CMD ["python", "-I", "web.py", "--host", "0.0.0.0", "--port", "7865", "--no-browser"]
