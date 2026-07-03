# gp_converter

PDF 악보를 업로드하면 Guitar Pro 파일(`.gp5`)로 변환해주는 웹 앱.

## 동작 원리

```
PDF 업로드 → Audiveris(OMR, PDF→MusicXML) → music21(파싱) → PyGuitarPro(.gp5 작성) → 다운로드
```

- **입력:** 디지털 표준악보 PDF(MuseScore/Finale 등에서 출력한 오선보). 스캔 이미지나 기타 탭 전용 PDF는 아직 지원하지 않음.
- **탭(TAB) 인식:** 표준악보(5선보)와 탭보표(6선보)가 같은 시스템에 함께 있는 디지털 PDF라면, 탭에 적힌 정확한 현/프렛을 읽어 사용한다(휴리스틱 추정보다 정확). 탭보표가 없거나 숫자 추출 결과가 표준악보 음표 개수와 다르면 자동으로 기존 휴리스틱(최저프렛)으로 폴백한다.
- **출력:** Guitar Pro 5(`.gp5`) 파일.
- **변환 방식:** Audiveris(Java, 광학 악보 인식)로 PDF를 MusicXML로 바꾼 뒤, 순수 Python(`music21` + `PyGuitarPro`)으로 `.gp5`를 직접 작성한다. Java 서브프로세스는 Audiveris 하나뿐.

## 기술 스택

- **백엔드:** Python 3.9+, FastAPI, uvicorn
- **변환 파이프라인:** Audiveris 5.10.2(OMR), music21(MusicXML 파싱), PyGuitarPro(GP5 작성)
- **프론트:** 최소 HTML/JS (`static/index.html`)
- **테스트:** pytest

## 로컬에서 실행하기

### 1. 의존성 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 2. Audiveris 설치 (OMR 엔진)

[Audiveris 릴리스](https://github.com/Audiveris/audiveris/releases)에서 OS에 맞는 패키지를 받아 설치한다.

- macOS: `.dmg` 다운로드 → `Audiveris.app`을 `/Applications`로 복사
- Linux: `.deb`/`.rpm` 사용 (Dockerfile 참고)

실행 경로가 기본값(`audiveris`)과 다르면 환경변수로 지정한다:

```bash
export GPC_AUDIVERIS_CMD=/Applications/Audiveris.app/Contents/MacOS/Audiveris
```

### 3. Redis + Celery 워커 실행

변환 작업은 Celery 워커가 처리한다. 로컬에서 Redis를 띄운다:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

브로커 주소가 기본값(`redis://localhost:6379/0`)과 다르면 환경변수로 지정한다:

```bash
export CELERY_BROKER_URL=redis://localhost:6379/0
```

별도 터미널에서 워커를 띄운다(동시 처리 개수는 `--concurrency`로 조절):

```bash
celery -A app.tasks:celery_app worker --loglevel=info --concurrency=2
```

**주의:** `-A app.celery_app`이 아니라 `-A app.tasks:celery_app`으로 띄워야 한다. `app/celery_app.py`는 Celery 앱 인스턴스만 정의하고 `process_job_task`는 `app/tasks.py`에 정의되는데, 워커 프로세스가 `-A app.celery_app`로만 뜨면 `app/tasks.py`를 임포트한 적이 없어 task 자체를 모른다(`celery -A app.celery_app worker` → `[tasks]` 목록이 비어있고, 실제 작업을 보내면 `KeyError: 'gp_converter.process_job'`로 워커가 거부한다). `app.tasks`를 진입점으로 지정해야 그 모듈이 임포트되면서 `celery_app`을 가져오고 task 데코레이터가 실행돼 등록된다.

### 4. 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속 → PDF 업로드 → 변환 완료되면 `.gp5` 다운로드.

**주의:** Celery 워커가 떠 있지 않으면 `/convert`는 job을 큐에 넣기만 하고 실제 변환은 영영 시작되지 않는다(`GET /jobs/{id}`가 `queued`에서 안 넘어감).

## Docker로 실행하기

Audiveris의 Linux 릴리스가 **x86_64 전용**이라 이미지는 반드시 `linux/amd64`로 빌드해야 한다(Apple Silicon에서도 에뮬레이션으로 동작).

```bash
docker build --platform linux/amd64 -t gp-converter .
docker run --rm --platform linux/amd64 -p 8000:8000 gp-converter
```

`http://localhost:8000`에서 동일하게 사용 가능.

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

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GPC_AUDIVERIS_CMD` | `audiveris` | Audiveris 실행 파일 경로 |
| `GPC_MAX_UPLOAD_BYTES` | `20971520`(20MB) | 업로드 최대 용량 |
| `GPC_STEP_TIMEOUT_SEC` | `300` | 변환 단계별 타임아웃(초) |
| `GPC_JOBS_DIR` | `<cwd>/jobs` | job 작업 디렉토리 |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery 브로커(Redis) 주소 |
| `STORAGE_BACKEND` | `local` | 파일 저장 백엔드: `local` 또는 `s3` |
| `S3_BUCKET_NAME` | 없음(s3일 때 필수) | S3 버킷 이름 |
| `S3_ENDPOINT_URL` | 없음(비우면 AWS) | MinIO/R2 등 비-AWS S3 호환 엔드포인트 |
| `STRIPE_SECRET_KEY` | 없음(필수) | Stripe API 시크릿 키 |
| `STRIPE_WEBHOOK_SECRET` | 없음(필수) | Stripe 웹훅 서명 검증 시크릿 |
| `STRIPE_PRICE_ID_PRO` | 없음(필수) | Pro 플랜(월 $4.99) 구독 Price ID |
| `JWT_SECRET_KEY` | 없음(필수) | 로그인 세션 JWT 서명 시크릿 |
| `GOOGLE_CLIENT_ID` | 없음 | Google OAuth 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 없음 | Google OAuth 클라이언트 시크릿 |
| `GITHUB_CLIENT_ID` | 없음 | GitHub OAuth 클라이언트 ID |
| `GITHUB_CLIENT_SECRET` | 없음 | GitHub OAuth 클라이언트 시크릿 |

`STORAGE_BACKEND=s3`일 때는 위 세 변수 외에 boto3 표준 AWS 자격증명 환경변수(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, 필요시 `AWS_REGION`)도 반드시 설정해야 한다. 이 프로젝트는 별도 자격증명 변수명을 만들지 않고 boto3의 기본 자격증명 체인(env → 공유 credentials 파일 → IAM 역할 순)을 그대로 사용한다.

**docker-compose로 실행할 때**는 `CELERY_BROKER_URL`, `DATABASE_URL`, `GPC_AUDIVERIS_CMD`, `GPC_JOBS_DIR` 네 변수를 `docker-compose.yml`/`Dockerfile`이 이미 컨테이너 내부 배선에 맞게 고정해두므로 `.env`에 따로 설정할 필요가 없다(`.env.example` 참고).

## 테스트

```bash
pytest              # 단위/API 테스트 (외부 도구 불필요, 모킹됨)
pytest -m integration  # 실제 Audiveris로 전체 파이프라인 검증 (Audiveris 설치 필요)
```

## API

| 엔드포인트 | 설명 |
|---|---|
| `POST /convert` | PDF 업로드, `{"job_id": "..."}` 반환 |
| `GET /jobs/{id}` | 변환 상태 조회: `queued` / `running` / `done` / `failed` |
| `GET /jobs/{id}/result` | 완료된 `.gp5` 다운로드 |

## 프로젝트 구조

```
app/
  config.py            # 환경변수 기반 설정
  jobs.py               # 파일 기반 job 상태 저장소
  storage.py             # 파일 저장 추상화 (local/S3)
  pipeline/
    audiveris.py        # PDF → MusicXML (Audiveris subprocess)
    musicxml_to_gp.py    # MusicXML → .gp5 (music21 + PyGuitarPro)
    orchestrator.py       # 위 두 단계를 연결
  worker.py              # 백그라운드 변환 실행
  celery_app.py          # Celery 앱 인스턴스 (브로커 설정)
  tasks.py               # Celery task 래퍼 (process_job 위임)
  main.py                # FastAPI 앱
static/
  index.html             # 업로드/다운로드 프론트엔드
tests/                   # pytest (단위 + API + 통합)
spikes/                  # 외부 도구 검증 스크립트
docs/superpowers/        # 설계 문서 및 구현 계획
```

## 알려진 한계

- 탭 인식은 디지털 PDF 한정이며, 표준악보 없이 탭보표만 있는 PDF, 스캔 이미지 탭, 화음(동시발음) 탭, 해머링/슬라이드 등 기법 기호는 지원하지 않는다(`X` 뮤트 표시는 스킵됨). 자세한 한계는 `docs/superpowers/specs/2026-06-24-guitar-tab-recognition-design.md` 참고.
- Audiveris OMR은 PDF 페이지 수에 비례해 느리다(예: 6페이지 ~7분).
- **Celery 워커와 웹서버는 반드시 같은 `GPC_JOBS_DIR` 파일시스템을 공유해야 한다.** job 상태는 파일 기반(`JobStore`)이라, 워커를 다른 호스트/컨테이너로 분리 배포하면서 `jobs_dir`를 공유 볼륨으로 마운트하지 않으면 워커가 `store.get(job_id)`에서 `None`을 받아 아무 에러 없이 조용히 리턴한다 — job이 영원히 `queued`로 멈춘다. 이 프로젝트의 `docker-compose.yml`은 `jobs-data` named volume을 `web`/`worker` 양쪽에 마운트해서 이 문제를 실제로 해소한다.
- 익명(비로그인) `/convert`도 동일한 Redis 큐에 우선순위 구분 없이 쌓인다 — 무료플랜 사용량 제한은 로그인 유저에게만 적용되고 익명 요청은 우회하므로, 악의적으로 익명 요청을 대량으로 보내면 정상 유저의 job이 큐에서 밀릴 수 있다. 레이트리밋/우선순위 큐는 아직 없음(추후 과제).
- `STORAGE_BACKEND`을 바꾸면(local↔s3) 이미 저장된 기존 파일은 자동 이관되지 않는다. 필요하면 수동으로 옮겨야 한다.
- `STORAGE_BACKEND=s3`일 때는 파일 다운로드/공유링크 접근마다 전체 파일을 로컬 임시파일로 내려받은 뒤(`load_to_temp`) 서빙한다(직접 스트리밍 아님). 특히 `GET /files/shared/{token}`는 인증 없이 공개된 엔드포인트라 트래픽이 몰리면 `local` 백엔드 대비 지연/대역폭/로컬 디스크 사용이 늘어난다.
