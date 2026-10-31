FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2
WORKDIR /service
COPY moderation/requirements.txt ./requirements.txt
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock -r requirements.txt \
    && groupadd --gid 10002 scanner \
    && useradd --uid 10002 --gid scanner --no-create-home scanner
COPY moderation ./moderation
RUN python -c "from moderation.server import loadDetector; loadDetector()"
USER 10002:10002
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/ready', timeout=3)"
CMD ["uvicorn", "moderation.server:createApp", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--limit-concurrency", "4", "--no-proxy-headers", "--no-access-log"]
