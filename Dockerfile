# Amend on Render (free plan: 512 MB). No video or audio processing on the server.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
# test-only and browser-test packages stay out of the image
RUN grep -v -E '^(pytest|pytest-asyncio|respx|playwright)' requirements.txt > runtime.txt \
    && pip install -r runtime.txt

# Named folders only, so .env, local databases and screenshots never end up in the image
COPY amend ./amend
COPY scripts ./scripts
COPY web ./web

EXPOSE 8000
CMD ["sh", "-c", "uvicorn amend.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
