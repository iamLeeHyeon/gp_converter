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

### 3. 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속 → PDF 업로드 → 변환 완료되면 `.gp5` 다운로드.

## Docker로 실행하기

Audiveris의 Linux 릴리스가 **x86_64 전용**이라 이미지는 반드시 `linux/amd64`로 빌드해야 한다(Apple Silicon에서도 에뮬레이션으로 동작).

```bash
docker build --platform linux/amd64 -t gp-converter .
docker run --rm --platform linux/amd64 -p 8000:8000 gp-converter
```

`http://localhost:8000`에서 동일하게 사용 가능.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GPC_AUDIVERIS_CMD` | `audiveris` | Audiveris 실행 파일 경로 |
| `GPC_MAX_UPLOAD_BYTES` | `20971520`(20MB) | 업로드 최대 용량 |
| `GPC_STEP_TIMEOUT_SEC` | `300` | 변환 단계별 타임아웃(초) |
| `GPC_JOBS_DIR` | `<cwd>/jobs` | job 작업 디렉토리 |

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
  pipeline/
    audiveris.py        # PDF → MusicXML (Audiveris subprocess)
    musicxml_to_gp.py    # MusicXML → .gp5 (music21 + PyGuitarPro)
    orchestrator.py       # 위 두 단계를 연결
  worker.py              # 백그라운드 변환 실행
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
