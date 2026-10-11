# Crawl4AI Gateway Console (Streamlit). Build from the repository root:
#   docker build -f deploy/ui/Dockerfile -t crawl4ai-console:<ver> .
# deploy/ui/Dockerfile.dockerignore limits the context to the files below.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/console

RUN groupadd --system --gid 10001 console \
    && useradd --system --uid 10001 --gid console --home-dir /home/console \
       --create-home --shell /usr/sbin/nologin console \
    && mkdir -p /data && chown console:console /data

WORKDIR /opt/console
COPY deploy/ui/requirements.txt ./ui/requirements.txt
# The base image's pip 25.0.1 carries six advisories (PYSEC-2026-1795 ...
# -3721); 26.2 clears them. Upgrade before installing anything with it.
RUN pip install --upgrade "pip>=26.2" && pip install -r ui/requirements.txt

# The console reuses the n8n contract and E2E helpers verbatim.
COPY deploy/n8n/contract.py ./n8n/contract.py
COPY deploy/gateway/e2e.py ./gateway/e2e.py
COPY deploy/ui/console.py deploy/ui/app.py ./ui/
COPY deploy/ui/.streamlit ./ui/.streamlit

USER console
WORKDIR /opt/console/ui
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"
CMD ["streamlit", "run", "app.py"]
