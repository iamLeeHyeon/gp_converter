# Docker Compose 프로덕션 설정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `redis`+`web`(FastAPI)+`worker`(Celery) 3서비스를 `docker-compose.yml` 하나로 묶어 어떤 배포환경에서도 `docker compose up --build`로 돌아가게 하고, 프론트엔드 빌드를 Dockerfile 멀티스테이지로 자동화한다.

**Architecture:** `Dockerfile`에 `node:20-slim` 프론트 빌드 스테이지를 앞에 추가해 기존 `python:3.11-slim-bookworm`(+Audiveris) 스테이지로 산출물만 복사한다. `docker-compose.yml`은 `redis`/`web`/`worker` 3서비스와 `redis-data`/`jobs-data`/`db-data` 3개 named volume으로 구성한다. `web`과 `worker`는 동일 이미지, `command:`만 다르다.

**Tech Stack:** Docker multi-stage build, Docker Compose v2, Redis 7, SQLite(named volume 영속화).

## Global Constraints

- 이 작업은 pytest 대상이 아니다(순수 인프라 설정) — 각 태스크의 "검증"은 `docker build`/`docker compose config`/수동 실행으로 한다.
- 리버스프록시/TLS/Postgres 전환은 범위 밖(스펙의 YAGNI 항목) — 추가하지 않는다.
- `web`/`worker`는 반드시 동일 이미지를 써야 한다(worker도 Audiveris 서브프로세스를 실행하므로).
- 비밀값은 `.env`(이미 gitignore됨) + `env_file:`로 주입, `.env.example`에 전체 변수 템플릿화.
- 이 개발 머신은 Docker Desktop 데몬이 현재 꺼져있는 상태로 확인됨(`docker ps` → daemon 소켓 연결 실패). `docker compose config`는 데몬 없이도 동작(클라이언트 사이드 YAML 검증)하지만, 실제 `docker build`/`docker compose up`은 데몬이 떠 있어야 한다 — 데몬이 꺼져있으면 그 단계는 건너뛰고 사용자에게 수동 검증을 안내한다(스펙에 이미 "검증은 수동 스모크테스트"로 명시돼 있음).

---

### Task 1: Dockerfile 멀티스테이지 + .dockerignore 업데이트

**Files:**
- Modify: `Dockerfile`
- Modify: `.dockerignore`

**Interfaces:**
- Consumes: `frontend/package.json`(`"build": "tsc -b && vite build"`), `frontend/vite.config.ts`(`outDir: '../static'`, `emptyOutDir: true`) — 기존 파일, 변경 안 함.
- Produces: 최종 이미지의 `/srv/static/`에 프론트 빌드 산출물(`index.html`, `assets/*.js`, `assets/*.css` 등)이 존재. Task 2(`docker-compose.yml`)가 이 이미지를 `build:` 대상으로 사용.

- [ ] **Step 1: Dockerfile을 멀티스테이지로 교체**

`Dockerfile` 전체를 아래 내용으로 교체한다(기존 Audiveris 설치 로직은 그대로 유지하고 앞에 프론트 빌드 스테이지만 추가):

```dockerfile
# Audiveris의 Linux 릴리스가 x86_64 전용이라 이 이미지는 반드시 linux/amd64로 빌드해야 한다.
# docker build --platform linux/amd64 -t gp-converter .
FROM node:20-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim-bookworm

ARG AUDIVERIS_VERSION=5.10.2
ARG AUDIVERIS_DEB=Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb

# Audiveris(jpackage 앱, 자체 JRE 동봉)의 AWT/Swing 헤드리스 구동에 필요한 네이티브 라이브러리.
# (deb 패키지 control 파일의 Depends 목록과 일치)
# fontconfig+폰트: Java AWT가 심볼 폰트를 그릴 때 fontconfig를 통해 시스템 폰트를
# 찾는다. 없으면 "Fontconfig head is null" 예외로 -batch 실행 자체가 죽는다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    libasound2 libbsd0 libc6 libmd0 \
    libx11-6 libxau6 libxcb1 libxdmcp6 libxext6 libxi6 libxrender1 libxtst6 \
    xdg-utils zlib1g \
    fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Audiveris 설치 (자체 런타임 동봉이라 별도 JRE 불필요).
# slim 베이스 이미지에는 데스크톱 환경의 표준 디렉토리(/usr/share/applications,
# desktop-directories, mime/packages)가 없어 deb의 postinst가 호출하는
# xdg-desktop-menu/xdg-mime install이 둘 자리를 못 찾아 exit 3으로 실패한다 → 미리 생성.
RUN mkdir -p /usr/share/applications /usr/share/desktop-directories /usr/share/mime/packages \
    && curl -fsSL -o /tmp/audiveris.deb \
      "https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/${AUDIVERIS_DEB}" \
    && dpkg -i /tmp/audiveris.deb || apt-get install -y -f \
    && rm -f /tmp/audiveris.deb

ENV GPC_AUDIVERIS_CMD=/opt/audiveris/bin/Audiveris

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=frontend-build /static ./static

ENV GPC_JOBS_DIR=/srv/jobs
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`vite.config.ts`의 `outDir: '../static'`은 vite root(`frontend/`) 기준 상대경로다. 빌드 스테이지의 `WORKDIR`가 `/app`이고 `frontend` 내용을 그대로 `/app`에 복사했으므로, 빌드 산출물은 `/app`의 상위인 `/static`에 생긴다 — 그래서 2번째 스테이지에서 `COPY --from=frontend-build /static ./static`으로 가져온다(`/app/static`이 아님에 주의).

- [ ] **Step 2: .dockerignore에 frontend 관련 항목 추가**

`.dockerignore`에 아래 2줄을 추가한다(파일 끝에):

```
frontend/node_modules/
frontend/dist/
```

전체 파일은 다음과 같아야 한다:

```
.venv/
__pycache__/
jobs/
tests/
docs/
spikes/
.git/
.pytest_cache/
*.gp5
frontend/node_modules/
frontend/dist/
```

`frontend/node_modules/`는 필수(로컬 설치된 네이티브 바이너리가 빌드 컨텍스트로 들어가면 스테이지1의 `npm ci`가 플랫폼 불일치로 깨질 수 있고, 전송 용량도 커진다 — 어차피 스테이지1에서 `npm ci`가 다시 설치함). `frontend/dist/`는 로컬에 남아있는 이전 vite 빌드 찌꺼기(gitignore도 이미 제외 중)를 컨텍스트에서 뺀다.

- [ ] **Step 3: 이미지 빌드 검증**

Docker Desktop이 떠 있는지 먼저 확인한다:

```bash
docker info >/dev/null 2>&1 && echo "daemon up" || echo "daemon down"
```

**"daemon up"이면** 실제로 빌드해서 검증한다:

```bash
docker build --platform linux/amd64 -t gp-converter-test .
docker run --rm gp-converter-test ls static
docker run --rm gp-converter-test ls static/assets
```

Expected: 첫 번째 `ls static`에 `index.html`이 보이고, 두 번째 `ls static/assets`에 해시가 붙은 `.js`/`.css` 파일이 보인다.

**"daemon down"이면** 빌드 검증은 건너뛰고 `Dockerfile` 문법만 눈으로 재확인한다(스테이지 이름 `frontend-build`가 `FROM`과 `COPY --from`에서 일치하는지, `COPY --from=frontend-build /static ./static` 경로가 맞는지). 리포트에 "Docker 데몬이 꺼져있어 실제 빌드는 검증하지 못함 — 사용자가 로컬에서 `docker build --platform linux/amd64 -t gp-converter-test . && docker run --rm gp-converter-test ls static/assets`로 직접 확인 필요"라고 명시한다.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: Dockerfile 멀티스테이지로 프론트엔드 빌드 자동화"
```

---

### Task 2: docker-compose.yml + .env.example

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

**Interfaces:**
- Consumes: Task 1의 `Dockerfile`(`web`/`worker` 서비스의 `build:` 대상), `app/database.py`의 `DATABASE_URL` 환경변수(기본값 `sqlite:///./gp_converter.db`, 이미 오버라이드 가능), `app/config.py`의 `GPC_JOBS_DIR`(Dockerfile에서 이미 `/srv/jobs`로 설정됨), README에 문서화된 워커 기동 커맨드(`celery -A app.tasks:celery_app worker --loglevel=info --concurrency=2`).
- Produces: `docker-compose.yml`(3서비스, 3볼륨), `.env.example`(전체 환경변수 템플릿) — Task 3(README)이 이 두 파일의 사용법을 문서화.

- [ ] **Step 1: docker-compose.yml 작성**

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

  web:
    build:
      context: .
      dockerfile: Dockerfile
    platform: linux/amd64
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////srv/data/gp_converter.db
    volumes:
      - jobs-data:/srv/jobs
      - db-data:/srv/data
    depends_on:
      - redis

  worker:
    build:
      context: .
      dockerfile: Dockerfile
    platform: linux/amd64
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////srv/data/gp_converter.db
    volumes:
      - jobs-data:/srv/jobs
      - db-data:/srv/data
    depends_on:
      - redis
    command: ["celery", "-A", "app.tasks:celery_app", "worker", "--loglevel=info", "--concurrency=2"]

volumes:
  redis-data:
  jobs-data:
  db-data:
```

`web`은 `Dockerfile`의 기본 `CMD`(uvicorn)를 그대로 쓰므로 `command:`를 안 적는다. `worker`만 `command:`로 celery 워커를 오버라이드한다 — README의 "주의: `-A app.celery_app`이 아니라 `-A app.tasks:celery_app`으로 띄워야 한다" 경고와 동일한 진입점을 쓴다.

`CELERY_BROKER_URL`/`DATABASE_URL`은 `environment:`에 고정값으로 박아넣는다 — compose에서 `environment:`가 `env_file:`보다 우선순위가 높아서, `.env`에 다른 값이 있어도 이 두 값이 이긴다. 이렇게 하는 이유: `redis`라는 호스트명은 compose 내부 네트워크에서만 유효(로컬 비-Docker 개발의 `redis://localhost:6379/0`과 다름)하고, `DATABASE_URL`도 `db-data` 볼륨 마운트 경로(`/srv/data`)에 맞춰 고정돼야 하기 때문 — 사용자가 `.env`에 실수로 다른 값을 넣어도 컨테이너 내부 배선이 깨지지 않는다.

- [ ] **Step 2: .env.example 작성**

```bash
# docker compose용 비밀값/설정 템플릿.
# 복사해서 .env로 저장하고 실제 값을 채운다: cp .env.example .env
# (CELERY_BROKER_URL, DATABASE_URL, GPC_AUDIVERIS_CMD, GPC_JOBS_DIR은
#  docker-compose.yml/Dockerfile이 이미 고정값으로 설정하므로 여기 없음)

# ── 인증 (로그인 세션 JWT + OAuth) ──────
JWT_SECRET_KEY=change-me-to-a-random-secret
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
FRONTEND_URL=http://localhost:8000
BACKEND_URL=http://localhost:8000

# ── Stripe 결제 ──────────────────────
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_ID_PRO=

# ── 파일 저장 (기본 local, jobs-data 볼륨에 저장됨) ──
STORAGE_BACKEND=local
# S3 호환 스토리지(AWS S3/MinIO/R2 등) 사용 시 주석 해제:
# STORAGE_BACKEND=s3
# S3_BUCKET_NAME=
# S3_ENDPOINT_URL=
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_REGION=

# ── 변환 파이프라인 ──────────────────
GPC_MAX_UPLOAD_BYTES=20971520
GPC_STEP_TIMEOUT_SEC=300

# ── 탭(TAB) 인식 보조 모델 (선택 기능, 없으면 휴리스틱으로 폴백) ──
# GUITAR_OMR_DIR=
# GUITAR_OMR_MODEL_DIR=
# GUITAR_OMR_MODEL_REPO=kk9293/guitar-tab-omr
```

- [ ] **Step 3: docker-compose.yml 문법 검증**

```bash
docker compose config
```

Expected: 에러 없이 병합된 YAML이 출력된다(이 명령은 Docker 데몬 연결 없이 클라이언트 사이드에서만 동작 — 데몬이 꺼져있어도 실행 가능. `.env` 파일이 없으면 `env_file: .env` 때문에 경고/에러가 날 수 있으므로, 검증 직전에 `cp .env.example .env`로 임시 파일을 만들고 검증 후 삭제한다):

```bash
cp .env.example .env
docker compose config
rm .env
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: docker-compose.yml + .env.example 추가"
```

---

### Task 3: README 문서화

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1의 `Dockerfile`, Task 2의 `docker-compose.yml`/`.env.example` — 이 태스크는 코드 변경 없이 문서만 추가.
- Produces: 없음(최종 태스크).

- [ ] **Step 1: "Docker Compose로 실행하기" 섹션을 기존 "Docker로 실행하기" 섹션(README.md:78-87) 바로 뒤에 추가**

`README.md`의 `## Docker로 실행하기` 섹션(끝나는 지점: `` `http://localhost:8000`에서 동일하게 사용 가능. `` 다음 줄, `## 환경변수` 헤더 바로 앞)에 아래 내용을 삽입한다:

```markdown

## Docker Compose로 실행하기 (프로덕션)

단일 컨테이너(`docker run`)와 달리, `redis`(작업큐 브로커) + `web`(FastAPI) + `worker`(Celery) 3개 서비스를 한 번에 띄운다. 프론트엔드 빌드도 `Dockerfile` 안에서 자동으로 처리되므로 `npm run build`를 따로 실행할 필요가 없다.

### 1. 환경변수 파일 준비

```bash
cp .env.example .env
```

`.env`를 열어 최소한 `JWT_SECRET_KEY`는 실제 랜덤 값으로 바꾼다. OAuth/Stripe/S3는 해당 기능을 쓸 때만 채우면 된다(비워두면 그 기능만 비활성).

### 2. 기동

```bash
docker compose up --build
```

`http://localhost:8000`에서 접속 가능. 최초 실행 시 Audiveris 설치 + 프론트 빌드 때문에 이미지 빌드에 몇 분 걸린다.

### 3. 데이터 영속성

- `jobs-data` 볼륨: 진행 중인 변환 임시파일 + `STORAGE_BACKEND=local`일 때 저장된 `.gp5` 파일.
- `db-data` 볼륨: SQLite DB 파일.

`docker compose down`으로 컨테이너를 내려도 두 볼륨은 남아있어 데이터가 유지된다. 완전히 초기화하려면:

```bash
docker compose down -v
```

### 4. 알려진 한계

- 리버스프록시/TLS를 포함하지 않는다 — 포트 8000을 그대로 노출하므로, 앞단에 HTTPS/로드밸런서가 필요하면 배포환경에서 직접 구성해야 한다.
- SQLite를 그대로 쓴다 — 단일 노드 전제이며 수평 확장은 지원하지 않는다.
- Audiveris의 Linux 릴리스가 x86_64 전용이라 `platform: linux/amd64`로 고정돼 있다(Apple Silicon 등에서는 에뮬레이션으로 동작, 느림).
```

- [ ] **Step 2: 환경변수 표에 각주 추가**

`README.md`의 `## 환경변수` 섹션(README.md:89) 표 바로 아래, 기존 boto3 자격증명 설명 문단(README.md:110) 다음 줄에 아래 문단을 추가한다:

```markdown

**docker-compose로 실행할 때**는 `CELERY_BROKER_URL`, `DATABASE_URL`, `GPC_AUDIVERIS_CMD`, `GPC_JOBS_DIR` 네 변수를 `docker-compose.yml`/`Dockerfile`이 이미 컨테이너 내부 배선에 맞게 고정해두므로 `.env`에 따로 설정할 필요가 없다(`.env.example` 참고).
```

- [ ] **Step 3: "알려진 한계" 섹션의 jobs_dir 공유 문구 갱신**

`README.md:153`의 다음 문장을 찾는다:

```markdown
- **Celery 워커와 웹서버는 반드시 같은 `GPC_JOBS_DIR` 파일시스템을 공유해야 한다.** job 상태는 파일 기반(`JobStore`)이라, 워커를 다른 호스트/컨테이너로 분리 배포하면서 `jobs_dir`를 공유 볼륨으로 마운트하지 않으면 워커가 `store.get(job_id)`에서 `None`을 받아 아무 에러 없이 조용히 리턴한다 — job이 영원히 `queued`로 멈춘다. 단일 호스트(같은 서버에서 웹+워커 실행) 또는 web/worker가 같은 볼륨을 공유하는 docker-compose 구성에서는 문제 없다.
```

마지막 문장만 아래로 교체한다(나머지는 그대로 유지):

```markdown
- **Celery 워커와 웹서버는 반드시 같은 `GPC_JOBS_DIR` 파일시스템을 공유해야 한다.** job 상태는 파일 기반(`JobStore`)이라, 워커를 다른 호스트/컨테이너로 분리 배포하면서 `jobs_dir`를 공유 볼륨으로 마운트하지 않으면 워커가 `store.get(job_id)`에서 `None`을 받아 아무 에러 없이 조용히 리턴한다 — job이 영원히 `queued`로 멈춘다. 이 프로젝트의 `docker-compose.yml`은 `jobs-data` named volume을 `web`/`worker` 양쪽에 마운트해서 이 문제를 실제로 해소한다.
```

- [ ] **Step 4: README 렌더링 확인**

```bash
grep -n "^## " README.md
```

Expected: `## Docker Compose로 실행하기 (프로덕션)`가 `## Docker로 실행하기`와 `## 환경변수` 사이에 정확히 한 번 나타난다. 다른 헤더 순서는 그대로다.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: Docker Compose 실행법 문서화"
```

---
