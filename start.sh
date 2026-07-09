#!/bin/sh
# Render 프리 플랜은 web/worker 서비스를 분리하면 디스크를 공유 못 해
# 파일 기반 JobStore(app/jobs.py)가 깨진다 — 한 컨테이너에서 같이 띄운다.
celery -A app.tasks:celery_app worker --loglevel=info --concurrency=2 &
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
