# 음악 기호 GP5 변환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MusicXML의 잇단음·다이나믹·슬러·아티큘레이션·그레이스노트를 GP5로 변환한다.

**Architecture:** 기존 파이프라인(`_extract_events` → `NoteEvent` → `_fill_voice`) 패턴 그대로 유지. `NoteEvent`에 필드 5개 추가, `_extract_events`에서 music21 정보를 추출해 담고, `_fill_voice`에서 GP5 `Beat`/`Note` 객체에 적용한다.

**Tech Stack:** Python 3.9, music21(Dynamic·Slur·articulations·GraceNote), PyGuitarPro(Tuplet·GraceEffect·NoteEffect.hammer/staccato/accentuatedNote/letRing)

## Global Constraints

- 수정 파일: `app/pipeline/musicxml_to_gp.py` 한 파일만. 새 파일 생성 금지.
- 테스트 파일: `tests/test_musicxml_to_gp.py`에만 추가.
- 기존 전체 테스트(67 passed, 2 deselected) 회귀 없어야 함.
- TDD 필수: 테스트 RED 확인 후 구현, GREEN 확인 후 커밋.
- 페르마타: 무시(코드 변경 없음).
- 잇단음 기준: `NoteEvent.tuplet = (enters, times)`. `_fill_voice`에서 base_ql = `ev.ql * enters / times`로 계산 후 `_ql_to_gp_duration(base_ql)` 호출. `beat.duration.tuplet = gpm.Tuplet(enters=enters, times=times)`.
- 다이나믹 velocity 매핑: ppp=15, pp=31, p=47, mp=63, mf=79, f=95, ff=111, fff=127. `None`이면 기본값(95).
- 슬러 → hammer-on: 슬러의 첫 번째 음은 normal, 이후 음들은 `NoteEffect.hammer = True`.
- 아티큘레이션 매핑: `Staccato`→staccato, `Accent`→accentuatedNote, `StrongAccent`→heavyAccentuatedNote, `Tenuto`→letRing.
- 그레이스노트: 단일음에만 적용(화음 무시). grace_midi < main_midi → `GraceEffectTransition.hammer`, 그 외 → `GraceEffectTransition.slide`. `GraceEffect(duration=32, fret=fret, transition=trans)`.
- PyGuitarPro 지원 잇단음: `(3,2),(5,4),(6,4),(7,4),(9,8),(10,8),(11,8),(12,8),(13,8)`. 이외엔 경고 후 무시.
- venv 활성화: `source .venv/bin/activate` (저장소 루트 `/Users/leehyeon/Desktop/projects/gp_converter` 기준).

---

### Task 1: NoteEvent 필드 추가 + 기존 호출부 마이그레이션

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:91-108`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Produces: `NoteEvent` 데이터클래스에 필드 5개 추가(기본값 있어 기존 코드 호환). 이후 태스크 전부가 이 필드를 읽고 쓴다.
  ```python
  tuplet: Optional[Tuple[int, int]] = None
  velocity: Optional[int] = None
  hammer: bool = False
  articulations: List[str] = field(default_factory=list)
  grace: Optional[Tuple[int, str]] = None
  ```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가:

```python
def test_note_event_new_fields_have_correct_defaults():
    """NoteEvent의 새 필드가 올바른 기본값을 가져야 한다."""
    ev = NoteEvent(pitches=[60], ql=1.0, tied=[False])
    assert ev.tuplet is None
    assert ev.velocity is None
    assert ev.hammer is False
    assert ev.articulations == []
    assert ev.grace is None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate
python -m pytest tests/test_musicxml_to_gp.py::test_note_event_new_fields_have_correct_defaults -v
```
Expected: `FAILED` — `NoteEvent` has no field `tuplet` 등.

- [ ] **Step 3: NoteEvent 수정**

`app/pipeline/musicxml_to_gp.py`에서 `NoteEvent` 클래스를 찾아 다음으로 교체:

```python
@dataclass
class NoteEvent:
    """한 음표(또는 화음)의 (음높이 목록, 길이, 이음줄 연속 여부).

    pitches는 MIDI 내림차순(높은음 먼저) 리스트다. 단일음은 길이 1,
    화음은 길이 2 이상, 쉼표(is_rest=True)는 빈 리스트다.

    tied는 pitches와 같은 길이로, 음마다 따로 이음줄 연속 여부를 담는다
    (인덱스 i가 pitches[i]에 대응). music21 Chord의 .tie는 구성음 중 하나의
    tie만 대표로 골라 화음 전체에 적용하는데, 실제 곡에는 화음 안에서 음마다
    tie 상태가 다른 경우(한 음은 이어지고 한 음은 새로 침)가 흔히 있어
    화음 전체에 하나의 값을 쓰면 안 된다.

    tuplet: (enters, times) 잇단음 비율. 예: (3,2)=셋잇단. None이면 일반 박자.
    velocity: GP5 Note.velocity (15~127). None이면 기본값(forte=95).
    hammer: 슬러 안 후속음이면 True → NoteEffect.hammer=True.
    articulations: ['staccato'|'accent'|'strong-accent'|'tenuto'] 리스트.
    grace: (grace_MIDI, transition) 꾸밈음. transition='hammer'|'slide'.
    """

    pitches: List[int]
    ql: float
    tied: List[bool] = field(default_factory=list)
    is_rest: bool = False
    tuplet: Optional[Tuple[int, int]] = None
    velocity: Optional[int] = None
    hammer: bool = False
    articulations: List[str] = field(default_factory=list)
    grace: Optional[Tuple[int, str]] = None
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_note_event_new_fields_have_correct_defaults -v
```
Expected: `PASSED`

- [ ] **Step 5: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 기존 67 passed + 신규 1 = 68 passed, 2 deselected

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: NoteEvent에 음악 기호 필드(tuplet/velocity/hammer/articulations/grace) 추가"
```

---

### Task 2: 잇단음(Tuplet) 추출 + 적용

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: Task 1의 `NoteEvent.tuplet: Optional[Tuple[int, int]]`
- Produces:
  - 모듈 상수 `_SUPPORTED_TUPLETS: frozenset`
  - `_extract_events`가 `NoteEvent.tuplet`을 채움
  - `_fill_voice`가 `beat.duration.tuplet = gpm.Tuplet(enters, times)` 적용

- [ ] **Step 1: 테스트 픽스처 + 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가:

```python
_TRIPLET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>6</divisions>
        <time><beats>2</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
        <notations><tuplet type="start" number="1" placement="above"/></notations>
      </note>
      <note>
        <pitch><step>D</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
      </note>
      <note>
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
        <notations><tuplet type="stop" number="1"/></notations>
      </note>
      <note><rest/><duration>6</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_triplet_eighth_notes_have_tuplet_duration(tmp_path):
    """셋잇단 8분음표 3개가 GP5에서 Tuplet(enters=3, times=2)으로 표시돼야 한다."""
    xml_path = tmp_path / "triplet.musicxml"
    xml_path.write_text(_TRIPLET_XML, encoding="utf-8")
    out = str(tmp_path / "triplet.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 3, f"셋잇단 3음이 있어야 하는데 {len(beats)}개"
    for i, beat in enumerate(beats):
        assert beat.duration.tuplet.enters == 3, f"beat {i}: enters != 3"
        assert beat.duration.tuplet.times == 2, f"beat {i}: times != 2"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_triplet_eighth_notes_have_tuplet_duration -v
```
Expected: `FAILED` — tuplet.enters가 1 (기본값, 잇단음 미적용)

- [ ] **Step 3: 상수 추가**

`app/pipeline/musicxml_to_gp.py`의 `_DOTTED_QL_TO_GPV` 바로 아래에 추가:

```python
_SUPPORTED_TUPLETS: frozenset = frozenset([
    (3, 2), (5, 4), (6, 4), (7, 4),
    (9, 8), (10, 8), (11, 8), (12, 8), (13, 8),
])
```

- [ ] **Step 4: `_extract_events` 수정 — 잇단음 추출**

`_extract_events` 내부에서 기존 `pitches = ...` 계산 이후, `events.append(...)` 직전에 아래 코드를 추가:

```python
        # 잇단음 감지
        tuplet = None
        if not isinstance(n, m21note.Rest) and n.duration.tuplets:
            tp = n.duration.tuplets[0]
            enters = tp.numberNotesActual
            times = tp.numberNotesNormal
            if (enters, times) in _SUPPORTED_TUPLETS:
                tuplet = (enters, times)
            else:
                logger.warning("미지원 잇단음 %d:%d — 무시", enters, times)
```

그리고 `events.append(NoteEvent(...))` 호출에 `tuplet=tuplet` 추가:

현재 코드:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied))
```
수정 후:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet))
```

쉼표(`is_rest=True`)에는 잇단음도 적용한다. 쉼표 처리 부분도 수정:

현재:
```python
        if isinstance(n, m21note.Rest):
            events.append(NoteEvent(pitches=[], ql=ql, is_rest=True))
            continue
```
수정 후:
```python
        if isinstance(n, m21note.Rest):
            rest_tuplet = None
            if n.duration.tuplets:
                tp = n.duration.tuplets[0]
                e, t = tp.numberNotesActual, tp.numberNotesNormal
                if (e, t) in _SUPPORTED_TUPLETS:
                    rest_tuplet = (e, t)
            events.append(NoteEvent(pitches=[], ql=ql, is_rest=True, tuplet=rest_tuplet))
            continue
```

- [ ] **Step 5: `_fill_voice` 수정 — 잇단음 적용**

`_fill_voice` 내부의 `gp_val, is_dotted = _ql_to_gp_duration(ev.ql)` 줄을 다음으로 교체:

```python
            if ev.tuplet is not None:
                enters, times = ev.tuplet
                ql_for_duration = ev.ql * enters / times
            else:
                ql_for_duration = ev.ql
            gp_val, is_dotted = _ql_to_gp_duration(ql_for_duration)
```

그리고 각 분기에서 `beat.duration.isDotted = is_dotted` 바로 다음에 추가(rest/chord/single-note 세 곳 모두):

```python
            if ev.tuplet is not None:
                enters, times = ev.tuplet
                beat.duration.tuplet = gpm.Tuplet(enters=enters, times=times)
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_triplet_eighth_notes_have_tuplet_duration -v
```
Expected: `PASSED`

- [ ] **Step 7: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 69 passed, 2 deselected

- [ ] **Step 8: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 잇단음(tuplet) GP5 Duration.tuplet으로 변환"
```

---

### Task 3: 다이나믹(Dynamics) 추출 + 적용

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: Task 1의 `NoteEvent.velocity: Optional[int]`
- Produces:
  - 모듈 상수 `_DYNAMIC_VELOCITY: dict`
  - 모듈 함수 `_build_velocity_map(stream_like) -> Dict[float, int]`
  - `_extract_events`에서 `NoteEvent.velocity` 채움
  - `_fill_voice`에서 `gnote.velocity = ev.velocity` 적용

- [ ] **Step 1: 테스트 픽스처 + 테스트 작성**

```python
_DYNAMICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction placement="above">
        <direction-type><dynamics><mf/></dynamics></direction-type>
      </direction>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <direction placement="above">
        <direction-type><dynamics><p/></dynamics></direction-type>
      </direction>
      <note><pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_dynamics_set_note_velocity_with_carry_forward(tmp_path):
    """다이나믹 기호가 이후 음표의 velocity를 바꾸고 carry-forward돼야 한다.

    mf(velocity=79) 이후 C5·D5는 79, p(velocity=47) 이후 E5·F5는 47.
    """
    xml_path = tmp_path / "dynamics.musicxml"
    xml_path.write_text(_DYNAMICS_XML, encoding="utf-8")
    out = str(tmp_path / "dynamics.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 4
    assert beats[0].notes[0].velocity == 79, "C5: mf=79"
    assert beats[1].notes[0].velocity == 79, "D5: mf carry-forward=79"
    assert beats[2].notes[0].velocity == 47, "E5: p=47"
    assert beats[3].notes[0].velocity == 47, "F5: p carry-forward=47"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_dynamics_set_note_velocity_with_carry_forward -v
```
Expected: `FAILED` — 모든 음표 velocity가 기본값 95

- [ ] **Step 3: 상수 + 헬퍼 함수 추가**

`_SUPPORTED_TUPLETS` 바로 아래에 추가:

```python
_DYNAMIC_VELOCITY: Dict[str, int] = {
    'ppp': 15, 'pp': 31, 'p': 47, 'mp': 63,
    'mf': 79,  'f':  95, 'ff': 111, 'fff': 127,
}
```

`_ql_to_gp_duration` 함수 바로 위에 추가:

```python
def _build_velocity_map(stream_like) -> Dict[float, int]:
    """스트림에서 Dynamic 객체를 찾아 offset → velocity 딕셔너리를 만든다."""
    import music21.dynamics as m21dyn
    result: Dict[float, int] = {}
    for el in stream_like.recurse().getElementsByClass(m21dyn.Dynamic):
        v = _DYNAMIC_VELOCITY.get(el.value)
        if v is not None:
            result[float(el.offset)] = v
    return result
```

- [ ] **Step 4: `_extract_events` 수정 — 다이나믹 carry-forward**

`_extract_events` 함수 시작부에서 `events: List[NoteEvent] = []` 줄 다음에 추가:

```python
    vel_map = _build_velocity_map(stream_like)
    sorted_vel_offsets = sorted(vel_map)
```

그리고 `for n in stream_like.notesAndRests:` 루프 안에서, `ql = float(...)` 직후에 추가:

```python
        note_offset = float(n.offset)
        current_velocity: Optional[int] = None
        for off in sorted_vel_offsets:
            if off <= note_offset:
                current_velocity = vel_map[off]
            else:
                break
```

기존 `events.append(NoteEvent(pitches=[], ql=ql, is_rest=True, tuplet=rest_tuplet))` 에 `velocity=current_velocity` 추가:
```python
        events.append(NoteEvent(pitches=[], ql=ql, is_rest=True,
                                tuplet=rest_tuplet, velocity=current_velocity))
```

기존 `events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet))` 에 `velocity=current_velocity` 추가:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied,
                                tuplet=tuplet, velocity=current_velocity))
```

- [ ] **Step 5: `_fill_voice` 수정 — velocity 적용**

단일음 분기에서 `gnote = Note(beat=beat)` 이후에 추가:
```python
            if ev.velocity is not None:
                gnote.velocity = ev.velocity
```

화음 분기에서 `gnote = Note(beat=beat)` 이후에 추가:
```python
                    gnote = Note(beat=beat)
                    if ev.velocity is not None:
                        gnote.velocity = ev.velocity
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_dynamics_set_note_velocity_with_carry_forward -v
```
Expected: `PASSED`

- [ ] **Step 7: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 70 passed, 2 deselected

- [ ] **Step 8: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 다이나믹(Dynamic) carry-forward로 Note.velocity 설정"
```

---

### Task 4: 슬러(Slur → hammer-on) 추출 + 적용

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: Task 1의 `NoteEvent.hammer: bool`
- Produces: `_extract_events`가 슬러 후속음에 `hammer=True` 설정, `_fill_voice`가 `gnote.effect.hammer = True` 적용

- [ ] **Step 1: 테스트 픽스처 + 테스트 작성**

```python
_SLUR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>3</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><slur type="start" number="1"/></notations>
      </note>
      <note>
        <pitch><step>A</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
      </note>
      <note>
        <pitch><step>B</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><slur type="stop" number="1"/></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_slur_marks_continuation_notes_as_hammer_on(tmp_path):
    """슬러 안의 첫 번째 음은 normal, 이후 음들은 hammer-on이어야 한다."""
    xml_path = tmp_path / "slur.musicxml"
    xml_path.write_text(_SLUR_XML, encoding="utf-8")
    out = str(tmp_path / "slur.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 3
    assert beats[0].notes[0].effect.hammer is False, "슬러 첫 음은 normal"
    assert beats[1].notes[0].effect.hammer is True, "슬러 두 번째 음은 hammer"
    assert beats[2].notes[0].effect.hammer is True, "슬러 세 번째 음은 hammer"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_slur_marks_continuation_notes_as_hammer_on -v
```
Expected: `FAILED` — 모든 음 `hammer=False`

- [ ] **Step 3: import 추가**

`app/pipeline/musicxml_to_gp.py` 상단 import 블록(`from music21 import ...` 줄)에 `spanner as m21spanner` 추가:

```python
from music21 import converter, note as m21note, chord as m21chord, stream as m21stream, spanner as m21spanner
```

- [ ] **Step 4: `_extract_events` 수정 — 슬러 pre-scan**

`_extract_events` 함수 시작부에서 `vel_map = ...` 줄 다음에 추가:

```python
    slur_continuation_ids: set = set()
    for slur in stream_like.recurse().getElementsByClass(m21spanner.Slur):
        for n in slur.getSpannedElements():
            if not slur.isFirst(n):
                slur_continuation_ids.add(id(n))
```

그리고 음표 처리 루프 안에서 `tuplet = None` 줄 다음에 추가:

```python
        hammer = id(n) in slur_continuation_ids
```

기존 `events.append(NoteEvent(..., tuplet=tuplet, velocity=current_velocity))` 에 `hammer=hammer` 추가:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied,
                                tuplet=tuplet, velocity=current_velocity, hammer=hammer))
```

- [ ] **Step 5: `_fill_voice` 수정 — hammer 적용**

단일음 분기에서 velocity 적용 바로 다음에 추가:

```python
            if ev.hammer:
                gnote.effect.hammer = True
```

화음 분기에서도 velocity 적용 바로 다음에 추가:

```python
                    gnote = Note(beat=beat)
                    if ev.velocity is not None:
                        gnote.velocity = ev.velocity
                    if ev.hammer:
                        gnote.effect.hammer = True
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_slur_marks_continuation_notes_as_hammer_on -v
```
Expected: `PASSED`

- [ ] **Step 7: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 71 passed, 2 deselected

- [ ] **Step 8: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 슬러(Slur) 후속음을 hammer-on으로 표현"
```

---

### Task 5: 아티큘레이션(Articulation) 추출 + 적용

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: Task 1의 `NoteEvent.articulations: List[str]`
- Produces:
  - 모듈 상수 `_ARTICULATION_MAP: Dict[type, str]`
  - `_extract_events`에서 `articulations` 채움
  - `_fill_voice`에서 단일음+화음 모두 `NoteEffect` 적용

- [ ] **Step 1: 테스트 픽스처 + 테스트 작성**

```python
_ARTICULATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><staccato/></articulations></notations>
      </note>
      <note>
        <pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><accent/></articulations></notations>
      </note>
      <note>
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><strong-accent/></articulations></notations>
      </note>
      <note>
        <pitch><step>F</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><tenuto/></articulations></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_articulations_applied_to_note_effect(tmp_path):
    """스타카토/악센트/강악센트/테누토가 각각 NoteEffect에 정확히 매핑돼야 한다."""
    xml_path = tmp_path / "articulation.musicxml"
    xml_path.write_text(_ARTICULATION_XML, encoding="utf-8")
    out = str(tmp_path / "articulation.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 4
    assert beats[0].notes[0].effect.staccato is True, "C5: staccato"
    assert beats[1].notes[0].effect.accentuatedNote is True, "D5: accent"
    assert beats[2].notes[0].effect.heavyAccentuatedNote is True, "E5: strong-accent"
    assert beats[3].notes[0].effect.letRing is True, "F5: tenuto"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_articulations_applied_to_note_effect -v
```
Expected: `FAILED`

- [ ] **Step 3: import + 상수 추가**

`app/pipeline/musicxml_to_gp.py` 상단 import 블록에 `articulations as m21art` 추가:

```python
from music21 import (converter, note as m21note, chord as m21chord,
                     stream as m21stream, spanner as m21spanner,
                     articulations as m21art)
```

`_DYNAMIC_VELOCITY` 바로 아래에 추가:

```python
_ARTICULATION_MAP: Dict[type, str] = {
    m21art.Staccato:     'staccato',
    m21art.Accent:       'accent',
    m21art.StrongAccent: 'strong-accent',
    m21art.Tenuto:       'tenuto',
}
```

- [ ] **Step 4: `_extract_events` 수정 — 아티큘레이션 추출**

`hammer = id(n) in slur_continuation_ids` 줄 다음에 추가:

```python
        arts: List[str] = []
        if hasattr(n, 'articulations'):
            for a in n.articulations:
                key = _ARTICULATION_MAP.get(type(a))
                if key:
                    arts.append(key)
```

기존 `events.append(...)` 에 `articulations=arts, hammer=hammer` 추가:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied,
                                tuplet=tuplet, velocity=current_velocity,
                                hammer=hammer, articulations=arts))
```

- [ ] **Step 5: `_fill_voice` 수정 — 아티큘레이션 적용 헬퍼 함수 작성**

`_is_tied` 함수 바로 위에 새 함수 추가:

```python
def _apply_articulations(gnote: Note, articulations: List[str]) -> None:
    """아티큘레이션 리스트를 GP5 NoteEffect에 적용한다."""
    for art in articulations:
        if art == 'staccato':
            gnote.effect.staccato = True
        elif art == 'accent':
            gnote.effect.accentuatedNote = True
        elif art == 'strong-accent':
            gnote.effect.heavyAccentuatedNote = True
        elif art == 'tenuto':
            gnote.effect.letRing = True
```

단일음 분기에서 hammer 적용 다음에 추가:
```python
            _apply_articulations(gnote, ev.articulations)
```

화음 분기에서도 hammer 적용 다음에 추가:
```python
                    _apply_articulations(gnote, ev.articulations)
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_articulations_applied_to_note_effect -v
```
Expected: `PASSED`

- [ ] **Step 7: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 72 passed, 2 deselected

- [ ] **Step 8: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 아티큘레이션(staccato/accent/strong-accent/tenuto) GP5 NoteEffect로 변환"
```

---

### Task 6: 그레이스노트(Grace Note) 추출 + 적용

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: Task 1의 `NoteEvent.grace: Optional[Tuple[int, str]]`
- Produces: `_extract_events`에서 그레이스노트를 버퍼링해 다음 일반음의 `grace` 필드에 첨부. `_fill_voice`에서 단일음에만 `gnote.effect.grace = gpm.GraceEffect(...)` 적용.

- [ ] **Step 1: 테스트 픽스처 + 테스트 작성**

```python
_GRACE_NOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>2</beats><beat-type>2</beat-type></time>
      </attributes>
      <!-- 오름 꾸밈음: F5(적힌) → G5(적힌). 소리는 F4→G4(각각 -1옥타브). F4<G4이므로 hammer -->
      <note>
        <grace slash="yes"/>
        <pitch><step>F</step><octave>5</octave></pitch>
        <type>eighth</type>
        <stem>up</stem>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>half</type>
      </note>
      <!-- 내림 꾸밈음: A5(적힌) → G5(적힌). 소리는 A4→G4. A4>G4이므로 slide -->
      <note>
        <grace slash="yes"/>
        <pitch><step>A</step><octave>5</octave></pitch>
        <type>eighth</type>
        <stem>up</stem>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>half</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_grace_notes_set_hammer_or_slide_transition(tmp_path):
    """오름 꾸밈음은 hammer, 내림 꾸밈음은 slide transition이어야 한다.

    적힌 음에 -1옥타브 보정: F5→F4(MIDI65), G5→G4(MIDI67), A5→A4(MIDI69).
    F4(65) < G4(67) → hammer. A4(69) > G4(67) → slide.
    """
    xml_path = tmp_path / "grace.musicxml"
    xml_path.write_text(_GRACE_NOTE_XML, encoding="utf-8")
    out = str(tmp_path / "grace.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2

    grace0 = beats[0].notes[0].effect.grace
    assert grace0 is not None, "첫 번째 음(G4)에 꾸밈음이 있어야 함"
    assert grace0.transition == guitarpro.GraceEffectTransition.hammer, "오름→hammer"

    grace1 = beats[1].notes[0].effect.grace
    assert grace1 is not None, "두 번째 음(G4)에 꾸밈음이 있어야 함"
    assert grace1.transition == guitarpro.GraceEffectTransition.slide, "내림→slide"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_grace_notes_set_hammer_or_slide_transition -v
```
Expected: `FAILED`

- [ ] **Step 3: `_extract_events` 수정 — 그레이스노트 버퍼링**

`_extract_events` 함수 시작부에서 `slur_continuation_ids = ...` 블록 다음에 추가:

```python
    pending_grace: Optional[Tuple[int, str]] = None
```

그리고 `for n in stream_like.notesAndRests:` 루프의 `ql = float(...)` 줄 다음, `if isinstance(n, m21note.Rest):` 줄 바로 위에 추가:

```python
        # 그레이스노트는 NoteEvent로 만들지 않고, 다음 일반음에 첨부한다.
        if isinstance(n, m21note.Note) and n.duration.isGrace:
            grace_midi = n.pitch.midi + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
            pending_grace = (grace_midi, 'grace_pending')
            continue
```

`if isinstance(n, m21note.Rest):` 블록 안에서 `events.append(...)` 바로 위에 추가:

```python
            pending_grace = None  # 쉼표를 만나면 꾸밈음 버퍼 초기화
```

음표 처리 부분(rest/grace 처리 이후)에서 `arts` 계산 다음, `events.append(...)` 바로 위에 추가:

```python
        # 직전에 버퍼링된 그레이스노트가 있으면 transition 결정 후 첨부
        grace: Optional[Tuple[int, str]] = None
        if pending_grace is not None:
            grace_midi, _ = pending_grace
            main_midi = pitches[0] if pitches else 0
            transition = 'hammer' if grace_midi < main_midi else 'slide'
            grace = (grace_midi, transition)
            pending_grace = None
```

기존 `events.append(...)` 에 `grace=grace` 추가:
```python
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied,
                                tuplet=tuplet, velocity=current_velocity,
                                hammer=hammer, articulations=arts, grace=grace))
```

- [ ] **Step 4: `_fill_voice` 수정 — 그레이스노트 적용**

단일음 분기에서 `_apply_articulations(gnote, ev.articulations)` 다음에 추가:

```python
            if ev.grace is not None and len(ev.pitches) == 1:
                grace_midi, transition_name = ev.grace
                sf = _midi_to_string_fret(grace_midi, strings)
                if sf is not None:
                    _, fret = sf
                    trans = (
                        gpm.GraceEffectTransition.hammer
                        if transition_name == 'hammer'
                        else gpm.GraceEffectTransition.slide
                    )
                    gnote.effect.grace = gpm.GraceEffect(
                        duration=32, fret=fret, transition=trans
                    )
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
python -m pytest tests/test_musicxml_to_gp.py::test_grace_notes_set_hammer_or_slide_transition -v
```
Expected: `PASSED`

- [ ] **Step 6: 전체 회귀 테스트**

```bash
python -m pytest -v
```
Expected: 73 passed, 2 deselected

- [ ] **Step 7: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 그레이스노트를 GP5 GraceEffect(hammer/slide)로 변환"
```

---

### Task 7: 모듈 docstring 갱신 + 최종 회귀 + 실제 곡 검증

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (docstring만)

**Interfaces:**
- Consumes: 없음 (문서만)
- Produces: 없음

- [ ] **Step 1: 모듈 docstring 수정**

`app/pipeline/musicxml_to_gp.py` 상단 docstring의 "설계 결정:" 목록에 다음 항목 추가:

기존 `- 매핑 불가 박자: ...` 줄 다음에:

```
- 잇단음(tuplet): music21 duration.tuplets에서 추출. GP5 지원 잇단음(3:2,5:4,6:4,
  7:4,9:8,10:8,11:8,12:8,13:8)이면 beat.duration.tuplet에 Tuplet(enters,times) 적용.
  base_ql = ql * enters / times 로 base 박자값을 구해 _ql_to_gp_duration에 전달.
- 다이나믹(dynamics): 스트림에서 music21 Dynamic 객체를 offset 기준 carry-forward
  적용. Note.velocity에 매핑(ppp=15 ~ fff=127). _build_velocity_map 참고.
- 슬러(slur): Slur spanner의 첫 번째 음은 일반 발음, 이후 음들은
  NoteEffect.hammer=True로 표현(GP5에 slur 개념 없음).
- 아티큘레이션: Staccato→staccato, Accent→accentuatedNote,
  StrongAccent→heavyAccentuatedNote, Tenuto→letRing.
- 페르마타: GP5에 직접 대응 없음 → 무시.
- 그레이스노트: 일반음 앞에 오는 grace note를 GraceEffect(duration=32)로 변환.
  오름 방향이면 transition=hammer, 내림이면 slide. 화음에는 미적용(GP5 한계).
```

- [ ] **Step 2: 전체 테스트 최종 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate
python -m pytest -v
```
Expected: 73 passed, 2 deselected

- [ ] **Step 3: 실제 곡 수동 검증**

실제 테스트곡(jobs/bac6d6a8ad54429d9cc4f9f853be0f09/xml/input.mxl)으로 변환 후 확인:

```bash
python3 - <<'EOF'
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
import guitarpro

musicxml_to_gp5("jobs/bac6d6a8ad54429d9cc4f9f853be0f09/xml/input.mxl", "/tmp/notation_check.gp5")
song = guitarpro.parse("/tmp/notation_check.gp5")
track = song.tracks[0]

# 잇단음 있는 비트 수
tuplet_beats = sum(
    1 for m in track.measures
    for v in m.voices
    for b in v.beats
    if b.duration.tuplet.enters != 1
)
# 비기본 velocity 음표 수
velocity_notes = sum(
    1 for m in track.measures
    for v in m.voices
    for b in v.beats
    for n in b.notes
    if n.velocity != 95
)
# hammer-on 음표 수
hammer_notes = sum(
    1 for m in track.measures
    for v in m.voices
    for b in v.beats
    for n in b.notes
    if n.effect.hammer
)
# staccato 음표 수
staccato_notes = sum(
    1 for m in track.measures
    for v in m.voices
    for b in v.beats
    for n in b.notes
    if n.effect.staccato
)
print(f"잇단음 비트: {tuplet_beats}  (실제 곡: 18개 예상)")
print(f"비기본 velocity 음표: {velocity_notes}  (실제 곡: 다이나믹 10개로 여러 음에 적용)")
print(f"hammer-on 음표: {hammer_notes}  (실제 곡: 슬러 1개)")
print(f"staccato 음표: {staccato_notes}  (실제 곡: 61개 아티큘레이션 중 staccato)")
EOF
```
Expected: 각 항목이 0보다 큰 값.

- [ ] **Step 4: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py
git commit -m "docs: 음악 기호 변환 기능 모듈 docstring에 반영"
```

---

## Self-Review 결과

**스펙 커버리지:**
- 잇단음 → Task 2 ✓
- 다이나믹 → Task 3 ✓
- 슬러 → Task 4 ✓
- 아티큘레이션(4종) → Task 5 ✓
- 페르마타 무시 → 별도 태스크 없음(코드 변경 없음) ✓
- 그레이스노트 → Task 6 ✓
- 기존 회귀 없음 → 모든 태스크마다 전체 테스트 실행 ✓

**플레이스홀더 없음**: 모든 스텝에 완전한 코드 블록 포함.

**타입 일관성:**
- `NoteEvent.tuplet: Optional[Tuple[int, int]]` — Task 1 정의, Tasks 2·6에서 사용 ✓
- `NoteEvent.velocity: Optional[int]` — Task 1 정의, Task 3에서 사용 ✓
- `NoteEvent.hammer: bool` — Task 1 정의, Task 4에서 사용 ✓
- `NoteEvent.articulations: List[str]` — Task 1 정의, Task 5에서 사용 ✓
- `NoteEvent.grace: Optional[Tuple[int, str]]` — Task 1 정의, Task 6에서 사용 ✓
- `_apply_articulations(gnote: Note, articulations: List[str])` — Task 5에서 정의, 사용 ✓
- `_build_velocity_map(stream_like) -> Dict[float, int]` — Task 3에서 정의, 사용 ✓
- `_SUPPORTED_TUPLETS: frozenset` — Task 2에서 정의, Task 2에서만 사용 ✓
