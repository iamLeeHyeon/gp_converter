# MusicXML → GP5 매핑 확장 설계

날짜: 2026-07-07
대상 파일: `app/pipeline/musicxml_to_gp.py` (Audiveris 경로 전용, tab-OMR 경로인 `token_to_gp.py`는 무관)

## 배경

Audiveris는 표준 오선보만 읽고 MusicXML로 출력한다. 이걸 GP5로 옮기는
`musicxml_to_gp.py`는 현재 음표/쉼표/화음/붙임줄/박자·조표/다이나믹/기본
아티큘레이션/슬러(근사)/그레이스노트만 매핑한다. 아래 4개를 추가한다:

1. 반복표/엔딩(volta)
2. 가사(1줄) + 코드 이름(다이어그램 없이)
3. 트레몰로 피킹 + 하모닉스
4. 벤드 + 팜뮤트 (raw XML 병행 파싱)

### 스코프에서 제외한 것 (기술적 근거)

- **페르마타**: `guitarpro` 패키지 전체에 fermata 개념이 없음(GP5 포맷
  자체 한계, 문자열 검색 0건 확인). 제외.
- **3성부 이상(다성)**: `guitarpro.models.Measure.maxVoices == 2`가
  writer(`gp5.py`)에 하드코딩되어(`measure.voices[:2]`) 그 이상은 파일
  쓸 때 잘림. 제외(우회책인 트랙 분리는 이번 스코프 아님).
- **멀티트랙(멀티파트)**: 사용자가 이번 라운드에서 스코프 제외로 선택.
- **비브라토**: MusicXML에 전용 태그가 없고 트릴과 같은
  `<wavy-line>`을 공유함 — 원본 데이터 자체에 트릴/비브라토 구분이
  안 남음(라이브러리 문제가 아니라 포맷 자체의 모호성). 제외.
- **코드 다이어그램(프렛박스)**: Audiveris가 원본 다이어그램 그림을
  인식해 `<frame>`으로 낼 방법이 사실상 없음 — 만들면 항상 우리가
  지어낸 값이라 의미 없음. 이름 텍스트만 매핑.

## 아키텍처

새 파이프라인 단계를 만들지 않는다. 기존 `NoteEvent`/`MeasureData`
dataclass에 옵셔널 필드를 추가하고, `_extract_events`/`_collect_notes`/
`_build_song` 안에서 그대로 확장한다.

```python
@dataclass
class NoteEvent:
    ...  # 기존 필드
    tremolo_picking: bool = False
    harmonic: Optional[str] = None       # 'natural' | 'artificial' | None
    bend: bool = False                   # raw XML에서 <bend> 발견 여부
    palm_mute: bool = False              # raw XML에서 <palm-mute> 발견 여부

@dataclass
class MeasureData:
    ...  # 기존 필드
    is_repeat_open: bool = False
    repeat_close: int = -1                # GP5 관례: -1=반복 없음
    repeat_alternative: int = 0           # 비트마스크 (bit0=1번엔딩...)
    chord_name: Optional[str] = None      # 이 마디 첫 비트에 붙일 코드 이름
```

가사는 마디 단위가 아니라 트랙 단위(`song.lyrics`)라 별도로 곡 전체를
한 번 훑어 `LyricLine` 하나를 만든다.

## 1. 반복표 / 엔딩(volta)

`_collect_notes`가 마디를 순회할 때 `m.leftBarline`/`m.rightBarline`
(music21 `bar.Repeat`)과 그 마디를 감싸는 `spanner.RepeatBracket`을 함께
읽는다.

- `leftBarline.direction == 'start'` → `is_repeat_open = True`
- `rightBarline.direction == 'end'` → `repeat_close = (barline.times or 2) - 1`
  (GP5는 "추가 반복 횟수"를 저장하는 오프바이원 관례 — 기존
  `gp5.py`의 read 경로에 이미 있는 `-1`/write 경로의 `+1` 보정과 대칭)
- 이 마디를 스팬하는 `RepeatBracket`이 있으면 `.getNumberList()`로 얻은
  번호마다 `repeat_alternative |= 1 << (n - 1)` — 브래킷이 걸친 모든
  마디에 동일하게 설정(엔딩 시작 마디만이 아니라 전 구간)

`_build_song`의 `_apply_header`에서 `MeasureHeader.isRepeatOpen`/
`repeatClose`/`repeatAlternative`에 그대로 대입.

## 2. 가사 + 코드 이름

**가사**: 멀티버스 지원 안 함(YAGNI, GP5는 최대 5줄 지원하지만 1줄만
채움). `score.parts[0]`을 순서대로 훑어 `note.lyrics`가 있는 음마다
텍스트를 모으고, 음절 사이는 스페이스로 join(멜리스마 연속은 기존
GP 관례상 `+`로 이어붙임 — `syllabic in ('middle','end')`일 때 직전
토큰에 공백 없이 붙임). 첫 가사가 나온 마디 번호를 `startingMeasure`로.
곡 끝에서 `song.lyrics.lines[0]`에 한 번만 대입.

**코드 이름**: `score.parts[0].recurse().getElementsByClass(harmony.ChordSymbol)`
로 각 코드의 `.figure`(또는 `.pitchedCommonName`) 텍스트를 뽑아 그 코드가
속한 마디의 `chord_name`에 저장. `_build_song`에서 그 마디 voices[0]의
첫 비트에 `beat.effect.chord = Chord(length=6, name=chord_name, show=False,
newFormat=True)`를 붙인다(`strings=[-1]*6` 기본값 유지 — 다이어그램은
안 그림, 이름 텍스트만 표시됨).

## 3. 트레몰로 피킹 + 하모닉스

`_extract_events`에서 음표당 `n.expressions`/`n.articulations`를 검사:

- `expressions.Tremolo` 인스턴스가 있으면 `tremolo_picking = True`
  (몇 회 슬래시인지는 GP5 `TremoloPickingEffect`가 세분화 지원하지만
  일단 단순 on/off만 — 필요해지면 `numberOfMarks`로 확장)
- `articulations.Harmonic`/`StringHarmonic` 인스턴스가 있으면
  `.harmonicType`(natural/artificial)을 그대로 `harmonic` 필드에 저장

`_build_song`에서 `gnote.effect.tremoloPicking = TremoloPickingEffect()`
(있을 때만 생성) / `gnote.effect.harmonic = NaturalHarmonic()` 또는
`ArtificialHarmonic()`으로 매핑. 화음·꾸밈음에는 적용 안 함(기존
그레이스노트 처리와 동일하게 단일음 한정 — YAGNI).

## 4. 벤드 + 팜뮤트 (raw XML 병행 파싱)

music21이 `<bend>`/`<palm-mute>`를 파싱하지 않으므로
`xml.etree.ElementTree`로 원본 MusicXML을 별도로 순회하는 헬퍼
`_scan_raw_technicals(xml_path) -> Dict[Tuple[int, int, int], Set[str]]`를
추가한다. 키는 `(measure_number, voice, ordinal)` — `ordinal`은 해당
(마디, 보이스) 안에서 쉼표와 `<chord/>` 연속음을 제외한 실제 음표 순번.
값은 그 노트에 걸린 `{'bend', 'palm_mute'}` 집합(있는 것만).

`_extract_events`가 이벤트를 만들 때 같은 방식으로 순번을 세면서
이 맵을 조회해 `bend`/`palm_mute` 필드를 채운다.

**리스크(문서화하고 감수)**: 이건 "raw XML과 music21 스트림이 같은
순서로 노트를 훑는다"는 가정에 기댄 best-effort 상관관계다. music21이
내부적으로 특정 표기를 드롭하거나 순서를 바꾸는 특이 케이스에서는
어긋날 수 있다. 실사용 데이터(Audiveris 표준보 출력)에서 이 두 태그
자체가 애초에 거의 안 나올 것으로 예상되는 기능이라 감수한다.
코드에 `ponytail:` 주석으로 이 한계와 실패 시 나타나는 증상(엉뚱한
음에 벤드/팜뮤트가 붙음)을 명시한다.

`_build_song`에서 `gnote.effect.bend = BendEffect(...)`(단순 on/off,
구체적 벤드 포인트 곡선은 안 만듦 — YAGNI, "벤드가 있었다"는 사실만
전달) / `gnote.effect.palmMute = True`.

## 에러 처리

넷 다 "있으면 매핑, 없으면 조용히 스킵" — 매핑 실패가 변환 자체를
막지 않는다. 미지원 잇단음 처리(warning 로그 후 무시)와 동일한 관례.

## 테스트

기능당 손으로 작성한 작은 MusicXML fixture 하나씩 →
`musicxml_to_gp5()` 실행 → 산출 GP5를 다시 파싱해서 해당 필드 확인하는
통합 테스트를 추가한다(기존 `tests/` 관례 따름). 벤드/팜뮤트는 raw-XML
순번 상관관계 로직이라 `_scan_raw_technicals`용 유닛 테스트도 별도로
추가한다(여러 보이스/화음이 섞인 마디에서 순번이 어긋나지 않는지).
