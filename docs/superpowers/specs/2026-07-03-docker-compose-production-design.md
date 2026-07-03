# Docker Compose 프로덕션 설정 설계 스펙

**날짜:** 2026-07-03
**연관:** Phase 3 후보 E (`docs/session-summary-2026-07-01.md`) — S3 파일저장에 이은 두 번째 하위작업.

---

## 목표

`redis`+`web`(FastAPI)+`worker`(Celery)를 `docker-compose.yml` 하나로 묶어서 배포환경이 뭐든(단일 VPS, 어떤 클라우드든) `docker compose up`으로 돌아가게 한다. 지금은 프론트엔드 빌드를 수동으로 돌리고 `docker build`하는데, 이것도 Dockerfile 안에서 자동화한다.

| 항목 | 결정 |
|------|------|
| 서비스 | `redis`(공식 이미지), `web`(FastAPI, 기존 Dockerfile 확장), `worker`(web과 동일 이미지, command만 다름) |
| 프론트 빌드 | Dockerfile 멀티스테이지로 자동화(node 스테이지 → python 스테이지에 산출물 복사) |
| DB | SQLite 유지 + 영속 named volume(컨테이너 재시작해도 데이터 보존). Postgres 전환은 범위 밖(현재 `run_sqlite_migrations`가 SQLite 전용이라 별도 마이그레이션 전략 필요 — 더 큰 작업) |
| 작업 디렉토리 | `GPC_JOBS_DIR`를 named volume으로 web/worker 간 공유 — README에 이미 적혀있던 "web/worker가 파일시스템 공유 안 하면 job이 조용히 멈춤" 한계를 실제로 해소 |
| 리버스프록시/TLS | 포함 안 함 — 배포환경마다 이미 자체 로드밸런서/HTTPS가 있는 경우가 많아 중복 위험. 포트 8000 그대로 노출, TLS/도메인 연결은 배포자 몫 |
| 비밀값 | `.env`(gitignore, 이미 존재) + `env_file:`로 주입. `.env.example` 신규 작성해서 필요한 변수 전부 템플릿화 |
| 검증 | pytest 대상 아님(인프라 설정) — `docker compose up --build`로 실제 띄워서 PDF 업로드→변환→다운로드 전체 플로우가 도는지 수동 스모크테스트 |

---

## 아키텍처

```
docker-compose.yml
├── redis        (redis:7-alpine, named volume: redis-data)
├── web          (Dockerfile 빌드, uvicorn 실행, 포트 8000 노출)
│     volumes: jobs-data:/srv/jobs, db-data:/srv/data
└── worker       (web과 동일 이미지, command: celery -A app.tasks:celery_app worker)
      volumes: jobs-data:/srv/jobs, db-data:/srv/data (web과 공유)
```

`web`과 `worker`는 **같은 이미지**를 쓴다 — 둘 다 Audiveris가 필요하기 때문이다(worker가 실제로 OMR 파이프라인 서브프로세스를 실행함). `command:`만 다르게 오버라이드한다.

**Dockerfile 멀티스테이지:**
```
Stage 1 (node:20-slim): frontend/ 빌드 → /app/static (vite outDir)
Stage 2 (기존 python:3.11-slim-bookworm + Audiveris): Stage 1의 /app/static을 ./static으로 복사
```
기존 Audiveris 설치 로직은 그대로 두고, 프론트 빌드 스테이지만 앞에 추가한다.

**볼륨 2개:**
- `jobs-data` → `GPC_JOBS_DIR`(기본 `/srv/jobs`, 기존 Dockerfile에 이미 설정됨). 진행중인 변환 임시파일 + `STORAGE_BACKEND=local`일 때 저장된 gp5 파일까지 여기 산다 — 이 볼륨이 없으면 컨테이너 재시작 시 전부 유실.
- `db-data` → SQLite 파일 위치. compose에서 `DATABASE_URL=sqlite:////srv/data/gp_converter.db`로 명시 지정(기존 기본값은 `WORKDIR` 기준 상대경로라 볼륨 마운트와 안 맞음).

---

## 파일 계획

| 파일 | 변경 |
|------|------|
| `Dockerfile` | 멀티스테이지로 확장(프론트 빌드 스테이지 추가) |
| `docker-compose.yml` (신규) | redis/web/worker 3서비스 + volumes 2개 |
| `.env.example` (신규) | JWT/OAuth/Stripe/Celery/Storage/Audiveris 등 전체 환경변수 템플릿 |
| `.dockerignore` | `frontend/node_modules/` 추가 |
| `README.md` | "Docker Compose로 실행하기" 섹션 신설(기존 "Docker로 실행하기"는 단일컨테이너용으로 유지) |

---

## 알려진 한계 / 범위 제외 (YAGNI)

- PostgreSQL 전환 없음 — SQLite 유지(수평 확장 안 됨, 단일 노드 전제)
- 리버스프록시/TLS 없음 — 배포자가 앞단에 붙여야 함
- SoundFont는 여전히 외부 jsdelivr CDN 의존(이 스펙 범위 아님)
- 헬스체크/`depends_on: condition: service_healthy` 등 정교한 기동 순서 제어 없음 — 단순 `depends_on`만
- 자동 배포(CI/CD, 이미지 레지스트리 푸시) 없음 — 로컬/서버에서 `docker compose up --build` 실행 전제
