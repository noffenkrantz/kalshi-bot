# The optional always-on rain watcher (bot/watcher.py, run by bot/server.py). Render builds and runs
# this from render.yaml. (`python -m bot serve` would also do research every 4 hours; the default is
# research only when you press Run, on GitHub.) The scheduled research bot doesn't use it; that runs on GitHub Actions.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY config.toml .
ENV PYTHONUNBUFFERED=1
# Needs GITHUB_TOKEN (fine-grained, Contents read/write on this repo).
CMD ["python", "-m", "bot", "watch"]
