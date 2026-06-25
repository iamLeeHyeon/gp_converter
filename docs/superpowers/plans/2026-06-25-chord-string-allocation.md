# 화음(다음 동시발음) GP5 변환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MusicXML 화음(Chord)의 모든 구성음을 GP5 한 Beat 안에 서로 다른 현/프렛으로 동시발음 표현한다(지금은 최고음 1개만 쓰고 나머지를 버림).

**Architecture:** `NoteEvent.midi: Optional[int]`를 `NoteEvent.pitches: List[int]`로 바꿔 단일음/화음/쉼표를 길이로 구분한다. 화음(len>=2)은 새 함수 `_assign_chord_strings`로 그리디+fallback 배정을 받아 `_fill_voice`에서 한 Beat에 여러 Note로 채운다. 단일음/쉼표 경로는 그대로 둔다.

**Tech Stack:** Python, music21(MusicXML 파싱), PyGuitarPro(`guitarpro`, GP5 작성/검증), pytest.

## Global Constraints

- 스펙 문서: `docs/superpowers/specs/2026-06-25-chord-string-allocation-design.md` (위반 시 스펙이 우선).
- 표준 기타 튜닝: `_STANDARD_STRINGS = [(1,64),(2,59),(3,55),(4,50),(5,45),(6,40)]` (이미 존재, 안 바꿈).
- 현당 유효 프렛 범위: 0~24.
- 한 Beat 안에서 같은 현을 두 음이 동시에 못 쓴다.
- 화음 처리 순서: MIDI 내림차순(높은음 먼저).
- 배정 실패(들어갈 현 없음)는 그 음만 스킵 + 경고 로그, 화음 나머지는 살린다.
- 화음 이벤트는 tab_hints를 항상 무시한다(힌트 1개로 다중음 표현 불가).
- 이 작업과 무관한 기존 동작(쉼표, 이음줄, 마디 그룹화, 유령 쉼표 제거, 조표/박자 전파, -12 옥타브 보정)은 절대 건드리지 않는다 — 매 태스크 끝에 전체 테스트(`pytest`)가 회귀 없이 통과해야 한다.

---

### Task 1: `NoteEvent.midi` → `NoteEvent.pitches` 리팩터 (동작 변경 없음)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (`NoteEvent` 클래스, `_extract_events`, `_fill_voice`)
- Test: `tests/test_musicxml_to_gp.py` (`test_out_of_range_note_is_logged_and_skipped`)

**Interfaces:**
- Consumes: 없음(기존 코드 리네임).
- Produces: `NoteEvent.pitches: List[int]` — 단일음은 길이1, 쉼표는 빈 리스트. (이후 모든 태스크가 이 필드명을 씀. 화음의 다중 pitches는 Task 5에서 채움 — 이 태스크에서는 chord도 여전히 `[max_midi]` 한 개짜리 리스트로만 채운다.)

이 태스크는 **순수 리팩터**다. `_extract_events`가 만드는 `pitches` 값은 지금과 동일하게 "단일음은 그 음, 화음은 최고음"이고 길이만 항상 1(또는 쉼표는 0)이 되도록 바꾼다. 동작이 하나도 안 바뀌므로 기존 테스트가 전부 그대로 통과해야 한다.

- [ ] **Step 1: `NoteEvent` 클래스 수정**

`app/pipeline/musicxml_to_gp.py`에서 다음을 찾아:

```python
@dataclass
class NoteEvent:
    """한 음표(또는 화음 최고음)의 (음높이, 길이, 이음줄 연속 여부).

    쉼표면 is_rest=True이고 midi는 None이다.
    """

    midi: Optional[int]
    ql: float
    tied: bool = False  # True면 직전 음에서 이어지는 연속음(NoteType.tie)
    is_rest: bool = False
```

다음으로 바꾼다:

```python
@dataclass
class NoteEvent:
    """한 음표(또는 화음)의 (음높이 목록, 길이, 이음줄 연속 여부).

    pitches는 MIDI 내림차순(높은음 먼저) 리스트다. 단일음은 길이 1,
    화음은 길이 2 이상, 쉼표(is_rest=True)는 빈 리스트다.
    """

    pitches: List[int]
    ql: float
    tied: bool = False  # True면 직전 음에서 이어지는 연속음(NoteType.tie)
    is_rest: bool = False
```

- [ ] **Step 2: `_extract_events` 수정**

다음을 찾아:

```python
def _extract_events(stream_like) -> List[NoteEvent]:
    """한 보이스(또는 단일 보이스 마디)에서 음표/쉼표 이벤트 목록을 뽑는다."""
    events: List[NoteEvent] = []
    for n in stream_like.notesAndRests:
        ql = float(n.duration.quarterLength)
        if isinstance(n, m21note.Rest):
            events.append(NoteEvent(midi=None, ql=ql, is_rest=True))
            continue
        tied = n.tie is not None and n.tie.type in ("continue", "stop")
        if isinstance(n, m21chord.Chord):
            midi = max(p.midi for p in n.pitches)
        else:
            midi = n.pitch.midi
        midi += _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
        events.append(NoteEvent(midi, ql, tied))
    return events
```

다음으로 바꾼다(이 단계에서는 화음도 `[최고음]` 한 개짜리 리스트 — Task 5에서 전체 화음으로 확장):

```python
def _extract_events(stream_like) -> List[NoteEvent]:
    """한 보이스(또는 단일 보이스 마디)에서 음표/쉼표 이벤트 목록을 뽑는다."""
    events: List[NoteEvent] = []
    for n in stream_like.notesAndRests:
        ql = float(n.duration.quarterLength)
        if isinstance(n, m21note.Rest):
            events.append(NoteEvent(pitches=[], ql=ql, is_rest=True))
            continue
        tied = n.tie is not None and n.tie.type in ("continue", "stop")
        if isinstance(n, m21chord.Chord):
            midi = max(p.midi for p in n.pitches)
        else:
            midi = n.pitch.midi
        midi += _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
        events.append(NoteEvent(pitches=[midi], ql=ql, tied=tied))
    return events
```

- [ ] **Step 3: `_fill_voice` 수정**

다음을 찾아(`_build_song` 안의 클로저):

```python
            hint = _next_hint() if use_hints else None
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(ev.midi, strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.midi)
                    continue
                snum, fret = sf
```

다음으로 바꾼다:

```python
            hint = _next_hint() if use_hints else None
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(ev.pitches[0], strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.pitches[0])
                    continue
                snum, fret = sf
```

- [ ] **Step 4: 기존 테스트의 `NoteEvent(midi=...)` 호출 수정**

`tests/test_musicxml_to_gp.py`에서 다음을 찾아:

```python
            voices=[[NoteEvent(midi=30, ql=1.0, tied=False), NoteEvent(midi=60, ql=1.0, tied=False)]],
```

다음으로 바꾼다:

```python
            voices=[[NoteEvent(pitches=[30], ql=1.0, tied=False), NoteEvent(pitches=[60], ql=1.0, tied=False)]],
```

- [ ] **Step 5: 전체 테스트 실행 — 회귀 없이 전부 통과해야 함**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest -v`
Expected: 모든 테스트 PASS (이 태스크 직전과 같은 개수, 같은 결과 — 동작 변경 없는 순수 리팩터이므로).

- [ ] **Step 6: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "refactor: NoteEvent.midi를 pitches 리스트로 바꿈(화음 다중음 준비)"
```

---

### Task 2: `_assign_chord_strings` — 기본 배정(충돌 없음)

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_STANDARD_STRINGS: List[Tuple[int,int]]` (기존, 안 바뀜).
- Produces: `_assign_chord_strings(pitches: List[int], strings: List[Tuple[int,int]]) -> List[Optional[Tuple[int,int]]]` — 입력 `pitches`와 같은 길이의 리스트를 반환한다. 각 자리는 `(현번호,프렛)` 또는 `None`(배정 실패). 이후 Task 3~5가 이 시그니처를 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py` 맨 위 import에 `_assign_chord_strings`를 추가:

```python
from app.pipeline.musicxml_to_gp import (
    musicxml_to_gp5,
    GpConvertError,
    _build_song,
    _assign_chord_strings,
    MeasureData,
    NoteEvent,
)
```

파일 끝에 다음 테스트를 추가한다:

```python
def test_assign_chord_strings_no_conflict():
    """충돌 없는 화음은 각 음마다 가장 낮은 프렛의 현을 받아야 한다."""
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    # E5(65) C5(60) A4(57) F4(53) — MIDI 내림차순
    result = _assign_chord_strings([65, 60, 57, 53], _STANDARD_STRINGS)

    assert result == [(1, 1), (2, 1), (3, 2), (4, 3)]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest tests/test_musicxml_to_gp.py::test_assign_chord_strings_no_conflict -v`
Expected: FAIL — `ImportError: cannot import name '_assign_chord_strings'`

- [ ] **Step 3: 최소 구현**

`app/pipeline/musicxml_to_gp.py`에서 `_midi_to_string_fret` 함수 바로 뒤(그리고 `_ql_to_gp_duration` 앞)에 추가:

```python
def _assign_chord_strings(
    pitches: List[int],
    strings: List[Tuple[int, int]],
) -> List[Optional[Tuple[int, int]]]:
    """화음의 각 음에 (현 번호, 프렛)을 배정한다.

    pitches는 MIDI 내림차순(높은음 먼저)이어야 한다. 높은음부터 처리하며,
    각 음마다 후보 현을 프렛 낮은순으로 정렬해두고 그리디하게 비어있는 첫
    현을 잡는다(1순위가 이미 다른 음에 쓰였으면 다음 후보로 넘어간다).
    모든 후보 현이 막히면 그 음은 None을 반환한다(화음 나머지는 계속 처리).
    """
    used_strings: set = set()
    result: List[Optional[Tuple[int, int]]] = []
    for midi in pitches:
        candidates = sorted(
            (midi - sval, snum) for snum, sval in strings if 0 <= midi - sval <= 24
        )
        placed = None
        for fret, snum in candidates:
            if snum not in used_strings:
                used_strings.add(snum)
                placed = (snum, fret)
                break
        result.append(placed)
    return result
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_musicxml_to_gp.py::test_assign_chord_strings_no_conflict -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 화음 현 배정 함수 _assign_chord_strings 추가(기본 케이스)"
```

---

### Task 3: `_assign_chord_strings` — 충돌 시 fallback

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (이미 Task 2에서 만든 함수 — 이 태스크는 새 테스트로 fallback 동작을 확정하는 것. 구현은 Task 2의 그리디 루프가 이미 fallback을 포함하므로 코드 변경 없이 테스트만 추가해도 통과해야 한다.)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_assign_chord_strings(pitches, strings)` (Task 2에서 정의).
- Produces: 없음(회귀 테스트 추가).

- [ ] **Step 1: 실패 여부 확인을 위한 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가:

```python
def test_assign_chord_strings_falls_back_when_first_choice_taken():
    """1순위 현이 이미 다른 음에 쓰였으면 그 다음 후보 현으로 넘어가야 한다.

    MIDI 65(E5)와 64(E4 옥타브 위... 실제로는 두 음 다 string1을 1순위로
    원하는 상황): 65는 string1 fret1을, 64는 string1 fret0을 1순위로
    원한다. 65가 먼저(내림차순) string1을 차지하면 64는 string2 fret5로
    밀려나야 한다.
    """
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    result = _assign_chord_strings([65, 64], _STANDARD_STRINGS)

    assert result == [(1, 1), (2, 5)]
```

- [ ] **Step 2: 테스트 실행 — 이미 통과해야 함(Task 2 구현이 fallback 포함)**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest tests/test_musicxml_to_gp.py::test_assign_chord_strings_falls_back_when_first_choice_taken -v`
Expected: PASS (구현 변경 불필요 — 이미 그리디 루프가 `if snum not in used_strings`로 다음 후보를 시도하므로). PASS가 아니라 FAIL이면 Task 2의 `_assign_chord_strings` 구현을 다시 확인한다.

- [ ] **Step 3: 커밋**

```bash
git add tests/test_musicxml_to_gp.py
git commit -m "test: 화음 현 배정 충돌 fallback 케이스 회귀 테스트 추가"
```

---

### Task 4: `_assign_chord_strings` — 배정 불가능한 음만 스킵

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (변경 불필요 예상 — Task 2 구현이 이미 처리)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_assign_chord_strings(pitches, strings)`.
- Produces: 없음.

- [ ] **Step 1: 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가:

```python
def test_assign_chord_strings_skips_unplaceable_note_only():
    """화음 안 한 음이 어떤 현으로도 표현 못 하면 그 음만 None, 나머지는 살아야 한다."""
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    # 100: 모든 현에서 프렛이 24 초과(범위 밖) / 64: 정상(string1 fret0)
    result = _assign_chord_strings([100, 64], _STANDARD_STRINGS)

    assert result == [None, (1, 0)]
```

- [ ] **Step 2: 테스트 실행**

Run: `python3 -m pytest tests/test_musicxml_to_gp.py::test_assign_chord_strings_skips_unplaceable_note_only -v`
Expected: PASS (Task 2의 `candidates`가 빈 리스트면 `placed=None`으로 남으므로 이미 처리됨). FAIL이면 `_assign_chord_strings` 구현을 점검한다.

- [ ] **Step 3: 커밋**

```bash
git add tests/test_musicxml_to_gp.py
git commit -m "test: 화음 현 배정 불가 음 스킵 케이스 회귀 테스트 추가"
```

---

### Task 5: 화음 전체 음 추출 + `_fill_voice` 화음 분기 — end-to-end 연결

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (`_extract_events`, `_fill_voice`)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_assign_chord_strings` (Task 2), `NoteEvent.pitches` (Task 1).
- Produces: `_extract_events`가 화음을 `pitches`에 MIDI 내림차순 전체 목록으로 채움. `_fill_voice`가 `len(ev.pitches) >= 2`일 때 화음 분기를 탄다 — 이후 Task 6(tab_hints)이 이 분기를 참조한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py`에 다음 fixture와 테스트를 추가한다:

```python
_CHORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>A</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>F</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_all_notes_placed_on_distinct_strings(tmp_path):
    """화음의 모든 음이 한 비트 안에, 서로 다른 현에 살아있어야 한다(최고음만 X)."""
    xml_path = tmp_path / "chord.musicxml"
    xml_path.write_text(_CHORD_XML, encoding="utf-8")
    out = str(tmp_path / "chord.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}

    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]
    assert len(beats) == 1, f"화음은 비트 1개여야 하는데 {len(beats)}개"

    notes = beats[0].notes
    assert len(notes) == 4, f"화음 음 4개가 다 살아있어야 하는데 {len(notes)}개"

    strings_used = [n.string for n in notes]
    assert len(strings_used) == len(set(strings_used)), "같은 현을 두 음이 동시에 씀"

    # 적힌 E5,C5,A4,F4(76,72,69,65) -1옥타브 = 64,60,57,53
    actual_midi = sorted(string_val[n.string] + n.value for n in notes)
    assert actual_midi == [53, 57, 60, 64]
```

`guitarpro`는 이미 파일 상단에 import돼 있다(`import guitarpro`).

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest tests/test_musicxml_to_gp.py::test_chord_all_notes_placed_on_distinct_strings -v`
Expected: FAIL — `assert len(notes) == 4` 자리에서 `1 != 4` (지금은 최고음 1개만 들어가므로).

- [ ] **Step 3: `_extract_events`가 화음 전체 음을 담도록 수정**

다음을 찾아(Task 1에서 만든 버전):

```python
        tied = n.tie is not None and n.tie.type in ("continue", "stop")
        if isinstance(n, m21chord.Chord):
            midi = max(p.midi for p in n.pitches)
        else:
            midi = n.pitch.midi
        midi += _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
        events.append(NoteEvent(pitches=[midi], ql=ql, tied=tied))
```

다음으로 바꾼다:

```python
        tied = n.tie is not None and n.tie.type in ("continue", "stop")
        if isinstance(n, m21chord.Chord):
            midis = sorted((p.midi for p in n.pitches), reverse=True)
        else:
            midis = [n.pitch.midi]
        pitches = [m + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET for m in midis]
        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied))
```

- [ ] **Step 4: `_fill_voice`에 화음 분기 추가**

다음을 찾아(Task 1에서 만든 버전):

```python
            hint = _next_hint() if use_hints else None
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(ev.pitches[0], strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.pitches[0])
                    continue
                snum, fret = sf

            beat = Beat(voice=voice)
            beat.status = BeatStatus.normal
            beat.duration.value = gp_val
            beat.duration.isDotted = is_dotted

            gnote = Note(beat=beat)
            gnote.value = fret
            gnote.string = snum
            gnote.type = NoteType.tie if ev.tied else NoteType.normal
            beat.notes = [gnote]
            beats.append(beat)
```

다음으로 바꾼다:

```python
            if len(ev.pitches) >= 2:
                # 화음: tab_hints는 무시(힌트 1개로 다중음 표현 불가)하고
                # 항상 _assign_chord_strings로 배정한다.
                placements = _assign_chord_strings(ev.pitches, strings)
                beat = Beat(voice=voice)
                beat.status = BeatStatus.normal
                beat.duration.value = gp_val
                beat.duration.isDotted = is_dotted

                gnotes = []
                for placement in placements:
                    if placement is None:
                        logger.warning("화음 음 일부가 어떤 현으로도 표현할 수 없어 건너뜀")
                        continue
                    snum, fret = placement
                    gnote = Note(beat=beat)
                    gnote.value = fret
                    gnote.string = snum
                    gnote.type = NoteType.tie if ev.tied else NoteType.normal
                    gnotes.append(gnote)
                beat.notes = gnotes
                beats.append(beat)
                continue

            hint = _next_hint() if use_hints else None
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(ev.pitches[0], strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.pitches[0])
                    continue
                snum, fret = sf

            beat = Beat(voice=voice)
            beat.status = BeatStatus.normal
            beat.duration.value = gp_val
            beat.duration.isDotted = is_dotted

            gnote = Note(beat=beat)
            gnote.value = fret
            gnote.string = snum
            gnote.type = NoteType.tie if ev.tied else NoteType.normal
            beat.notes = [gnote]
            beats.append(beat)
```

주의: 이 블록은 `_fill_voice` 안, `for ev in events:` 루프 안, `if ev.is_rest: ... continue` 블록 바로 다음에 와야 한다(쉼표 처리 이후, 단일음/화음 분기 이전).

- [ ] **Step 5: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_musicxml_to_gp.py::test_chord_all_notes_placed_on_distinct_strings -v`
Expected: PASS

- [ ] **Step 6: 전체 회귀 테스트 실행**

Run: `python3 -m pytest -v`
Expected: 모든 테스트 PASS (단일음/쉼표 경로는 `len(ev.pitches)==1`이라 화음 분기를 안 타므로 영향 없음).

- [ ] **Step 7: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: 화음 모든 음을 GP5에 동시발음으로 표현"
```

---

### Task 6: tab_hints와 화음 공존

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (`_build_song`의 `total_notes` 계산)
- Test: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: `_fill_voice`의 화음 분기(Task 5, 이미 tab_hints 무시함 — `_next_hint()`를 화음 분기에서 호출하지 않으므로 추가 코드 변경 없이 이미 만족).
- Produces: `_build_song`의 `total_notes`가 "쉼표도 화음도 아닌 단일음 이벤트 개수"만 센다 — 이후 다른 태스크 없음(이 계획의 마지막 동작 변경 태스크).

지금 `total_notes` 계산은 다음과 같다(쉼표만 제외, 화음 이벤트는 "1개"로 셈 — 화음이 있으면 tab_hints 길이 매칭이 깨질 수 있다):

```python
    total_notes = sum(
        1 for m in measures_data for ev in m.voices[0] if not ev.is_rest
    )
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가:

```python
_CHORD_PLUS_SINGLE_NOTES_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
      </note>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_tab_hints_apply_only_to_single_note_events_when_chord_present(tmp_path):
    """화음이 섞인 마디에서 tab_hints 개수는 단일음 이벤트 개수만 따져야 한다.

    이 마디는 화음(half, 2음) 1개 + 단일음(quarter) 2개다. tab_hints를
    단일음 2개에 맞춰 주면(화음은 세지 않음) 화음은 휴리스틱으로, 단일음
    2개는 힌트로 그대로 들어가야 한다.
    """
    xml_path = tmp_path / "chord_plus_single.musicxml"
    xml_path.write_text(_CHORD_PLUS_SINGLE_NOTES_XML, encoding="utf-8")
    out = str(tmp_path / "chord_plus_single.gp5")

    # 단일음 2개(C4,D4)에 대한 가짜 힌트 — 휴리스틱이면 다른 값이 나오게 일부러 6번줄로
    fake_hints = [(6, 20), (6, 21)]
    musicxml_to_gp5(str(xml_path), out, tab_hints=fake_hints)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]

    assert len(beats) == 3  # 화음 1비트 + 단일음 2비트
    chord_beat, single1, single2 = beats

    assert len(chord_beat.notes) == 2  # 화음은 힌트 무시, 2음 다 살아있음
    assert (single1.notes[0].string, single1.notes[0].value) == (6, 20)
    assert (single2.notes[0].string, single2.notes[0].value) == (6, 21)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest tests/test_musicxml_to_gp.py::test_tab_hints_apply_only_to_single_note_events_when_chord_present -v`
Expected: FAIL — `total_notes`가 화음을 "1개"로 세서 `len(tab_hints)=2 != total_notes=3`이 되어 tab_hints 전체가 무시되고, `single1.notes[0]`이 `(6,20)`이 아닌 휴리스틱 값이 나옴.

- [ ] **Step 3: `total_notes` 계산 수정**

다음을 찾아:

```python
    total_notes = sum(
        1 for m in measures_data for ev in m.voices[0] if not ev.is_rest
    )
```

다음으로 바꾼다:

```python
    total_notes = sum(
        1 for m in measures_data for ev in m.voices[0]
        if not ev.is_rest and len(ev.pitches) == 1
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_musicxml_to_gp.py::test_tab_hints_apply_only_to_single_note_events_when_chord_present -v`
Expected: PASS

- [ ] **Step 5: 전체 회귀 테스트 실행**

Run: `python3 -m pytest -v`
Expected: 모든 테스트 PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "fix: tab_hints 개수 검증이 화음을 단일음과 혼동하지 않게 수정"
```

---

### Task 7: 모듈 docstring 정리 + 최종 회귀

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py` (파일 맨 위 모듈 docstring, `_collect_notes`의 docstring)

**Interfaces:**
- Consumes: 없음(문서만 수정).
- Produces: 없음.

- [ ] **Step 1: 모듈 docstring 수정**

파일 맨 위 docstring에서 다음 줄을 찾아:

```
- 코드(Chord): 코드에서 가장 높은 음(최대 MIDI 값)만 사용한다. MVP 단순화.
```

다음으로 바꾼다:

```
- 코드(Chord): 모든 구성음을 서로 다른 현/프렛에 동시발음으로 배정한다
  (_assign_chord_strings). 높은음부터 그리디하게 배정하고, 1순위 현이
  막히면 다음 후보로 넘어간다(fallback). 끝까지 못 들어가는 음만 건너뛴다.
```

- [ ] **Step 2: `_collect_notes` docstring 수정**

다음을 찾아:

```
    Chord는 최고음(최대 MIDI) 하나만 사용한다.
```

다음으로 바꾼다:

```
    Chord는 모든 구성음을 MIDI 내림차순으로 pitches에 담는다(현 배정은
    _build_song의 _assign_chord_strings에서 처리).
```

- [ ] **Step 3: 전체 테스트 + 실제 곡 회귀 확인**

Run: `cd /Users/leehyeon/Desktop/projects/gp_converter && source .venv/bin/activate && python3 -m pytest -v`
Expected: 모든 테스트 PASS.

마디100(실제 화음 있는 마디)으로 수동 확인:

Run:
```bash
python3 - <<'EOF'
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
import guitarpro

xml = "jobs/3548f9a458b04ffeaa262dd2977a37d4/xml/input.mxl"
out = "/tmp/chord_check.gp5"
musicxml_to_gp5(xml, out)

song = guitarpro.parse(out)
track = song.tracks[0]
m100 = [m for m in track.measures if m.number == 100][0]
for voice in m100.voices:
    for b in voice.beats:
        print(b.status, [(n.string, n.value) for n in b.notes])
EOF
```
Expected: 화음 비트마다 `notes` 리스트 길이가 1보다 큰 항목이 보여야 한다(예: 4개 음 화음이면 `notes` 4개).

- [ ] **Step 4: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py
git commit -m "docs: 화음 다중음 지원 반영해 모듈 docstring 갱신"
```

---

## Self-Review 결과

- **스펙 커버리지:** 데이터 모델 변경(Task 1), 현 배정 알고리즘(Task 2~4), `_fill_voice` 분기(Task 5), tab_hints 개수 검증(Task 6) — 스펙의 모든 섹션에 대응 태스크 있음. "영향받지 않는 부분"은 각 태스크 끝 전체 회귀 테스트로 보장.
- **플레이스홀더 스캔:** 없음. 모든 단계에 실제 코드/명령 포함.
- **타입 일관성:** `_assign_chord_strings(pitches: List[int], strings: List[Tuple[int,int]]) -> List[Optional[Tuple[int,int]]]` 시그니처를 Task 2~5에서 동일하게 사용. `NoteEvent.pitches: List[int]` 필드명을 Task 1 이후 전부 동일하게 사용.
