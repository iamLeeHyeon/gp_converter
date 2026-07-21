# 다중 파트 → 다중 트랙 변환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MusicXML의 모든 `<part>`를 각각 GP5 `Track`으로 변환한다(기타 듀엣/앙상블 전용). 탭-OMR 경로와 파트 1개짜리 기존 동작은 완전히 그대로 유지한다.

**Architecture:** `app/pipeline/musicxml_to_gp.py`의 표준악보 경로(`_scan_raw_technicals` → `_collect_notes` → `_build_song`)를 파트 파라미터화한다. "곡 전체 공통" 필드(박자표/조표/반복표/direction/템포/메타데이터/악기)는 파트 0에서만 계산해 `song`/`song.measureHeaders`에 반영하고, "트랙별" 필드(음표/이펙트)는 파트마다 독립적으로 추출해 각자의 `Track`에 담는다. `app/pipeline/orchestrator.py`의 탭보표 감지 분기는 수정하지 않는다.

**Tech Stack:** Python, music21, PyGuitarPro(`guitarpro`), pytest.

## Global Constraints

- 모든 트랙은 표준 6현 어쿠스틱 기타 튜닝(EADGBE)과 기본 음색을 쓴다 — 파트별 악기 인식은 하지 않는다.
- 탭보표가 감지된 악보는 지금처럼 `token_texts_to_gp5` 단일트랙 경로를 그대로 탄다 — `app/pipeline/orchestrator.py`는 수정하지 않는다.
- 파트가 1개뿐인 기존 악보는 지금과 완전히 동일한 GP5 결과가 나와야 한다(회귀 없음) — 기존 테스트 스위트 전체가 수정 없이 통과해야 한다(단, `_build_song`의 시그니처 변경으로 직접 호출부 1곳만 예외적으로 고친다 — Task 4).
- 파트 하나를 처리하다 예외가 나면 전체 변환을 실패시킨다(`GpConvertError` 그대로 전파, 부분 성공 없음).
- 모든 커밋 메시지는 한글로 작성하고 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`로 끝낸다.

---

## Task 1: `_scan_raw_technicals`에 `part_index` 파라미터 추가

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:655-729` (`_scan_raw_technicals`)
- Test: `tests/test_musicxml_to_gp.py` (기존 `test_scan_raw_technicals_ignores_other_parts` 테스트 바로 뒤에 추가)

**Interfaces:**
- Consumes: 없음(순수 함수, 기존 `_read_xml_root` 그대로 사용)
- Produces: `_scan_raw_technicals(xml_path: str, part_index: int = 0) -> Dict[Tuple[int, int, int], Dict[str, Optional[float]]]` — Task 2(`_collect_notes`)가 이 시그니처로 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py`의 `test_scan_raw_technicals_ignores_other_parts` 함수(약 1915번째 줄) 바로 뒤에 추가:

```python
def test_scan_raw_technicals_part_index_selects_that_part(tmp_path):
    """part_index로 지정한 파트만 스캔해야 한다 — 다중트랙 변환 시 2번째
    이후 파트의 벤드/팜뮤트도 그 파트 자신의 스캔 결과로 얻을 수 있어야 한다."""
    from app.pipeline.musicxml_to_gp import _scan_raw_technicals

    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
    <score-part id="P2"><part-name>Vocal</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><technical><bend><bend-alter>4</bend-alter></bend></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "multi_part_index.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")

    part0_result = _scan_raw_technicals(str(xml_path), 0)
    part1_result = _scan_raw_technicals(str(xml_path), 1)
    default_result = _scan_raw_technicals(str(xml_path))

    assert part0_result == {}
    assert part1_result == {(1, 0, 0): {"bend": 4.0}}
    assert default_result == part0_result  # 기본값(0)은 기존 동작과 동일해야 함
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_scan_raw_technicals_part_index_selects_that_part -v`
Expected: FAIL — `TypeError: _scan_raw_technicals() takes 1 positional argument but 2 were given`

- [ ] **Step 3: `_scan_raw_technicals` 구현 수정**

`app/pipeline/musicxml_to_gp.py:655-729`을 통째로 아래로 교체:

```python
def _scan_raw_technicals(
    xml_path: str, part_index: int = 0
) -> Dict[Tuple[int, int, int], Dict[str, Optional[float]]]:
    """원본 MusicXML을 병행 파싱해 (마디, 보이스, 순번)별 벤드/팜뮤트/비브라토 표기를 찾는다.

    music21이 <bend>/<palm-mute>/<vibrato>를 파싱하지 않아서 raw XML을 직접 훑는다.
    "bend" 키의 값은 <bend-alter>(반음 수, 없으면 2.0=1음 벤드로 가정) —
    PyGuitarPro의 BendPoint.value도 동일하게 반음 단위라 그대로 옮겨쓸 수 있다.
    "palm_mute"/"vibrato" 키는 값이 의미 없어 None으로 둔다.

    ponytail: 이건 "raw XML과 music21 스트림이 같은 순서로 노트를 센다"는
    가정에 기댄 best-effort 상관관계다. 화음/보이스가 복잡하게 얽히면
    어긋날 수 있음 — 실사용 입력(Audiveris 표준보)에 이 태그 자체가 애초에
    거의 안 나올 걸로 예상해서 감수함. 팜뮤트는 <palm-mute type="start"/">
    경계 음표에만 표시하고 그 사이 음표까지 전파하지 않는다(추가로 단순화).
    쉼표·화음 연속음(<chord/>)·꾸밈음(<grace/>)은 순번에서 제외한다
    (_extract_events가 이들을 건너뛰거나 따로 처리하는 것과 동일하게 유지).

    part_index로 지정한 <part>만 본다(기본값 0=첫 번째 파트) — _collect_notes가
    이 함수를 호출할 때 자신이 처리 중인 파트와 같은 인덱스를 넘겨서, 다른
    파트의 벤드/팜뮤트가 엉뚱한 파트의 같은 위치 음표로 새어 들어가지 않게 한다.
    """
    result: Dict[Tuple[int, int, int], Dict[str, Optional[float]]] = {}
    root = _read_xml_root(xml_path)
    parts = root.findall("part")
    target_part = parts[part_index] if 0 <= part_index < len(parts) else None
    if target_part is not None:
        for measure in target_part.findall("measure"):
            measure_number = int(measure.get("number"))
            notes = measure.findall("note")

            # voice_index는 XML 문서상 등장 순서가 아니라, music21의
            # MusicXML importer(voiceIndices를 set에 모아 sorted()로 Voice를
            # 만드는 방식, xmlToM21.py)와 똑같이 voice id 문자열 정렬 순서로
            # 매겨야 한다 — 안 그러면 2성 마디에서 voice "2"가 문서상 먼저
            # 나올 때(흔한 표기) raw 스캔과 music21의 보이스 순서가 어긋난다.
            voice_texts_seen: Set[str] = set()
            for note in notes:
                if note.find("rest") is not None:
                    continue
                if note.find("chord") is not None:
                    continue
                if note.find("grace") is not None:
                    continue
                voice_texts_seen.add(note.findtext("voice") or "1")
            voice_order = sorted(voice_texts_seen)

            ordinals: Dict[str, int] = {}
            for note in notes:
                if note.find("rest") is not None:
                    continue
                if note.find("chord") is not None:
                    continue
                if note.find("grace") is not None:
                    continue
                voice_text = note.findtext("voice") or "1"
                voice_index = voice_order.index(voice_text)
                ordinal = ordinals.get(voice_text, 0)
                ordinals[voice_text] = ordinal + 1

                marks: Dict[str, Optional[float]] = {}
                technical = note.find("notations/technical")
                if technical is not None:
                    bend_el = technical.find("bend")
                    if bend_el is not None:
                        alter_text = bend_el.findtext("bend-alter")
                        try:
                            marks["bend"] = float(alter_text) if alter_text else 2.0
                        except ValueError:
                            marks["bend"] = 2.0
                    if technical.find("palm-mute") is not None:
                        marks["palm_mute"] = None
                    if technical.find("vibrato") is not None:
                        marks["vibrato"] = None
                if marks:
                    result[(measure_number, voice_index, ordinal)] = marks
    return result
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py -k scan_raw_technicals -v`
Expected: 새 테스트 포함 전부 PASS (기존 4개 + 신규 1개 = 5개).

- [ ] **Step 5: 전체 스위트로 회귀 확인**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 PASS (기존 호출부는 전부 `_scan_raw_technicals(xml_path)` 형태라 `part_index` 기본값 0으로 동작 동일).

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "$(cat <<'EOF'
feat: _scan_raw_technicals에 part_index 파라미터 추가 (다중트랙 준비)

다중 파트→다중 트랙 변환의 1단계. 각 파트를 독립적으로 스캔할 수 있도록
part_index(기본값 0)를 받아 root.findall("part")[part_index]만 스캔하게
바꿨다. 기본값이 기존 첫 파트 스캔과 동일해 호출부 변경 없이 회귀 없음.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_collect_notes`를 파트 파라미터화

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:732-852` (`_collect_notes`)
- Test: `tests/test_musicxml_to_gp.py` (새 테스트 함수 추가, `_scan_raw_technicals` 관련 테스트들 뒤 아무 곳)

**Interfaces:**
- Consumes: `_scan_raw_technicals(xml_path, part_index)` (Task 1에서 완성).
- Produces: `_collect_notes(part, xml_path: str, part_index: int = 0) -> List[MeasureData]` — Task 4(`musicxml_to_gp5`)가 `score.parts`를 순회하며 이 시그니처로 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py` 맨 아래(또는 `_scan_raw_technicals` 테스트 섹션 뒤)에 추가:

```python
def test_collect_notes_takes_explicit_part_and_index(tmp_path):
    """_collect_notes가 score.parts[0] 고정이 아니라 명시적으로 받은 part를
    처리해야 한다 — 다중트랙 변환에서 파트마다 따로 호출할 수 있어야 함."""
    from music21 import converter
    from app.pipeline.musicxml_to_gp import _collect_notes

    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar 1</part-name></score-part>
    <score-part id="P2"><part-name>Guitar 2</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><technical><bend><bend-alter>4</bend-alter></bend></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "two_part_collect.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")

    score = converter.parse(str(xml_path))

    md0 = _collect_notes(score.parts[0], str(xml_path), 0)
    md1 = _collect_notes(score.parts[1], str(xml_path), 1)

    assert md0[0].voices[0][0].pitches == [60]  # C4
    assert md0[0].voices[0][0].bend is None
    assert md1[0].voices[0][0].pitches == [67]  # G4
    assert md1[0].voices[0][0].bend == 4.0  # part_index=1로 스캔한 벤드가 이 파트에만 적용


def test_collect_notes_only_computes_tempo_changes_for_part_zero(tmp_path):
    """곡중간 템포 변화는 곡 전체 개념이라 파트 0에서만 계산해야 한다 —
    다른 파트(part_index != 0)에 독립적인 템포 표기가 있어도 무시해야 함."""
    from music21 import converter
    from app.pipeline.musicxml_to_gp import _collect_notes

    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar 1</part-name></score-part>
    <score-part id="P2"><part-name>Guitar 2</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type>
        <sound tempo="120"/>
      </direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>90</per-minute></metronome></direction-type>
        <sound tempo="90"/>
      </direction>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type>
        <sound tempo="120"/>
      </direction>
      <note><pitch><step>E</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type>
        <sound tempo="60"/>
      </direction>
      <note><pitch><step>F</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "tempo_per_part.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")

    score = converter.parse(str(xml_path))

    md0 = _collect_notes(score.parts[0], str(xml_path), 0)
    md1 = _collect_notes(score.parts[1], str(xml_path), 1)

    tempo_changes0 = [ev.tempo_change for ev in md0[1].voices[0] if ev.tempo_change is not None]
    tempo_changes1 = [ev.tempo_change for ev in md1[1].voices[0] if ev.tempo_change is not None]

    assert tempo_changes0 == [90]  # 파트 0(part_index=0)의 곡중간 템포 변화는 그대로 반영
    assert tempo_changes1 == []    # 파트 1(part_index=1)은 자체 템포 표기가 있어도 무시해야 함
```

(`_build_tempo_changes`를 게이팅 없이 직접 호출해보면 파트 1도 `{<note id>: 60}`을 반환한다는 게 직접 확인됐다 — 즉 이 테스트는 진짜로 "그냥 애초에 템포 변화가 없어서 통과"가 아니라 "있는데 의도적으로 버려서 통과"하는 케이스다.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_collect_notes_takes_explicit_part_and_index tests/test_musicxml_to_gp.py::test_collect_notes_only_computes_tempo_changes_for_part_zero -v`
Expected: FAIL — `TypeError: _collect_notes() takes 2 positional arguments but 3 were given` (현재 `_collect_notes(score, xml_path)`는 `part_index` 인자를 받지 않는다).

- [ ] **Step 3: `_collect_notes` 구현 수정**

`app/pipeline/musicxml_to_gp.py:732-761`의 시그니처와 앞부분을 교체 (docstring과 `part = score.parts[0]` 줄, `_scan_raw_technicals` 호출부 3곳 수정):

```python
def _collect_notes(part, xml_path: str, part_index: int = 0) -> List[MeasureData]:
    """지정된 파트에서 마디 단위 (박자, 조표, 보이스별 음표/쉼표) 목록을 추출한다.

    박자/조표는 명시된 마디가 없으면 이전 마디 값을 이어받는다(carry-forward).
    Chord는 모든 구성음을 MIDI 내림차순으로 pitches에 담는다(현 배정은
    _build_song의 _assign_chord_strings에서 처리).
    이음줄로 이어지는(continue/stop) 음은 음별로 tied=True로 표시한다(화음은
    구성음마다 따로 판정 — _is_tied/_extract_events 참고).
    쉼표도 길이가 있는 이벤트로 포함한다(건너뛰면 그 뒤 음표들이 마디 박자
    총합을 못 채워 GP5가 깨진다).
    한 마디에 보이스가 여러 개면(예: <backup>으로 만든 2성) GP5가 지원하는
    최대 2개까지만 voices에 담는다(3개 이상이면 나머지는 버림).

    part_index는 이 part가 원본 <part-list>에서 몇 번째인지(0-based) — raw XML
    스캔(_scan_raw_technicals)이 같은 인덱스로 이 파트만 보게 맞추는 용도다.
    다중 파트 변환에서는 파트마다 이 함수를 따로 호출한다.
    """
    try:
        raw_technicals = _scan_raw_technicals(xml_path, part_index)
    except Exception:
        logger.warning("벤드/팜뮤트/비브라토 raw XML 스캔 실패 — 해당 이펙트 없이 계속 진행", exc_info=True)
        raw_technicals = {}
    try:
        hairpin_velocities = _build_hairpin_velocities(part)
    except Exception:
        logger.warning("크레센도/디미누엔도 보간 실패 — 해당 이펙트 없이 계속 진행", exc_info=True)
        hairpin_velocities = {}
    try:
        # 곡중간 템포 변화는 "곡 전체" 개념이다(트랙마다 재생 속도가 따로
        # 달라질 수 없다) — 파트 0에서만 계산하고, 다른 파트에서는 계산 자체를
        # 건너뛴다(설계 문서 "코드 변경 지점" 3번). 안 그러면 2번째 이후
        # 파트에 우연히 붙은 템포 표기가 그 파트의 트랙에 곡 전체 재생 속도를
        # 바꾸는 MixTableChange로 잘못 붙는다.
        tempo_changes = _build_tempo_changes(part) if part_index == 0 else {}
    except Exception:
        logger.warning("곡중간 템포 변화 추출 실패 — 해당 이펙트 없이 계속 진행", exc_info=True)
        tempo_changes = {}
    measures = list(part.getElementsByClass(m21stream.Measure))

    repeat_alt_by_measure: Dict[int, int] = {}
    for rb in part.recurse().getElementsByClass(m21spanner.RepeatBracket):
        bitmask = 0
        for n in rb.getNumberList():
            bitmask |= 1 << (n - 1)
        for spanned in rb.getSpannedElements():
            repeat_alt_by_measure[spanned.number] = (
                repeat_alt_by_measure.get(spanned.number, 0) | bitmask
            )
```

정리하면 원본 대비 바뀐 부분은 다섯 군데다: (1) 시그니처 `(score, xml_path)` → `(part, xml_path, part_index=0)`, (2) 첫 줄의 `part = score.parts[0]` 삭제(이제 파라미터로 받음), (3) `_scan_raw_technicals(xml_path)` → `_scan_raw_technicals(xml_path, part_index)`, (4) `score.recurse()` → `part.recurse()`(RepeatBracket이 이제 이 파트 안에서만 검색됨 — 곡 전체가 아니라 파트 0만 반영한다는 설계와 일치), (5) `tempo_changes`를 `part_index == 0`일 때만 계산(곡중간 템포 변화는 곡 전체 개념이라 다른 파트에서 계산한 결과는 버림). 이 함수의 나머지 본문(762번째 줄 이후 `_collect_notes`의 for-loop 전체)은 `score`/`part`를 참조하지 않으므로 그대로 둔다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_collect_notes_takes_explicit_part_and_index tests/test_musicxml_to_gp.py::test_collect_notes_only_computes_tempo_changes_for_part_zero -v`
Expected: PASS

- [ ] **Step 5: 전체 스위트로 회귀 확인**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: FAIL — `musicxml_to_gp5`가 아직 `_collect_notes(score, xml_path)`(구 시그니처)로 호출 중이라 관련 테스트들이 깨진다. **이건 예상된 실패다** — Task 4에서 호출부를 고치기 전까지는 `musicxml_to_gp5`를 쓰는 모든 테스트가 깨진 채로 둔다(Task 2와 Task 4는 반드시 연속으로 진행). 여기서는 새로 추가한 `test_collect_notes_takes_explicit_part_and_index`만 통과하는지 확인하고 다음 태스크로 넘어간다.

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "$(cat <<'EOF'
feat: _collect_notes를 파트 파라미터화 (다중트랙 준비)

다중 파트→다중 트랙 변환의 2단계. score.parts[0] 고정 대신 명시적으로
part/part_index를 받게 바꿨다. RepeatBracket 탐색도 score.recurse()에서
part.recurse()로 좁혀서, 이제부터 이 함수가 정말 그 파트 하나만 보고
동작하게 했다. 곡중간 템포 변화(_build_tempo_changes)는 곡 전체 개념이라
part_index==0일 때만 계산하고 다른 파트에서는 무시한다.

주의: 이 커밋 시점에는 musicxml_to_gp5가 아직 구 시그니처로 호출 중이라
전체 테스트 스위트가 깨져 있다 — 다음 커밋(_build_song 확장 + 오케스트레이션
변경)까지 반드시 이어서 진행한다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `_build_song`을 트랙 리스트로 확장

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:855-1104` (`_build_song`)
- Modify: `tests/test_musicxml_to_gp.py:277-297` (`test_out_of_range_note_is_logged_and_skipped` — `_build_song` 직접 호출부 1곳)
- Test: `tests/test_musicxml_to_gp.py` (새 테스트 함수 추가)

**Interfaces:**
- Consumes: `MeasureData`(Task 2 이전과 동일한 dataclass, 변경 없음).
- Produces: `_build_song(measures_data_by_track: List[List[MeasureData]], tab_hints: Optional[List[Tuple[int, int]]] = None) -> guitarpro.Song` — Task 4가 이 시그니처로 호출한다. `song.tracks`의 개수 == `len(measures_data_by_track)`.

- [ ] **Step 1: 기존 직접 호출부를 새 시그니처에 맞게 먼저 고친다**

`tests/test_musicxml_to_gp.py:287`:

```python
        song = _build_song(measures_data)
```

를

```python
        song = _build_song([measures_data])
```

로 변경한다(이 테스트는 파트 1개 케이스라 리스트로 한 번 더 감싸기만 하면 된다).

- [ ] **Step 2: 실패하는 테스트 작성 (다중 트랙)**

`tests/test_musicxml_to_gp.py`의 `test_out_of_range_note_is_logged_and_skipped` 함수 뒤에 추가:

```python
def test_build_song_creates_one_track_per_part():
    """measures_data_by_track에 파트가 2개 들어오면 song.tracks도 2개여야
    하고, 각 트랙은 자기 파트의 음표만 담아야 한다(서로 섞이면 안 됨)."""
    track0_data = [
        MeasureData(
            numerator=4, denominator=4, key_fifths=0,
            voices=[[NoteEvent(pitches=[60], ql=4.0, tied=[False])]],  # C4
        )
    ]
    track1_data = [
        MeasureData(
            numerator=4, denominator=4, key_fifths=0,
            voices=[[NoteEvent(pitches=[67], ql=4.0, tied=[False])]],  # G4
        )
    ]

    song = _build_song([track0_data, track1_data])

    assert len(song.tracks) == 2
    assert len(song.measureHeaders) == 1  # 곡 전체 마디헤더는 하나만(트랙끼리 공유)

    def _notes(track):
        return [
            (note.string, note.value)
            for measure in track.measures
            for voice in measure.voices
            for beat in voice.beats
            for note in beat.notes
        ]

    notes0 = _notes(song.tracks[0])
    notes1 = _notes(song.tracks[1])
    # _assign_with_tie_carryover(strings=표준 튜닝)로 직접 확인된 배정값:
    # MIDI60(C4) → (string2, fret1), MIDI67(G4) → (string1, fret3).
    assert notes0 == [(2, 1)]
    assert notes1 == [(1, 3)]
    assert notes1 != notes0     # 핵심 검증: 두 트랙이 서로 다른 음표를 담아야 함(오염 없음)


def test_build_song_second_track_ignores_own_header_fields():
    """2번째 트랙의 박자표/반복표 등은 무시되고, song.measureHeaders는
    첫 번째 트랙(파트 0) 기준으로만 정해져야 한다."""
    track0_data = [
        MeasureData(
            numerator=4, denominator=4, key_fifths=0,
            voices=[[NoteEvent(pitches=[60], ql=4.0, tied=[False])]],
        )
    ]
    # 파트 1이 (실무상 없다고 가정하지만) 만약 다른 박자표를 갖고 있어도
    # 곡 전체 헤더는 파트 0(4/4)을 따라야 한다.
    track1_data = [
        MeasureData(
            numerator=3, denominator=4, key_fifths=2,
            voices=[[NoteEvent(pitches=[67], ql=3.0, tied=[False])]],
        )
    ]

    song = _build_song([track0_data, track1_data])

    assert song.measureHeaders[0].timeSignature.numerator == 4
    assert song.measureHeaders[0].timeSignature.denominator.value == 4
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_build_song_creates_one_track_per_part tests/test_musicxml_to_gp.py::test_build_song_second_track_ignores_own_header_fields -v`
Expected: FAIL — `TypeError`류(현재 `_build_song`이 `measures_data[0]`을 `MeasureData` 인스턴스로 기대하는데 `List[MeasureData]`(리스트의 리스트 첫 항목)를 받아 어긋남) 또는 `AttributeError: 'list' object has no attribute 'numerator'`.

- [ ] **Step 4: `_build_song` 구현 수정**

`app/pipeline/musicxml_to_gp.py:855-1104` 전체를 아래로 교체:

```python
def _build_song(
    measures_data_by_track: List[List[MeasureData]],
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> guitarpro.Song:
    """트랙(파트)별 마디 목록으로 GP Song 객체를 생성한다.

    measures_data_by_track[0](파트 0)의 박자표/조표/반복표 열기·닫기/volta/
    direction만 song.measureHeaders에 반영한다 — 같은 곡의 여러 파트가 서로
    다른 마디 구조(박자표 등)를 갖는 일은 실무상 없다고 가정하기 때문이다.
    measures_data_by_track[1:]의 동일 필드는 무시하고 음표 내용만 각자의
    트랙에 채운다. 모든 트랙은 표준 6현 어쿠스틱 기타 튜닝을 그대로 쓴다
    (파트별 악기 인식은 하지 않음).

    tab_hints는 주 멜로디(measures_data_by_track[0]의 voices[0])의 음표
    개수(쉼표 제외)와 같을 때만, 그 트랙의 그 보이스에 명시적 (현,프렛)을
    쓴다. 나머지 트랙/보이스는 항상 휴리스틱을 쓴다(탭보표는 한 줄짜리
    멜로디만 읽으므로 다성/다중트랙에는 대응 불가).
    """
    first_track_data = measures_data_by_track[0]
    total_notes = sum(
        1 for m in first_track_data for ev in m.voices[0]
        if not ev.is_rest and len(ev.pitches) == 1
    )
    if tab_hints is not None and len(tab_hints) != total_notes:
        tab_hints = None

    song = gpm.Song()
    track = song.tracks[0]
    strings = [(s.number, s.value) for s in track.strings]

    if tab_hints is not None:
        valid_string_numbers = {snum for snum, _ in strings}
        if any(
            not (0 <= fret <= 24) or string not in valid_string_numbers
            for string, fret in tab_hints
        ):
            tab_hints = None

    hints_iter = iter(tab_hints) if tab_hints is not None else None

    def _next_hint() -> Optional[Tuple[int, int]]:
        return next(hints_iter) if hints_iter is not None else None

    if not first_track_data:
        return song

    def _apply_header(mh: gpm.MeasureHeader, md: MeasureData) -> None:
        mh.timeSignature.numerator = md.numerator
        mh.timeSignature.denominator.value = md.denominator
        fifths = max(-8, min(8, md.key_fifths))
        mh.keySignature = _FIFTHS_TO_KEYSIG[fifths]
        mh.isRepeatOpen = md.is_repeat_open
        mh.repeatClose = md.repeat_close
        mh.repeatAlternative = md.repeat_alternative
        if md.direction:
            mh.direction = gpm.DirectionSign(md.direction)
        if md.from_direction:
            mh.fromDirection = gpm.DirectionSign(md.from_direction)

    def _fill_voice(
        voice: gpm.Voice, events: List[NoteEvent], use_hints: bool,
        numerator: int, denominator: int,
    ) -> None:
        beats: List[Beat] = []
        # 이어지는 음(tie)이 직전 비트와 같은 줄을 유지하도록 추적한다
        # (pitch → 그 음이 현재 놓인 줄 번호). 쉼표를 만나면 비운다.
        prev_pitch_to_string: Dict[int, int] = {}

        for ev in events:
            if ev.tuplet is not None:
                enters, times = ev.tuplet
                ql_for_duration = ev.ql * enters / times
            else:
                ql_for_duration = ev.ql
            gp_val, is_dotted = _ql_to_gp_duration(ql_for_duration)

            if ev.is_rest:
                beat = Beat(voice=voice)
                beat.status = BeatStatus.rest
                beat.duration.value = gp_val
                beat.duration.isDotted = is_dotted
                if ev.tuplet is not None:
                    enters, times = ev.tuplet
                    beat.duration.tuplet = gpm.Tuplet(enters=enters, times=times)
                beat.notes = []
                beats.append(beat)
                prev_pitch_to_string = {}
                continue

            if len(ev.pitches) >= 2:
                # 화음: tab_hints는 무시(힌트 1개로 다중음 표현 불가)하고
                # 이어지는 음은 직전 줄을 유지, 새 음만 남은 줄에 배정한다.
                placements = _assign_with_tie_carryover(
                    ev.pitches, ev.tied, strings, prev_pitch_to_string
                )
                beat = Beat(voice=voice)
                beat.status = BeatStatus.normal
                beat.duration.value = gp_val
                beat.duration.isDotted = is_dotted
                if ev.tuplet is not None:
                    enters, times = ev.tuplet
                    beat.duration.tuplet = gpm.Tuplet(enters=enters, times=times)

                gnotes = []
                new_prev: Dict[int, int] = {}
                for midi, placement, note_tied in zip(ev.pitches, placements, ev.tied):
                    if placement is None:
                        logger.warning("화음 음 일부가 어떤 현으로도 표현할 수 없어 건너뜀")
                        continue
                    snum, fret = placement
                    gnote = Note(beat=beat)
                    gnote.value = fret
                    gnote.string = snum
                    gnote.type = NoteType.tie if note_tied else NoteType.normal
                    if ev.velocity is not None:
                        gnote.velocity = ev.velocity
                    _apply_articulations(gnote, ev.articulations)
                    gnotes.append(gnote)
                    new_prev[midi] = snum
                prev_pitch_to_string = new_prev
                if not gnotes:
                    # 화음 전체 음이 범위 밖이라 하나도 못 배정되면, 빈
                    # normal 비트(의미상 잘못된 상태) 대신 rest로 처리한다.
                    beat.status = BeatStatus.rest
                beat.notes = gnotes
                beats.append(beat)
                continue

            hint = _next_hint() if use_hints else None
            if hint is not None:
                snum, fret = hint
            else:
                sf = _assign_with_tie_carryover(
                    ev.pitches, ev.tied, strings, prev_pitch_to_string
                )[0]
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.pitches[0])
                    prev_pitch_to_string = {}
                    continue
                snum, fret = sf

            beat = Beat(voice=voice)
            beat.status = BeatStatus.normal
            beat.duration.value = gp_val
            beat.duration.isDotted = is_dotted
            if ev.tuplet is not None:
                enters, times = ev.tuplet
                beat.duration.tuplet = gpm.Tuplet(enters=enters, times=times)

            gnote = Note(beat=beat)
            gnote.value = fret
            gnote.string = snum
            gnote.type = NoteType.tie if ev.tied[0] else NoteType.normal
            if ev.velocity is not None:
                gnote.velocity = ev.velocity
            _apply_articulations(gnote, ev.articulations)
            if ev.tremolo_picking is not None:
                trem_value = _TREMOLO_MARKS_TO_GPV.get(ev.tremolo_picking, gpm.Duration.eighth)
                gnote.effect.tremoloPicking = gpm.TremoloPickingEffect(duration=gpm.Duration(value=trem_value))
            if ev.harmonic == "natural":
                gnote.effect.harmonic = gpm.NaturalHarmonic()
            elif ev.harmonic == "artificial":
                gnote.effect.harmonic = gpm.ArtificialHarmonic()
            if ev.bend is not None:
                gnote.effect.bend = gpm.BendEffect(
                    type=gpm.BendType.bend,
                    points=[gpm.BendPoint(0, 0), gpm.BendPoint(12, round(ev.bend))],
                )
            if ev.palm_mute:
                gnote.effect.palmMute = True
            if ev.slide:
                gnote.effect.slides = [gpm.SlideType.shiftSlideTo]
            if ev.vibrato:
                gnote.effect.vibrato = True
            if ev.ghost:
                gnote.effect.ghostNote = True
            if ev.right_hand_finger is not None:
                gnote.effect.rightHandFinger = _FINGERING_TO_GP[ev.right_hand_finger]
            if ev.tempo_change is not None:
                beat.effect.mixTableChange = gpm.MixTableChange(
                    tempo=gpm.MixTableItem(value=ev.tempo_change),
                )
            if ev.trill_alt_midi is not None:
                trill_fret = ev.trill_alt_midi - dict(strings)[snum]
                if 0 <= trill_fret <= 24:
                    # duration은 GP5가 지원하는 트릴 속도 프리셋(16분음표/32분음표/
                    # 64분음표)이어야 한다 — 기본값(4분음표)은 GP5가 못 써서 쓰기
                    # 단계에서 조용히 깨진다.
                    gnote.effect.trill = gpm.TrillEffect(
                        fret=trill_fret, duration=gpm.Duration(value=gpm.Duration.sixteenth),
                    )
            if ev.grace is not None and len(ev.pitches) == 1:
                grace_midi, transition_name = ev.grace
                sf_grace = _midi_to_string_fret(grace_midi, strings)
                if sf_grace is not None:
                    _, grace_fret = sf_grace
                    trans = (
                        gpm.GraceEffectTransition.hammer
                        if transition_name == 'hammer'
                        else gpm.GraceEffectTransition.slide
                    )
                    gnote.effect.grace = gpm.GraceEffect(
                        duration=32, fret=grace_fret, transition=trans
                    )
            beat.notes = [gnote]
            beats.append(beat)
            prev_pitch_to_string = {ev.pitches[0]: snum}

        if not beats:
            # 이 마디에서 이 보이스가 완전히 안 쓰여도(특히 2번째 보이스),
            # beats를 진짜 빈 배열로 두면 안 된다 — alphaTab이 한 번이라도
            # 그 보이스가 실제로 쓰인 뒤(다른 마디에서) 빈 배열을 만나면
            # "Cannot read properties of undefined (reading 'beats')"로
            # 로드 자체가 죽는다(실사례로 재현 확인, PyGuitarPro/GP5 파일
            # 자체는 이상 없어서 이 리포의 다른 자동화 테스트로는 못 잡힘).
            # 마디 전체를 채우는 쉼표 비트 1개로 대신한다.
            ql = 4.0 * numerator / denominator
            gp_val, is_dotted = _ql_to_gp_duration(ql)
            rest_beat = Beat(voice=voice)
            rest_beat.status = BeatStatus.rest
            rest_beat.duration.value = gp_val
            rest_beat.duration.isDotted = is_dotted
            rest_beat.notes = []
            beats = [rest_beat]

        voice.beats = beats

    def _fill_measure(measure: gpm.Measure, md: MeasureData, allow_hints: bool) -> None:
        for vi, events in enumerate(md.voices):
            _fill_voice(
                measure.voices[vi], events, use_hints=(vi == 0 and allow_hints),
                numerator=md.numerator, denominator=md.denominator,
            )
        if md.chord_name is not None and measure.voices[0].beats:
            measure.voices[0].beats[0].effect.chord = gpm.Chord(
                length=6, name=md.chord_name, show=False, firstFret=0,
            )

    def _build_track_measures(
        cur_track: gpm.Track, measures_data: List[MeasureData],
        build_headers: bool, allow_hints: bool,
    ) -> None:
        """이 트랙의 모든 마디에 음표를 채운다.

        build_headers=True인 트랙(파트 0)만 song.measureHeaders를 새로 만들고
        박자표/조표/반복표 등을 적용한다 — 나머지 트랙은 이미 만들어진 헤더를
        그대로 재사용하고 음표만 채운다(곡 전체 마디 구조는 공유되므로).
        """
        first_mh = song.measureHeaders[0]
        first_measure = cur_track.measures[0]
        if build_headers:
            _apply_header(first_mh, measures_data[0])
        _fill_measure(first_measure, measures_data[0], allow_hints)

        start = first_mh.start + first_mh.length
        for i, md in enumerate(measures_data[1:], start=2):
            if build_headers:
                mh = gpm.MeasureHeader()
                mh.number = i
                mh.start = start
                _apply_header(mh, md)
                song.measureHeaders.append(mh)
            else:
                mh = song.measureHeaders[i - 1]

            m = gpm.Measure(cur_track, mh)
            _fill_measure(m, md, allow_hints)
            cur_track.measures.append(m)

            start += mh.length

    for idx, measures_data in enumerate(measures_data_by_track):
        if idx == 0:
            cur_track = track
        else:
            cur_track = gpm.Track(song, number=idx + 1)
            song.tracks.append(cur_track)
        _build_track_measures(
            cur_track, measures_data,
            build_headers=(idx == 0),
            allow_hints=(idx == 0),
        )

    return song
```

바뀐 지점 요약: 시그니처(`measures_data` → `measures_data_by_track: List[List[MeasureData]]`), `total_notes`/`tab_hints` 검증이 `first_track_data`(= `measures_data_by_track[0]`) 기준, `_fill_measure`에 `allow_hints: bool` 파라미터 추가(2번째 이후 트랙은 항상 `False`), 마디 조립 로직을 `_build_track_measures` 클로저로 뽑아서 `build_headers`(파트 0만 `True`) 플래그로 헤더 신규 생성 여부를 가르고, 마지막에 `measures_data_by_track`를 순회하며 트랙을 만든다. `gpm.Track(song, number=idx+1)`은 PyGuitarPro 기본 생성자가 이미 표준 6현 튜닝(EADGBE)과 기본 음색(instrument=25)으로 초기화하므로 별도 튜닝 설정 코드가 필요 없다(직접 확인됨: `gpm.Track(song)`의 `strings`가 `_STANDARD_STRINGS`와 동일).

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_build_song_creates_one_track_per_part tests/test_musicxml_to_gp.py::test_build_song_second_track_ignores_own_header_fields tests/test_musicxml_to_gp.py::test_out_of_range_note_is_logged_and_skipped -v`
Expected: PASS 전부.

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "$(cat <<'EOF'
feat: _build_song을 트랙 리스트로 확장 (다중트랙 준비)

다중 파트→다중 트랙 변환의 3단계. measures_data_by_track(파트별 리스트)를
받아 파트 개수만큼 song.tracks를 만든다. 마디헤더(박자표/조표/반복표/
direction)는 파트 0에서만 만들고 나머지 트랙은 그 헤더를 공유하며 음표만
채운다. tab_hints도 파트 0에만 적용된다. gpm.Track 기본 생성자가 이미
표준 6현 튜닝이라 트랙별 튜닝 코드는 불필요.

주의: 이 커밋 시점에는 musicxml_to_gp5가 아직 구 시그니처로 호출 중이라
전체 테스트 스위트가 깨져 있다 — 다음 커밋(오케스트레이션 변경)까지
반드시 이어서 진행한다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `musicxml_to_gp5` 오케스트레이션을 다중 파트로 확장

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py:1142-1155` (`musicxml_to_gp5` 내부, `_collect_notes`/`_build_song` 호출부)
- Test: `tests/test_musicxml_to_gp.py` (새 테스트 함수 추가)

**Interfaces:**
- Consumes: `_collect_notes(part, xml_path, part_index)`(Task 2), `_build_song(measures_data_by_track, tab_hints)`(Task 3).
- Produces: `musicxml_to_gp5`의 공개 시그니처는 변경 없음(`xml_path, gp5_path, timeout=0, tab_hints=None`) — 여러 `<part>`가 있으면 자동으로 여러 트랙을 만든다. `app/pipeline/orchestrator.py`는 이 함수를 그대로 호출하므로 수정 불필요.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_musicxml_to_gp.py` 맨 아래에 추가(이 fixture는 전체 파이프라인을 도는 통합 테스트다):

```python
_TWO_PART_GUITAR_DUET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar 1</part-name></score-part>
    <score-part id="P2"><part-name>Guitar 2</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>E</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
        <notations><technical><bend><bend-alter>2</bend-alter></bend></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_musicxml_to_gp5_creates_track_per_part(tmp_path):
    """파트 2개짜리(기타 듀엣) MusicXML을 변환하면 GP5에 트랙이 2개 생기고,
    각 트랙이 자기 파트의 음표/이펙트만 담아야 한다(다른 트랙으로 안 샘)."""
    xml_path = tmp_path / "duet.musicxml"
    xml_path.write_text(_TWO_PART_GUITAR_DUET_XML, encoding="utf-8")
    out = str(tmp_path / "duet.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert len(song.tracks) == 2

    def _first_note(track):
        return track.measures[0].voices[0].beats[0].notes[0]

    note0 = _first_note(song.tracks[0])
    note1 = _first_note(song.tracks[1])

    # 실제(sounding) MIDI는 기타 표기 관행상 적힌 음보다 1옥타브 낮다.
    # note0: 적힌 C5(72) → 소리 C4(60). note1: 적힌 E4(64) → 소리 E3(52).
    assert note0.effect.bend is None
    assert note1.effect.bend is not None  # 파트2에만 있던 벤드가 트랙2에만 적용돼야 함
    assert note0.string != note1.string or note0.value != note1.value  # 서로 다른 음


def test_musicxml_to_gp5_single_part_unchanged(tmp_path):
    """파트 1개짜리 기존 fixture는 여전히 트랙 1개만 만들어야 한다(회귀 없음)."""
    out = str(tmp_path / "single.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    assert len(song.tracks) == 1
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_creates_track_per_part tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_single_part_unchanged -v`
Expected: FAIL — `TypeError: _collect_notes() missing 1 required positional argument` (아직 `musicxml_to_gp5`가 구 시그니처로 호출 중이라 Task 2/3 변경 이후 이 함수 자체가 깨져 있던 상태 그대로).

- [ ] **Step 3: `musicxml_to_gp5` 오케스트레이션 수정**

`app/pipeline/musicxml_to_gp.py:1142-1155`을 아래로 교체:

```python
    try:
        measures_data_by_track = [
            _collect_notes(part, xml_path, i) for i, part in enumerate(score.parts)
        ]
    except Exception as e:
        raise GpConvertError("음표 추출 실패") from e

    if not any(
        not ev.is_rest
        for measures_data in measures_data_by_track
        for m in measures_data
        for voice_events in m.voices
        for ev in voice_events
    ):
        raise GpConvertError("변환할 음표 없음")

    try:
        song = _build_song(measures_data_by_track, tab_hints=tab_hints)
    except Exception as e:
        raise GpConvertError("GP5 쓰기 실패") from e
```

이 아래의 템포(`_extract_tempo(score)`)/메타데이터(`score.metadata`)/악기(`score.parts[0].getInstrument()`, `song.tracks[0].channel.instrument`)/가사(`_collect_lyrics(score)`) 블록은 전부 **수정하지 않는다** — 이미 `score`(파트 0 기준 템포·메타데이터) 또는 `score.parts[0]`(파트 0 악기)만 보고 `song.tracks[0]`(트랙 0)에만 적용하고 있어서, 설계의 "곡 전체 공통은 파트 0 기준, 파트별 악기 인식은 안 함(추가 트랙은 기본 음색 유지)" 요구사항과 이미 일치한다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_creates_track_per_part tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_single_part_unchanged -v`
Expected: PASS 전부.

- [ ] **Step 5: 전체 스위트로 회귀 확인 (가장 중요한 안전망)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 PASS. 이 시점에서 Task 1~4가 합쳐지며 기존 파트 1개짜리 fixture 전체가 다시 정상 동작해야 한다.

- [ ] **Step 6: `git stash`로 회귀 테스트가 실제로 버그를 잡는지 확인**

```bash
git stash push -- app/pipeline/musicxml_to_gp.py
.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_creates_track_per_part -v
```
Expected: FAIL(구현이 스태시되어 파트 0만 처리하므로 `len(song.tracks) == 2` 실패).

```bash
git stash pop
.venv/bin/python -m pytest tests/test_musicxml_to_gp.py::test_musicxml_to_gp5_creates_track_per_part -v
```
Expected: PASS(구현 복원).

- [ ] **Step 7: 프론트엔드 타입체크(회귀 없음 확인용, 백엔드만 바뀌었지만 CI 습관상 확인)**

Run: `cd frontend && npx tsc -b && cd ..`
Expected: 에러 없음(이번 태스크는 프론트엔드 코드를 건드리지 않음).

- [ ] **Step 8: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "$(cat <<'EOF'
feat: 다중 파트 MusicXML을 다중 트랙 GP5로 변환

기타 듀엣/앙상블처럼 여러 <part>로 된 표준악보를 변환하면, 이제 파트마다
GP5 Track이 하나씩 생긴다(기존엔 score.parts[0] 고정이라 항상 트랙
1개짜리로만 나왔음). 박자표/조표/반복표/direction/템포/메타데이터는
파트 0 기준으로 한 번만 계산해 모든 트랙이 공유하고, 음표/벤드/트릴 등
이펙트는 파트마다 독립적으로 추출해 각자의 트랙에만 담는다(트랙 간 오염 없음).

탭보표가 감지된 악보는 orchestrator.py의 기존 분기 그대로 첫 파트 단일트랙
tab-OMR 경로를 탄다 — 이번 변경과 무관.

design: docs/superpowers/specs/2026-07-20-multi-part-multi-track-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: 원격 저장소에 푸시**

```bash
git push origin main
```

---

## 최종 확인 체크리스트

- [ ] `.venv/bin/python -m pytest tests/ -q` 전체 통과
- [ ] `cd frontend && npx vitest run && npx tsc -b && cd ..` 전체 통과(이번 작업은 프론트엔드를 건드리지 않으므로 회귀 없어야 함)
- [ ] 파트 1개짜리 기존 fixture(`tests/fixtures/sample.musicxml`)가 여전히 트랙 1개로 변환됨(`test_musicxml_to_gp5_single_part_unchanged`)
- [ ] 파트 2개짜리(기타 듀엣) fixture가 트랙 2개로, 서로 이펙트가 안 섞인 채 변환됨(`test_musicxml_to_gp5_creates_track_per_part`)
- [ ] 탭보표 감지 시 `orchestrator.py`가 여전히 `token_texts_to_gp5` 단일트랙 경로를 타는지(코드 리뷰로 확인 — 이번 계획에서 `orchestrator.py`는 수정하지 않았으므로 자동으로 유지됨)
