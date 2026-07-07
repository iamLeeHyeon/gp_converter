# MusicXML→GP5 매핑 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `app/pipeline/musicxml_to_gp.py`(Audiveris 표준보 경로)가 반복표/엔딩, 가사, 코드 이름, 트레몰로 피킹, 하모닉스, 벤드, 팜뮤트를 GP5로 매핑하게 확장한다.

**Architecture:** 새 파이프라인 단계 없음. 기존 `NoteEvent`/`MeasureData` dataclass에 옵셔널 필드만 추가하고, 기존 `_extract_events`/`_collect_notes`/`_build_song` 흐름 안에서 채운다. 벤드/팜뮤트만 music21이 파싱을 안 해줘서 `xml.etree.ElementTree`로 원본 MusicXML을 병행 스캔하는 별도 헬퍼(`_scan_raw_technicals`)를 추가하고, `(마디번호, 보이스, 순번)` 키로 기존 이벤트 스트림과 상관관계를 맞춘다.

**Tech Stack:** Python, music21 8.3.0(MusicXML 파싱), PyGuitarPro(guitarpro) 0.10.1(GP5 쓰기), pytest.

## Global Constraints

- 대상 파일은 오직 `app/pipeline/musicxml_to_gp.py`와 `tests/test_musicxml_to_gp.py` — tab-OMR 경로(`token_to_gp.py`)는 건드리지 않음.
- 넷 다 "있으면 매핑, 없으면 조용히 스킵" — 매핑 실패가 변환 자체를 막으면 안 됨(기존 미지원 잇단음 처리와 동일 관례).
- 화음·꾸밈음에는 트레몰로/하모닉/벤드/팜뮤트 적용 안 함(YAGNI, 기존 그레이스노트·아티큘레이션 처리와 동일하게 단일음 한정).
- 페르마타/3성부 이상/멀티트랙/비브라토는 스코프 아님(설계 문서 `docs/superpowers/specs/2026-07-07-musicxml-gp5-mapping-extension-design.md` 참고, 기술적 근거로 제외됨).
- 코드 다이어그램(프렛박스)은 안 만듦 — 이름 텍스트만.
- 가사는 1줄(verse 1)만 지원.
- 각 작업 끝나면 `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`로 회귀 확인 후 커밋.

---

### Task 1: 반복표(repeat) + 엔딩(volta)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:56` (import), `app/pipeline/musicxml_to_gp.py:153-164` (`MeasureData`), `app/pipeline/musicxml_to_gp.py:396-448` (`_collect_notes`), `app/pipeline/musicxml_to_gp.py:488-492` (`_apply_header`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `MeasureData.is_repeat_open: bool`, `MeasureData.repeat_close: int`, `MeasureData.repeat_alternative: int` — Task 2 이후 작업들이 그대로 재사용(다른 필드 추가 시 이 필드들 순서/기본값 유지).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py` 맨 끝에 추가:

```python
_REPEAT_VOLTA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <barline location="left"><bar-style>heavy-light</bar-style><repeat direction="forward"/></barline>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <barline location="left"><ending number="1" type="start"/></barline>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
      <barline location="right"><bar-style>light-heavy</bar-style><ending number="1" type="stop"/><repeat direction="backward" times="3"/></barline>
    </measure>
    <measure number="3">
      <barline location="left"><ending number="2" type="start"/></barline>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
      <barline location="right"><ending number="2" type="discontinue"/></barline>
    </measure>
  </part>
</score-partwise>"""


def test_repeat_and_volta_mapped_to_gp5_measure_headers(tmp_path):
    """반복표 시작/닫힘(횟수)과 1·2번 엔딩이 GP5 마디 헤더에 반영돼야 한다."""
    xml_path = tmp_path / "repeat_volta.musicxml"
    xml_path.write_text(_REPEAT_VOLTA_XML, encoding="utf-8")
    out = str(tmp_path / "repeat_volta.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    measures = song.tracks[0].measures

    assert measures[0].isRepeatOpen is True
    assert measures[1].repeatClose == 2, "MusicXML times=3 → GP5 repeatClose=2(3-1)"
    assert measures[1].header.repeatAlternative == 0b01, "1번 엔딩 → bit0"
    assert measures[2].header.repeatAlternative == 0b10, "2번 엔딩 → bit1"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_repeat_and_volta_mapped_to_gp5_measure_headers -v`
Expected: FAIL (`assert False is True` — `isRepeatOpen` 기본값이 `False`라서)

- [ ] **Step 3: 구현**

`app/pipeline/musicxml_to_gp.py:56`의 music21 import 줄을 다음으로 교체:

```python
from music21 import converter, bar as m21bar, note as m21note, chord as m21chord, stream as m21stream, spanner as m21spanner, articulations as m21art, dynamics as m21dyn
```

`MeasureData` (현재 153-164줄)를 다음으로 교체:

```python
@dataclass
class MeasureData:
    """한 마디의 박자/조표와 보이스별 음표 목록.

    voices[0]은 주 멜로디, voices[1](있으면)은 동시에 울리는 두 번째 성부다.
    GP5 Measure가 보이스를 최대 2개까지만 지원하므로 그 이상은 버린다.
    """

    numerator: int
    denominator: int
    key_fifths: int
    voices: List[List[NoteEvent]] = field(default_factory=lambda: [[]])
    is_repeat_open: bool = False
    repeat_close: int = -1
    repeat_alternative: int = 0
    chord_name: Optional[str] = None
```

`_collect_notes` (현재 396-448줄) 맨 앞부분(`part = score.parts[0]` 직후, 마디 loop 시작 전)에 반복표 브래킷 수집 코드를 추가하고, loop 안에서 각 마디의 반복 정보를 읽어 `MeasureData` 생성 시 넘긴다:

```python
    part = score.parts[0]
    measures = list(part.getElementsByClass(m21stream.Measure))

    repeat_alt_by_measure: Dict[int, int] = {}
    for rb in score.recurse().getElementsByClass(m21spanner.RepeatBracket):
        bitmask = 0
        for n in rb.getNumberList():
            bitmask |= 1 << (n - 1)
        for spanned in rb.getSpannedElements():
            repeat_alt_by_measure[spanned.number] = (
                repeat_alt_by_measure.get(spanned.number, 0) | bitmask
            )

    result: List[MeasureData] = []
    numerator, denominator, key_fifths = 4, 4, 0
    running_velocity: Optional[int] = None

    for m in measures:
        if m.timeSignature is not None:
            numerator = m.timeSignature.numerator
            denominator = m.timeSignature.denominator
        if m.keySignature is not None:
            key_fifths = m.keySignature.sharps

        is_repeat_open = (
            isinstance(m.leftBarline, m21bar.Repeat) and m.leftBarline.direction == "start"
        )
        repeat_close = -1
        if isinstance(m.rightBarline, m21bar.Repeat) and m.rightBarline.direction == "end":
            repeat_close = (m.rightBarline.times or 2) - 1
        repeat_alternative = repeat_alt_by_measure.get(m.number, 0)

        expected_ql = numerator * 4.0 / denominator
        voice_streams = list(m.voices)[:2] if m.hasVoices() else [m]
        voices_events = [
            _drop_phantom_leading_rest(_extract_events(vs, initial_velocity=running_velocity), expected_ql)
            for vs in voice_streams
        ]
        for ev in voices_events[0]:
            if ev.velocity is not None:
                running_velocity = ev.velocity

        result.append(MeasureData(
            numerator, denominator, key_fifths, voices_events,
            is_repeat_open=is_repeat_open,
            repeat_close=repeat_close,
            repeat_alternative=repeat_alternative,
        ))
```

(나머지 `_collect_notes` 본문 — 2번째 보이스 빈 배열 채우는 로직 등 — 은 그대로 둔다.)

`_apply_header` (현재 488-492줄)를 다음으로 교체:

```python
    def _apply_header(mh: gpm.MeasureHeader, md: MeasureData) -> None:
        mh.timeSignature.numerator = md.numerator
        mh.timeSignature.denominator.value = md.denominator
        fifths = max(-8, min(8, md.key_fifths))
        mh.keySignature = _FIFTHS_TO_KEYSIG[fifths]
        mh.isRepeatOpen = md.is_repeat_open
        mh.repeatClose = md.repeat_close
        mh.repeatAlternative = md.repeat_alternative
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS(새 테스트 포함, 기존 테스트 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: MusicXML 반복표/엔딩(volta)을 GP5 마디 헤더에 매핑"
```

---

### Task 2: 코드 이름(이름만, 다이어그램 없음)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`(import 줄, `MeasureData`는 Task 1에서 이미 `chord_name` 필드 추가됨, `_collect_notes`, `_fill_measure`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `MeasureData.chord_name`(Task 1에서 이미 정의됨)
- Produces: 없음(마지막 소비 지점)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
_CHORD_SYMBOL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <harmony><root><root-step>A</root-step></root><kind>minor-seventh</kind></harmony>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_symbol_name_attached_to_first_beat(tmp_path):
    """<harmony> 코드 심볼 이름이 그 마디 첫 비트에 붙어야 한다(다이어그램 없이 이름만)."""
    xml_path = tmp_path / "chordsym.musicxml"
    xml_path.write_text(_CHORD_SYMBOL_XML, encoding="utf-8")
    out = str(tmp_path / "chordsym.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    assert beat.effect.chord is not None
    assert beat.effect.chord.name == "Am7"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_chord_symbol_name_attached_to_first_beat -v`
Expected: FAIL (`beat.effect.chord is not None` → `AssertionError`, 항상 `None`이라)

- [ ] **Step 3: 구현**

import 줄(Task 1에서 수정한 그 줄)에 `harmony`를 추가:

```python
from music21 import converter, bar as m21bar, harmony as m21harmony, note as m21note, chord as m21chord, stream as m21stream, spanner as m21spanner, articulations as m21art, dynamics as m21dyn
```

`_collect_notes`의 마디 loop 안, `repeat_alternative = ...` 다음 줄에 추가:

```python
        chord_syms = list(m.recurse().getElementsByClass(m21harmony.ChordSymbol))
        chord_name = chord_syms[0].figure if chord_syms else None
```

그리고 `result.append(MeasureData(...))` 호출에 `chord_name=chord_name` 인자를 추가한다.

`_fill_measure` (현재 628-633줄)를 다음으로 교체:

```python
    def _fill_measure(measure: gpm.Measure, md: MeasureData) -> None:
        for vi, events in enumerate(md.voices):
            _fill_voice(
                measure.voices[vi], events, use_hints=(vi == 0),
                numerator=md.numerator, denominator=md.denominator,
            )
        if md.chord_name is not None and measure.voices[0].beats:
            measure.voices[0].beats[0].effect.chord = gpm.Chord(
                length=6, name=md.chord_name, show=False, firstFret=0,
            )
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: MusicXML 코드 심볼 이름을 GP5 비트에 매핑(다이어그램 없이 이름만)"
```

---

### Task 3: 가사(1줄, verse 1만)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (새 함수 `_collect_lyrics` 추가, `musicxml_to_gp5` 본문)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `_collect_lyrics(score) -> Tuple[Optional[int], str]` — `(첫 가사가 나온 마디 번호 또는 None, 합쳐진 가사 문자열)`. 다른 태스크가 이 함수를 소비하지 않음(마지막 소비 지점, `musicxml_to_gp5` 안에서 바로 `song.lyrics`에 씀).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
_LYRICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>begin</syllabic><text>Hel</text></lyric>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>end</syllabic><text>lo</text></lyric>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>single</syllabic><text>world</text></lyric>
      </note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_lyrics_joined_with_plus_for_syllable_continuation(tmp_path):
    """가사 음절이 이어지면(middle/end) '+'로 붙고, 새 단어는 공백으로 구분돼야 한다."""
    xml_path = tmp_path / "lyrics.musicxml"
    xml_path.write_text(_LYRICS_XML, encoding="utf-8")
    out = str(tmp_path / "lyrics.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.lyrics.lines[0].lyrics == "Hel+lo world"
    assert song.lyrics.lines[0].startingMeasure == 1
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_lyrics_joined_with_plus_for_syllable_continuation -v`
Expected: FAIL (`song.lyrics.lines[0].lyrics == ''`)

- [ ] **Step 3: 구현**

`_collect_notes` 함수 앞에 새 함수를 추가:

```python
def _collect_lyrics(score) -> Tuple[Optional[int], str]:
    """악보 전체에서 가사를 순서대로 모아 한 줄로 합친다(1절만, YAGNI).

    음절이 이어지면(syllabic이 'middle'|'end') 앞 토큰에 공백 없이 '+'로 붙인다
    (GP 관례). 여러 줄(verse) 지원은 안 함 — 첫 줄만 채운다.
    """
    part = score.parts[0]
    tokens: List[str] = []
    starting_measure: Optional[int] = None
    for m in part.getElementsByClass(m21stream.Measure):
        for n in m.recurse().getElementsByClass(m21note.Note):
            if not n.lyrics:
                continue
            if starting_measure is None:
                starting_measure = m.number
            for ly in n.lyrics:
                if ly.syllabic in ("middle", "end") and tokens:
                    tokens[-1] = tokens[-1] + "+" + ly.text
                else:
                    tokens.append(ly.text)
    return starting_measure, " ".join(tokens)
```

`musicxml_to_gp5` 안, `song = _build_song(measures_data, tab_hints=tab_hints)` 다음 줄에 추가:

```python
        starting_measure, lyrics_text = _collect_lyrics(score)
        if lyrics_text:
            song.lyrics.trackChoice = 0
            song.lyrics.lines[0].startingMeasure = starting_measure or 1
            song.lyrics.lines[0].lyrics = lyrics_text
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: MusicXML 가사(1절)를 GP5 lyrics에 매핑"
```

---

### Task 4: 트레몰로 피킹

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (import, 모듈 상수, `NoteEvent`, `_extract_events`, `_fill_voice`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `NoteEvent.tremolo_picking: Optional[int]`(music21 `numberOfMarks` 값 1/2/3 그대로) — Task 5가 같은 자리(단일음 분기)에 이어서 필드 추가하므로 이름/타입 유지.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
_TREMOLO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><ornaments><tremolo type="single">2</tremolo></ornaments></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_tremolo_picking_mapped_to_sixteenth_duration(tmp_path):
    """트레몰로 표기(2슬래시)가 GP5 tremoloPicking(16분음표 속도)로 매핑돼야 한다."""
    xml_path = tmp_path / "tremolo.musicxml"
    xml_path.write_text(_TREMOLO_XML, encoding="utf-8")
    out = str(tmp_path / "tremolo.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.tremoloPicking is not None
    assert note.effect.tremoloPicking.duration.value == guitarpro.models.Duration.sixteenth
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_tremolo_picking_mapped_to_sixteenth_duration -v`
Expected: FAIL (`note.effect.tremoloPicking is not None` → `AssertionError`)

- [ ] **Step 3: 구현**

import 줄에 `expressions`를 추가(Task 2에서 수정한 그 줄):

```python
from music21 import converter, bar as m21bar, harmony as m21harmony, expressions as m21expr, note as m21note, chord as m21chord, stream as m21stream, spanner as m21spanner, articulations as m21art, dynamics as m21dyn
```

`_ARTICULATION_MAP` 상수 (현재 88-93줄) 다음에 새 상수를 추가:

```python
# music21 Tremolo.numberOfMarks(슬래시 개수) → GP5 Duration.value(트레몰로 속도)
_TREMOLO_MARKS_TO_GPV: Dict[int, int] = {
    1: gpm.Duration.eighth,
    2: gpm.Duration.sixteenth,
    3: gpm.Duration.thirtySecond,
}
```

`NoteEvent` (현재 122-150줄)의 필드 목록 맨 끝에 추가:

```python
    tremolo_picking: Optional[int] = None  # music21 Tremolo.numberOfMarks(1|2|3)
```

`_extract_events` 안, 화음/단일음 분기(`if isinstance(n, m21chord.Chord): ... else: ...` 블록) 다음, `pitches = [...]` 줄 다음에 추가:

```python
        tremolo_picking = None
        if not isinstance(n, m21chord.Chord):
            for expr in n.expressions:
                if isinstance(expr, m21expr.Tremolo):
                    tremolo_picking = expr.numberOfMarks
                    break
```

그리고 함수 맨 끝의 `events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet, velocity=current_velocity, articulations=arts, grace=grace))`를 다음으로 교체:

```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet, velocity=current_velocity, articulations=arts, grace=grace, tremolo_picking=tremolo_picking))
```

`_fill_voice`의 단일음 분기(`gnote = Note(beat=beat)` 이후, `_apply_articulations(gnote, ev.articulations)` 다음 줄)에 추가:

```python
            if ev.tremolo_picking is not None:
                trem_value = _TREMOLO_MARKS_TO_GPV.get(ev.tremolo_picking, gpm.Duration.eighth)
                gnote.effect.tremoloPicking = gpm.TremoloPickingEffect(duration=gpm.Duration(value=trem_value))
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: MusicXML 트레몰로 피킹을 GP5 NoteEffect에 매핑"
```

---

### Task 5: 하모닉스(natural/artificial)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (`NoteEvent`, `_extract_events`, `_fill_voice`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `NoteEvent.harmonic: Optional[str]`('natural' | 'artificial')

- [ ] **Step 1: 실패하는 테스트 작성**

```python
_HARMONIC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><technical><harmonic><natural/></harmonic></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_natural_harmonic_mapped_to_gp5_natural_harmonic(tmp_path):
    """자연 하모닉 표기가 GP5 NaturalHarmonic으로 매핑돼야 한다."""
    xml_path = tmp_path / "harmonic.musicxml"
    xml_path.write_text(_HARMONIC_XML, encoding="utf-8")
    out = str(tmp_path / "harmonic.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert isinstance(note.effect.harmonic, guitarpro.models.NaturalHarmonic)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_natural_harmonic_mapped_to_gp5_natural_harmonic -v`
Expected: FAIL (`note.effect.harmonic`이 `None`이라 `isinstance` 확인 실패)

- [ ] **Step 3: 구현**

`NoteEvent`의 `tremolo_picking` 필드 다음 줄에 추가:

```python
    harmonic: Optional[str] = None  # 'natural' | 'artificial' (music21 Harmonic.harmonicType)
```

`_extract_events`의 `tremolo_picking = None` 블록 바로 다음에 추가:

```python
        harmonic = None
        if not isinstance(n, m21chord.Chord):
            for art in n.articulations:
                if isinstance(art, m21art.Harmonic):
                    harmonic = art.harmonicType
                    break
```

`events.append(NoteEvent(...))` 호출을 다음으로 교체(`harmonic=harmonic` 추가):

```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet, velocity=current_velocity, articulations=arts, grace=grace, tremolo_picking=tremolo_picking, harmonic=harmonic))
```

`_fill_voice`의 단일음 분기, Task 4에서 추가한 `tremoloPicking` 블록 다음 줄에 추가:

```python
            if ev.harmonic == "natural":
                gnote.effect.harmonic = gpm.NaturalHarmonic()
            elif ev.harmonic == "artificial":
                gnote.effect.harmonic = gpm.ArtificialHarmonic()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: MusicXML 하모닉스(natural/artificial)를 GP5 NoteEffect에 매핑"
```

---

### Task 6: raw XML 벤드/팜뮤트 스캔 헬퍼

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (import, 새 함수 `_scan_raw_technicals`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `_scan_raw_technicals(xml_path: str) -> Dict[Tuple[int, int, int], Set[str]]` — 키는 `(마디번호, 보이스인덱스, 순번)`, 값은 `{'bend', 'palm_mute'}` 부분집합. Task 7이 이 함수와 반환 타입을 그대로 소비함.

이 태스크는 헬퍼 함수만 만들고 유닛 테스트만 통과시킨다(아직 `_extract_events`/`_build_song`에 연결 안 함 — Task 7에서 연결).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py` 끝에 추가:

```python
def test_scan_raw_technicals_finds_bend_and_palm_mute_by_ordinal(tmp_path):
    """단일 보이스 안에서 (마디, 보이스, 순번)별로 벤드/팜뮤트를 찾아야 한다.

    쉼표·화음 연속음(<chord/>)·꾸밈음(<grace/>)은 순번에서 제외해야 한다
    (_extract_events가 이들을 건너뛰거나 따로 처리하는 것과 동일한 순서 유지).
    """
    from app.pipeline.musicxml_to_gp import _scan_raw_technicals

    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><technical><bend><bend-alter>2</bend-alter></bend></technical></notations>
      </note>
      <note><rest/><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><technical><palm-mute type="start"/></technical></notations>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "raw_technicals.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")

    result = _scan_raw_technicals(str(xml_path))

    # 순번: C(0)=bend, [쉼표는 순번 안 씀], D(1)=palm_mute, E(2)=없음
    assert result == {
        (1, 0, 0): {"bend"},
        (1, 0, 1): {"palm_mute"},
    }
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_scan_raw_technicals_finds_bend_and_palm_mute_by_ordinal -v`
Expected: FAIL (`ImportError: cannot import name '_scan_raw_technicals'`)

- [ ] **Step 3: 구현**

`app/pipeline/musicxml_to_gp.py` 맨 위 import 블록(`import logging` 다음 줄)에 추가:

```python
import xml.etree.ElementTree as ET
```

`_collect_lyrics` 함수(Task 3에서 추가) 바로 다음에 새 함수를 추가:

```python
def _scan_raw_technicals(xml_path: str) -> Dict[Tuple[int, int, int], Set[str]]:
    """원본 MusicXML을 병행 파싱해 (마디, 보이스, 순번)별 벤드/팜뮤트 표기를 찾는다.

    music21이 <bend>/<palm-mute>를 파싱하지 않아서 raw XML을 직접 훑는다.

    ponytail: 이건 "raw XML과 music21 스트림이 같은 순서로 노트를 센다"는
    가정에 기댄 best-effort 상관관계다. 화음/보이스가 복잡하게 얽히면
    어긋날 수 있음 — 실사용 입력(Audiveris 표준보)에 이 태그 자체가 애초에
    거의 안 나올 걸로 예상해서 감수함. 팜뮤트는 <palm-mute type="start"/">
    경계 음표에만 표시하고 그 사이 음표까지 전파하지 않는다(추가로 단순화).
    쉼표·화음 연속음(<chord/>)·꾸밈음(<grace/>)은 순번에서 제외한다
    (_extract_events가 이들을 건너뛰거나 따로 처리하는 것과 동일하게 유지).
    """
    result: Dict[Tuple[int, int, int], Set[str]] = {}
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            measure_number = int(measure.get("number"))
            voice_order: List[str] = []
            ordinals: Dict[str, int] = {}
            for note in measure.findall("note"):
                if note.find("rest") is not None:
                    continue
                if note.find("chord") is not None:
                    continue
                if note.find("grace") is not None:
                    continue
                voice_text = note.findtext("voice") or "1"
                if voice_text not in voice_order:
                    voice_order.append(voice_text)
                voice_index = voice_order.index(voice_text)
                ordinal = ordinals.get(voice_text, 0)
                ordinals[voice_text] = ordinal + 1

                marks: Set[str] = set()
                technical = note.find("notations/technical")
                if technical is not None:
                    if technical.find("bend") is not None:
                        marks.add("bend")
                    if technical.find("palm-mute") is not None:
                        marks.add("palm_mute")
                if marks:
                    result[(measure_number, voice_index, ordinal)] = marks
    return result
```

`typing` import 줄(현재 50줄)에 `Set`를 추가:

```python
from typing import Dict, List, Optional, Set, Tuple
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 벤드/팜뮤트 raw XML 스캔 헬퍼 추가(_scan_raw_technicals)"
```

---

### Task 7: 벤드 + 팜뮤트 연결

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (`NoteEvent`, `_extract_events`, `_collect_notes`, `_fill_voice`, `musicxml_to_gp5`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_scan_raw_technicals(xml_path) -> Dict[Tuple[int, int, int], Set[str]]`(Task 6)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
_BEND_PALM_MUTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notations><technical><bend><bend-alter>2</bend-alter></bend></technical></notations>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notations><technical><palm-mute type="start"/></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_bend_and_palm_mute_mapped_via_raw_xml_correlation(tmp_path):
    """<bend>/<palm-mute>가 순번 상관관계로 올바른 음표에 매핑돼야 한다."""
    xml_path = tmp_path / "bend_palm_mute.musicxml"
    xml_path.write_text(_BEND_PALM_MUTE_XML, encoding="utf-8")
    out = str(tmp_path / "bend_palm_mute.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2

    note0 = beats[0].notes[0]
    note1 = beats[1].notes[0]
    assert note0.effect.bend is not None and len(note0.effect.bend.points) >= 2
    assert note0.effect.palmMute is False
    assert note1.effect.palmMute is True
    assert note1.effect.bend is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_bend_and_palm_mute_mapped_via_raw_xml_correlation -v`
Expected: FAIL (`note0.effect.bend is not None` → `AssertionError`)

- [ ] **Step 3: 구현**

`NoteEvent`의 `harmonic` 필드 다음 줄에 추가:

```python
    bend: bool = False
    palm_mute: bool = False
```

`_extract_events` 함수 시그니처를 다음으로 교체(현재 `def _extract_events(stream_like, initial_velocity: Optional[int] = None) -> List[NoteEvent]:`):

```python
def _extract_events(
    stream_like,
    initial_velocity: Optional[int] = None,
    technicals: Optional[Dict[int, Set[str]]] = None,
) -> List[NoteEvent]:
```

함수 본문 맨 앞(`events: List[NoteEvent] = []` 다음 줄)에 추가:

```python
    ordinal = 0
```

Task 5에서 추가한 `harmonic = None` 블록 바로 다음에 추가:

```python
        marks = technicals.get(ordinal, set()) if technicals else set()
        bend = "bend" in marks
        palm_mute = "palm_mute" in marks
        ordinal += 1
```

(쉼표·그레이스노트는 이 지점 이전에 이미 `continue`로 빠지므로 `ordinal`이 자동으로 스킵된다.)

`events.append(NoteEvent(...))` 호출을 다음으로 교체(`bend=bend, palm_mute=palm_mute` 추가):

```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet, velocity=current_velocity, articulations=arts, grace=grace, tremolo_picking=tremolo_picking, harmonic=harmonic, bend=bend, palm_mute=palm_mute))
```

`_collect_notes` 시그니처를 `def _collect_notes(score, xml_path: str) -> List[MeasureData]:`로 바꾸고, 함수 맨 앞(`part = score.parts[0]` 다음 줄)에 추가:

```python
    raw_technicals = _scan_raw_technicals(xml_path)
```

`voices_events = [...]` 부분(리스트 컴프리헨션)을 다음으로 교체해 `voice_index`와 그 마디의 raw 기술 정보를 함께 넘긴다:

```python
        voices_events = [
            _drop_phantom_leading_rest(
                _extract_events(
                    vs,
                    initial_velocity=running_velocity,
                    technicals={
                        ordinal: marks
                        for (mnum, vidx, ordinal), marks in raw_technicals.items()
                        if mnum == m.number and vidx == voice_index
                    },
                ),
                expected_ql,
            )
            for voice_index, vs in enumerate(voice_streams)
        ]
```

`musicxml_to_gp5` 안, `measures_data = _collect_notes(score)` 호출을 `measures_data = _collect_notes(score, xml_path)`로 바꾼다.

`_fill_voice`의 단일음 분기, Task 5에서 추가한 harmonic 블록 다음 줄에 추가:

```python
            if ev.bend:
                gnote.effect.bend = gpm.BendEffect(
                    type=gpm.BendType.bend,
                    points=[gpm.BendPoint(0, 0), gpm.BendPoint(12, 2)],
                )
            if ev.palm_mute:
                gnote.effect.palmMute = True
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -q`
Expected: 전부 PASS (Task 1~7 테스트 전부 포함)

전체 회귀도 한 번 더 확인:

Run: `.venv/bin/python -m pytest -m "not integration" -q`
Expected: 기존 286개 + 이번에 추가한 7개 = 293개 PASS(± 정확한 총량은 실행해서 확인), 2 deselected

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 벤드/팜뮤트를 raw XML 상관관계로 GP5 NoteEffect에 매핑"
```

---

## 자체 검토

**스펙 커버리지**: 설계 문서의 4개 기능(반복표/엔딩, 가사+코드이름, 트레몰로+하모닉스, 벤드+팜뮤트) 전부 Task 1~7에 대응됨. 제외 스코프(페르마타/3성부/멀티트랙/비브라토)는 코드 변경 없음 — 해당 없음.

**타입 일관성**: `NoteEvent`에 추가되는 필드 순서 — `tremolo_picking`(Task4) → `harmonic`(Task5) → `bend`, `palm_mute`(Task7). `_extract_events`의 `events.append(...)` 호출은 각 태스크에서 이전 태스크가 추가한 인자를 그대로 포함해서 누적 확장한다(Task 5 코드에 Task 4의 `tremolo_picking=tremolo_picking` 포함, Task 7 코드에 Task 4·5 인자 다 포함). `_collect_notes` 시그니처 변경(Task 7에서 `xml_path` 추가)의 유일한 호출부는 `musicxml_to_gp5` 안 한 곳— 같은 태스크에서 함께 수정함. `_extract_events`의 유일한 호출부(`_collect_notes` 안 리스트 컴프리헨션)도 Task 7에서 함께 수정.

**플레이스홀더**: 없음 — 모든 코드 스니펫은 위에서 사전에 실제로 실행해 동작 확인(`guitarpro.write`/`parse` 라운드트립, music21 파싱 결과)한 값 그대로 사용.
