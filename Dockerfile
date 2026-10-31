FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 imagehost \
    && useradd --uid 10001 --gid imagehost --no-create-home imagehost \
    && mkdir /data && chown imagehost:imagehost /data
COPY --chown=imagehost:imagehost app ./app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=3)"
CMD ["uvicorn", "app.main:createApp", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
