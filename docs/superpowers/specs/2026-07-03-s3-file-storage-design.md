# S3 호환 파일 저장 설계 스펙

**날짜:** 2026-07-03
**연관:** Phase 3 후보 E (`docs/session-summary-2026-07-01.md`) — 3개 하위작업(S3 파일저장/SoundFont CDN/Docker Compose) 중 첫 번째. 배포환경 아직 미정.

---

## 목표

저장된 GP5 파일(`File.gp5_path`)을 로컬 디스크뿐 아니라 S3 호환 오브젝트 스토리지(AWS S3, MinIO, Cloudflare R2 등)에도 저장할 수 있게 추상화한다. 배포환경이 아직 안 정해졌으므로 특정 클라우드 업체에 종속되지 않게 만들고, 로컬 개발은 지금처럼 계정 없이 그대로 동작해야 한다.

| 항목 | 결정 |
|------|------|
| 범위 | **저장된 GP5 파일만**(`File.gp5_path`). 변환 작업 중 임시파일(PDF/XML/output.gp5)은 그대로 로컬 디스크 — 범위 밖 |
| 백엔드 선택 | `STORAGE_BACKEND=local\|s3` 환경변수, 기본값 `local`(무변경) |
| S3 호환성 | boto3 + 커스텀 `endpoint_url` — AWS 전용 아님, MinIO/R2 등 어디든 가능 |
| 자격증명 | boto3 표준 환경변수(`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION`) 그대로 사용, 커스텀 이름 안 만듦 |
| 백엔드 전환 시 기존 파일 | 마이그레이션 안 함(YAGNI) — 필요해지면 별도 스크립트 |
| 테스트 | boto3 client를 plain mock(Stripe 때와 동일 컨벤션) — `moto` 등 별도 라이브러리 안 씀. `S3_*` 환경변수 없어도 전체 스위트 통과(기본값이 local이라 자연히 보장) |

---

## 왜 이렇게 복잡한가 — 현재 `gp5_path`의 실제 사용처

`File.gp5_path`는 단순 문자열 컬럼이지만, 5개 라우터/워커 파일이 이걸 **로컬 파일시스템 경로**로 직접 다룬다:

| 파일 | 사용 방식 |
|------|-----------|
| `app/worker.py` | 변환 성공 시 `f.gp5_path = gp5_path`(orchestrator가 만든 로컬 경로) |
| `app/routers/export.py` | `os.path.exists`, `FileResponse(f.gp5_path)`, `gp5_to_midi(f.gp5_path, ...)` |
| `app/routers/edit.py` | `os.path.dirname(f.gp5_path)`로 임시파일 위치 잡고 `os.replace`로 덮어씀 |
| `app/routers/share.py` | `os.path.exists`, `FileResponse(f.gp5_path)` |
| `app/routers/files.py` | `os.remove(f.gp5_path)` (삭제) |

이 전부를 스토리지 추상화 뒤로 감춰야 S3 호환이 의미가 있다.

---

## 아키텍처

`app/storage.py`(신규)에 프로토콜 + 두 구현체:

```python
class Storage(Protocol):
    def save_file(self, key: str, local_path: str) -> None: ...
    def load_to_temp(self, key: str) -> str: ...  # 호출자가 정리 책임
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def response_for(self, key: str, filename: str) -> Response: ...


def get_storage() -> Storage:
    """STORAGE_BACKEND 환경변수(기본 local)로 백엔드 선택."""
```

**핵심 설계 결정 — 기존 파이프라인 함수(PyGuitarPro/mido 기반)는 손대지 않는다.** `guitarpro.parse()`/`guitarpro.write()`/`gp5_to_midi()`는 전부 실제 로컬 파일 경로를 요구한다. S3에서 바로 읽고 쓰게 라이브러리 호출부를 뜯어고치는 대신, `load_to_temp(key)`가 S3 오브젝트를 로컬 임시파일로 내려받아 그 경로를 반환하게 해서 — 이후 코드는 지금처럼 로컬 경로를 그대로 쓴다. `save_file(key, local_path)`도 마찬가지로 "로컬에 다 만든 결과물을 저장소로 업로드"하는 한 방향 동작이다.

- **`LocalStorage`**: `key`가 곧 로컬 경로. `save_file`은 사실상 no-op(이미 그 경로에 있음), `load_to_temp`는 그 경로를 그대로 반환, `response_for`는 `FileResponse(key, filename=filename)`, `exists`/`delete`는 `os.path.exists`/`os.remove` 그대로. **기존 동작과 100% 동일** — 회귀 위험 없음.
- **`S3Storage`**: `key`는 `{file_id}.gp5` 형태(로컬 경로와 무관한 새 네임스페이스). `save_file`은 `s3.upload_file(local_path, bucket, key)`, `load_to_temp`는 `tempfile.mkstemp()` 위치로 `s3.download_file`, `response_for`는 다운로드 후 `FileResponse` + `BackgroundTask(os.unlink, tmp_path)`(기존 `export.py`의 MIDI 임시파일 정리 패턴과 동일), `exists`는 `head_object` try/except, `delete`는 `delete_object`.

각 라우터는 `os.path.*`/`FileResponse(f.gp5_path)` 직접 호출을 `storage.response_for(f.gp5_path, filename)` 등으로 교체한다.

---

## 파일 계획

| 파일 | 변경 |
|------|------|
| `app/storage.py` (신규) | `Storage` 프로토콜, `LocalStorage`, `S3Storage`, `get_storage()` |
| `app/worker.py` (수정) | `_update_file_gp5_path`가 `storage.save_file()` 경유 |
| `app/routers/export.py` (수정) | 다운로드/MIDI export가 `storage.load_to_temp`/`response_for` 경유 |
| `app/routers/edit.py` (수정) | 편집 저장(sync)이 `storage.save_file()` 경유 |
| `app/routers/share.py` (수정) | 공개 다운로드가 `storage.response_for()` 경유 |
| `app/routers/files.py` (수정) | 삭제가 `storage.delete()` 경유 |
| `requirements.txt` (수정) | `boto3` 추가 |
| `README.md` (수정) | `STORAGE_BACKEND`/`S3_BUCKET_NAME`/`S3_ENDPOINT_URL` 환경변수 문서화 |

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local` 또는 `s3` |
| `S3_BUCKET_NAME` | 없음(s3일 때 필수) | 버킷 이름 |
| `S3_ENDPOINT_URL` | 없음(비워두면 진짜 AWS) | MinIO/R2 등 비-AWS S3 호환 엔드포인트 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | boto3 표준 | 자격증명(boto3가 알아서 읽음, 커스텀 이름 없음) |

---

## 테스트 전략

- `LocalStorage`: 실제 파일시스템(`tmp_path`)으로 4개 메서드 전부 검증 — 회귀 방지용, "기존 동작과 동일함"을 증명
- `S3Storage`: `boto3.client("s3")`를 `unittest.mock.patch`로 목킹(Stripe SDK 테스트와 동일 컨벤션), `upload_file`/`download_file`/`head_object`/`delete_object` 호출 인자 검증
- `get_storage()`: `STORAGE_BACKEND` 미설정 시 `LocalStorage` 반환, `s3` 설정 시 `S3Storage` 반환(버킷 없으면 명확한 에러)
- 각 라우터(export/edit/share/files) 테스트는 `storage.response_for`/`save_file`/`delete`를 목킹해서 라우터 로직만 검증 — 실제 S3 계정 불필요
- 전체 스위트는 `S3_*` 환경변수 없이도 통과해야 함(기본값 local이라 자연히 보장)

---

## 알려진 한계 / 범위 제외 (YAGNI)

- 변환 작업 임시파일(PDF/XML/output.gp5)은 계속 로컬 디스크 — Celery 워커의 "jobs_dir 공유 필요" 제약은 이번 스펙으로 해소 안 됨(별도 과제)
- 백엔드 전환 시 기존 저장 파일 마이그레이션 도구 없음
- 멀티 리전/복제/버저닝 등 S3 고급 기능 없음
- SoundFont CDN, Docker Compose는 이 스펙에 포함 안 됨 — Phase 3 E의 남은 하위작업
