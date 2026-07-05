# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

ARG PORT=8000
ENV PORT=$PORT

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

RUN chmod +x start.sh && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request,os; p=os.environ.get('PORT','8000'); urllib.request.urlopen('http://localhost:'+p+'/health')" 2>/dev/null || exit 1

CMD ./start.sh
