FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cortex_mem/ cortex_mem/
COPY service/ service/
COPY cortex/ cortex/
COPY schemas/ schemas/
COPY run.py .

EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import httpx; httpx.get('http://localhost:9100/health').raise_for_status()" || exit 1

CMD ["python", "-m", "cortex_mem.cli", "start", "--host", "0.0.0.0"]
