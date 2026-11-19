FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SALIM_DB_URL=sqlite:////data/salim.db

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "sqlalchemy>=2" jinja2 httpx mcp uvicorn python-multipart
COPY src ./src
ENV PYTHONPATH=/app/src

RUN useradd --create-home salim && mkdir /data && chown salim /data
USER salim
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "--factory", "salim.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
