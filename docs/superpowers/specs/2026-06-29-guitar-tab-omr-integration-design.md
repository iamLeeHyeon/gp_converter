# guitar-tab-omr 통합 설계

**날짜:** 2026-06-29  
**목표:** PDF에 탭 보표가 감지되면 Audiveris 대신 guitar-tab-omr을 사용해 GP5로 직접 변환

---

## 배경

현재 파이프라인은 `PDF → Audiveris(MusicXML) → GP5`로 동작한다.
Audiveris는 오선보 중심 OMR이라 기타 탭 보표 인식이 부정확하다.
`guitar-tab-omr`은 탭 시스템 이미지를 입력받아 구조화된 토큰을 출력하는 전용 모델이다.

---

## 아키텍처

### 데이터 흐름

```
orchestrator.py
│
├─ detect_tab_staves(pdf) → regions 있음
│   ├─ omr_tab.py
│   │   ├─ PDF 전체 페이지 스캔 → TabStaffRegion 리스트
│   │   ├─ pymupdf로 시스템별 PNG crop (workdir/clips/)
│   │   ├─ clip manifest JSON 생성
│   │   └─ subprocess: guitar_omr_infer.py → tokenText 리스트 반환
│   │
│   └─ token_to_gp.py
│       ├─ tokenText 파싱 → 마디/비트/음표 구조
│       └─ PyGuitarPro Song 조립 → .gp5 저장
│
└─ detect_tab_staves(pdf) → regions 없음
    └─ 기존: audiveris.py → musicxml_to_gp.py (변경 없음)
```

### 신규 파일

| 파일 | 역할 |
|------|------|
| `app/pipeline/omr_tab.py` | PDF → 시스템 이미지 → subprocess → tokenText 리스트 |
| `app/pipeline/token_to_gp.py` | tokenText → PyGuitarPro Song → .gp5 |

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `orchestrator.py` | 탭 감지 시 omr_tab + token_to_gp 경로로 분기 |
| `requirements.txt` | `pymupdf` 추가 |

---

## omr_tab.py 상세

### 입력
- `pdf_path: str`
- `regions: List[TabStaffRegion]` — detect_tab_staves 결과
- `workdir: str`

### 출력
- `List[str]` — 시스템 순서대로 정렬된 tokenText 리스트

### 처리 단계

1. **이미지 crop**
   - pymupdf로 PDF 열기
   - 각 TabStaffRegion의 y좌표를 pymupdf 좌표계로 변환
     - pdfminer: 좌하단 원점 (y증가=위)
     - pymupdf: 좌상단 원점 (y증가=아래)
   - crop 범위: x=페이지 전체 폭, y=보표 최상단~최하단 + 마진(보표 간격 × 1.5)
   - `workdir/clips/clip-{n}.png` 저장

2. **manifest 생성**
   ```json
   {
     "clips": [
       {"id": "clip-1", "imagePath": "/path/to/clip-1.png"},
       {"id": "clip-2", "imagePath": "/path/to/clip-2.png"}
     ]
   }
   ```

3. **subprocess 실행**
   ```bash
   python {GUITAR_OMR_DIR}/scripts/guitar_omr_infer.py \
     --input-json manifest.json \
     --output-json predictions.json \
     --device auto \
     [--model-dir {GUITAR_OMR_MODEL_DIR}]  # 선택적
   ```

4. **결과 파싱**
   - `predictions[].tokenText` 추출
   - clip 순서 그대로 반환

### 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `GUITAR_OMR_DIR` | 필수 | guitar-tab-omr 레포 루트 경로 |
| `GUITAR_OMR_MODEL_DIR` | 선택 | 로컬 모델 디렉토리 (없으면 HuggingFace 자동 다운로드) |

---

## token_to_gp.py 상세

### 입력
- `token_texts: List[str]` — 시스템별 tokenText
- `out_path: str`

### 출력
- `str` — 저장된 .gp5 경로

### 토큰 포맷

```
TS_4_4                              → 박자표 (분자_분모)
BAR                                 → 마디 시작
END_BAR                             → 마디 끝
DOUBLE_BAR                          → 겹세로줄
BEAT                                → 비트 시작 (이후 토큰이 이 비트에 속함)
DUR_{1|2|4|8|16|32}                → 음표 길이
REST                                → 쉼표
N_S{1-6}_F{0-24}                   → 음표 (현, 프렛)
DYN_{ppp|pp|p|mp|mf|f|ff|fff}     → 다이나믹
BTECH_STRUM_{DOWN|UP}              → 스트럼 방향
```

### 파싱 전략

- 줄 단위 상태머신
- `BEAT` 만나면 이전 비트 flush, 새 비트 시작
- `END_BAR` 만나면 현재 마디 flush
- 다중 tokenText → 마디 이어붙임 (순서 보장)

### 1차 지원 범위

- 기본 음표 / 쉼표 / 화음 ✓
- 다이나믹 (velocity 매핑) ✓
- 스트럼 방향 ✓
- 박자표 ✓
- 점음표 / 잇단음: 제외 (토큰 포맷 확인 후 추가)

---

## 에러 처리

| 상황 | 처리 |
|------|------|
| `GUITAR_OMR_DIR` 미설정 | `GpConvertError` 발생, 명확한 메시지 |
| subprocess 비정상 종료 | `GpConvertError` 발생 |
| 특정 clip 인식 실패 | 경고 로그 후 해당 시스템 스킵, 변환 계속 |
| 알 수 없는 토큰 | 경고 로그 후 스킵 |
| 모든 clip 실패 | `GpConvertError` 발생 |

---

## 크기 관련 주의사항

모델 학습 입력 크기: `height=224, width=1200` (inference 시 자동 리사이즈).  
크기가 달라도 변환 가능하나 극단적 비율 차이 시 정확도 저하 가능.  
핵심은 crop이 탭 시스템 전체를 정확히 담는 것.

---

## 테스트 전략

- `omr_tab.py`: `--dev-mock` 플래그로 모델 없이 subprocess 흐름 테스트
- `token_to_gp.py`: 고정 tokenText 문자열 입력 → GP5 파싱 검증
- 통합: 탭 PDF 샘플로 end-to-end 테스트
