# PDF → Guitar Pro 변환기 설계 (MVP)

작성일: 2026-06-24

> **갱신 (2026-06-24, 스파이크 후):** 출력단을 **TuxGuitar → PyGuitarPro(순수 파이썬)** 로 전환.
> macOS arm64에서 TuxGuitar는 deprecated/헤드리스 불가, PyGuitarPro 0.10.1이 `.gp5` 쓰기 지원.
> 확정 파이프라인: `Audiveris(PDF→MusicXML) → music21(파싱) → PyGuitarPro(.gp5 쓰기)`.
> 아래 본문의 TuxGuitar 언급은 이 변환기 구현으로 대체된다.

## 목표

사용자가 웹에서 악보 PDF를 업로드하면 Guitar Pro 파일(`.gp5`)로 변환해 다운로드한다.

## 범위

- **MVP 입력:** 디지털 표준악보 PDF (MuseScore/Finale 등에서 출력한 오선보 PDF)
- **출력:** `.gp5`
- **제공 형태:** 웹 앱
- **이후 확장(범위 밖):** 기타 탭 PDF → 텍스트 탭 → 스캔 이미지(OMR)

비목표(YAGNI): 사용자 계정, 결제, 편집 기능, 다중 출력 포맷, 스캔 이미지 인식.

## 접근법

선택안 **A: OSS 오케스트레이션 + 자체 출력 변환기** (스파이크로 확정).

```
PDF → Audiveris(PDF→MusicXML) → music21 파싱 → PyGuitarPro(.gp5 쓰기) → 다운로드
```

MusicXML을 중간 포맷으로 삼는다. 인식은 Audiveris(OSS), 출력은 순수 파이썬 라이브러리 PyGuitarPro로 직접 작성한다(원래 폴백 B안이 정식 경로가 됨). Java 서브프로세스는 Audiveris 하나뿐.

## 아키텍처

```
[브라우저] --PDF--> [FastAPI] --job--> [변환 워커]
                                          |
              Audiveris(PDF→MusicXML) → music21+PyGuitarPro(.gp5)
                                          |
[브라우저] <--.gp5 다운로드-- [FastAPI] <--done--
```

## 컴포넌트

각 컴포넌트는 한 가지 책임을 가지며 독립적으로 테스트 가능하다.

1. **프론트엔드** — 최소 HTML/JS. PDF 드래그 업로드, 진행 상태 폴링, `.gp5` 다운로드, 에러 표시.
2. **API (FastAPI)**
   - `POST /convert` — PDF 수신, job 생성, `job_id` 반환
   - `GET /jobs/{id}` — 상태 반환 (`queued` / `running` / `done` / `failed` + 메시지)
   - `GET /jobs/{id}/result` — `.gp5` 다운로드
3. **변환 파이프라인** (코어 모듈, 단계별 격리)
   - `pdf_to_musicxml(pdf_path) -> musicxml_path` — Audiveris CLI subprocess
   - `musicxml_to_gp5(xml_path) -> gp5_path` — music21로 MusicXML 파싱 후 PyGuitarPro로 `.gp5` 작성 (순수 파이썬, 서브프로세스 없음)
   - 오케스트레이터가 단계를 연결하고 단계별 실패를 처리
4. **외부 도구** — Audiveris(Java)만 subprocess. Docker 이미지에 동봉. 출력단은 파이썬 의존성(music21, PyGuitarPro).
5. **저장소** — job별 임시 작업 디렉토리(업로드/중간 MusicXML/출력 gp5). 다운로드 또는 만료 후 청소.

## 데이터 흐름

PDF 업로드 → 임시 저장 → job 큐잉 → 워커가 Audiveris→MusicXML→(music21+PyGuitarPro)→`.gp5` 실행 → `done` 표시 → 사용자 다운로드 → 작업 폴더 청소.

## 비동기 처리

Audiveris는 수초~수분 소요. 업로드 즉시 `job_id`로 응답하고 클라이언트가 상태를 폴링한다. MVP는 FastAPI 백그라운드 워커 + 파일 기반 job 저장으로 시작한다(Celery 등 큐는 과함, 추후 필요 시 도입).

## 에러 처리

단계별 실패는 job을 `failed`로 만들고 사용자용 메시지를 남긴다.

- 업로드: PDF 아님 / 용량 초과 → `400` 거부
- Audiveris: 악보 미검출 / 깨진 PDF → "악보 인식 실패"
- MusicXML 비었거나 무효 → "변환할 음표 없음"
- PyGuitarPro 변환 실패 → "gp 생성 실패"
- 각 단계 타임아웃으로 무한 멈춤 방지

## 테스트 (TDD)

- **단위:** 각 파이프라인 단계를 고정 픽스처로 검증 (샘플 PDF→기대 MusicXML, 샘플 MusicXML→`.gp5` 생성 확인)
- **통합:** 샘플 PDF 전 과정 1회 실행
- **API:** 각 엔드포인트 동작

## 기술 위험 / 스파이크 결과 (2026-06-24 완료)

1. ~~**TuxGuitar 헤드리스**~~ → **해소.** TuxGuitar 폐기, PyGuitarPro로 `.gp5` 쓰기 검증 완료(생성+재파싱 OK). 최대 위험 제거.
2. **Audiveris 배치 CLI** → **통과.** `audiveris -batch -export -output <dir> -- <pdf>`로 `.mxl` 생성, music21 파싱 OK. 단 6페이지 ~7분(느림), 기타 탭은 부정확(표준 오선보 위주 인식).
3. **Docker** → JRE는 Audiveris 번들 런타임 사용, 출력단은 pip 의존성. 추후 패키징.

**남은 핵심 미지수(스파이크 아닌 구현):** MusicXML→GP 매핑 품질 — 음정→(현,프렛) 배치, 박자→Duration, 마디/박자표 구조.

스파이크 스크립트: `spikes/spike_audiveris.sh`, `spikes/spike_pyguitarpro.py`.
