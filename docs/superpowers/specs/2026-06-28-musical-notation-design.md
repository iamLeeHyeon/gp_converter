# 음악 기호 GP5 변환 설계

## 배경

`app/pipeline/musicxml_to_gp.py`는 음표·쉼표·이음줄·화음·박자/조표를 변환하지만,
MusicXML의 음악 기호(잇단음, 다이나믹, 슬러, 아티큘레이션, 페르마타, 그레이스노트)는
전부 무시한다. 실제 테스트곡("Flower of the Field")에서 실측 확인: 잇단음 18개, 다이나믹
10개, 아티큘레이션 61개, 슬러 1개 — 전부 지금은 GP5에 반영 안 됨.

## 목표

MusicXML 음악 기호 6종을 GP5로 변환한다:

1. **잇단음(tuplet)** — 셋잇단음 등, 박자 분할
2. **다이나믹(dynamics)** — 셈여림(p/mf/f 등)
3. **슬러(slur)** — legato 표현선
4. **아티큘레이션(articulation)** — 스타카토, 악센트 등
5. **페르마타(fermata)** — 늘임표
6. **그레이스노트(grace note)** — 꾸밈음

## 설계 원칙

기존 아키텍처 그대로 유지: `_extract_events`에서 music21 정보를 `NoteEvent`에 담고,
`_fill_voice`에서 GP5 객체에 적용. 파일 하나(`musicxml_to_gp.py`)만 수정한다.

---

## 데이터 모델 변경

`NoteEvent`에 필드 5개 추가(페르마타는 무시이므로 필드 없음):

```python
@dataclass
class NoteEvent:
    pitches: List[int]
    ql: float
    tied: List[bool] = field(default_factory=list)
    is_rest: bool = False
    # 새로 추가
    tuplet: Optional[Tuple[int, int]] = None
    # (enters, times). 예: (3, 2)=셋잇단, (5, 4)=다섯잇단.
    # PyGuitarPro 지원: (3,2),(5,4),(6,4),(7,4),(9,8),(10,8),(11,8),(12,8),(13,8).
    # 미지원 잇단음은 None으로 두고 경고 로그.
    velocity: Optional[int] = None
    # None이면 기본값(forte=95) 사용.
    # 다이나믹 carry-forward: Dynamic 객체 만나면 갱신, 이후 음표에 계속 적용.
    hammer: bool = False
    # 슬러 안의 첫 번째 음을 제외한 모든 음. GP5에서 hammer-on으로 표현.
    articulations: List[str] = field(default_factory=list)
    # 'staccato' | 'accent' | 'strong-accent' | 'tenuto'
    grace: Optional[Tuple[int, str]] = None
    # (MIDI pitch of grace note, transition)
    # transition: 'none' | 'slide' | 'hammer' (오름=hammer, 내림=slide)
    # 여러 그레이스노트가 연속이면 마지막 하나만 사용(GP5는 음표당 1개만 지원).
```

---

## 기능별 구현

### 1. 잇단음(Tuplet)

**MusicXML 소스**: `n.duration.tuplets` 리스트. `tuplets[0].numberNotesActual`(분자),
`tuplets[0].numberNotesNormal`(분모).

**추출**(`_extract_events`):
```python
if n.duration.tuplets:
    tp = n.duration.tuplets[0]
    enters = tp.numberNotesActual
    times  = tp.numberNotesNormal
    supported = [(3,2),(5,4),(6,4),(7,4),(9,8),(10,8),(11,8),(12,8),(13,8)]
    if (enters, times) in supported:
        tuplet = (enters, times)
    else:
        logger.warning("미지원 잇단음 %d:%d — 무시", enters, times)
        tuplet = None
```

**적용**(`_fill_voice`):
```python
from guitarpro.models import Tuplet
if ev.tuplet is not None:
    enters, times = ev.tuplet
    beat.duration.tuplet = Tuplet(enters=enters, times=times)
```

`_ql_to_gp_duration` 시그니처는 바꾸지 않는다. 잇단음의 `ql` 자체(예: 셋잇단 8분음표
= 1/3)는 기존 fallback 로직으로 가장 가까운 기본값(8분음표=8)을 찾고, tuplet 필드로
실제 잇단음 비율을 별도 적용한다.

### 2. 다이나믹(Dynamics)

**MusicXML 소스**: 스트림 안의 `music21.dynamics.Dynamic` 객체. 음표에 직접 붙지 않고
스트림 내 별도 요소로 존재 — offset 순서로 carry-forward 처리.

**velocity 매핑**:
```python
_DYNAMIC_VELOCITY = {
    'ppp': 15, 'pp': 31, 'p': 47, 'mp': 63,
    'mf': 79,  'f':  95, 'ff': 111, 'fff': 127,
}
```

**추출**(`_extract_events`): 음표 순회 전에 스트림에서 Dynamic 객체를 먼저 수집해
offset → velocity 딕셔너리로 만들어두고, 음표마다 자신의 offset보다 작거나 같은
마지막 Dynamic velocity를 carry-forward 적용.

```python
import music21.dynamics as m21dyn

def _build_velocity_map(stream_like) -> dict:
    """offset → velocity 딕셔너리. 음표 처리 전 한 번만 실행."""
    result = {}
    for el in stream_like.recurse().getElementsByClass(m21dyn.Dynamic):
        v = _DYNAMIC_VELOCITY.get(el.value)
        if v is not None:
            result[float(el.offset)] = v
    return result

# _extract_events 내부
vel_map = _build_velocity_map(stream_like)
sorted_vel_offsets = sorted(vel_map)

for n in stream_like.notesAndRests:
    # 해당 음표 offset 이하의 마지막 dynamic
    note_offset = float(n.offset)
    current_vel = None
    for off in sorted_vel_offsets:
        if off <= note_offset:
            current_vel = vel_map[off]
        else:
            break
    ...
    event = NoteEvent(..., velocity=current_vel)
```

**적용**(`_fill_voice`):
```python
if ev.velocity is not None:
    gnote.velocity = ev.velocity
```

### 3. 슬러(Slur → hammer-on/pull-off)

**GP5 대응**: `NoteEffect.hammer = True`. GP5엔 slur 개념 없어서 hammer-on으로 표현.
슬러 첫 음은 새로 침(normal), 이후 음들은 `hammer=True`.

**추출**(`_extract_events`):
```python
from music21 import spanner as m21spanner
for slur in stream_like.recurse().getElementsByClass(m21spanner.Slur):
    elements = slur.getSpannedElements()
    for n in elements[1:]:  # 첫 음 제외
        slurred_note_ids.add(id(n))
```
음표 처리 시 `id(n) in slurred_note_ids`면 `hammer=True`.

**적용**(`_fill_voice`):
```python
if ev.hammer:
    gnote.effect.hammer = True
```

### 4. 아티큘레이션(Articulation)

**MusicXML 소스**: `n.articulations` 리스트.

**매핑**:
```python
import music21.articulations as m21art
_ARTICULATION_MAP = {
    m21art.Staccato:      'staccato',
    m21art.Accent:        'accent',
    m21art.StrongAccent:  'strong-accent',
    m21art.Tenuto:        'tenuto',
}
```

**추출**(`_extract_events`):
```python
arts = []
for a in n.articulations:
    key = _ARTICULATION_MAP.get(type(a))
    if key:
        arts.append(key)
```

**적용**(`_fill_voice`):
```python
for art in ev.articulations:
    if art == 'staccato':
        gnote.effect.staccato = True
    elif art == 'accent':
        gnote.effect.accentuatedNote = True
    elif art == 'strong-accent':
        gnote.effect.heavyAccentuatedNote = True
    elif art == 'tenuto':
        gnote.effect.letRing = True
```

화음은 모든 구성음에 동일 아티큘레이션 적용.

### 5. 페르마타(Fermata)

**결정**: 무시. GP5에 직접 대응 기능 없음. 코드 변경 없음.

### 6. 그레이스노트(Grace Note)

**MusicXML 소스**: `n.duration.isGrace == True`인 `Note` 객체. 스트림에서 일반 음표
바로 앞에 위치. GP5는 음표당 그레이스노트 1개만 지원.

**추출**(`_extract_events`): pending_grace 버퍼 유지.

```python
pending_grace: Optional[Tuple[int, str]] = None
for n in stream_like.notesAndRests:
    if isinstance(n, m21note.Note) and n.duration.isGrace:
        # 여러 개면 마지막 것만 유지
        midi = n.pitch.midi + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
        pending_grace = (midi, 'grace_pending')
        continue
    if isinstance(n, m21note.Rest):
        pending_grace = None
        events.append(NoteEvent(pitches=[], ql=ql, is_rest=True))
        continue
    # 일반 음표: pending_grace가 있으면 transition 결정
    grace = None
    if pending_grace is not None:
        grace_midi, _ = pending_grace
        main_midi = (pitches[0] if pitches else 0)
        transition = 'hammer' if grace_midi < main_midi else 'slide'
        grace = (grace_midi, transition)
        pending_grace = None
    events.append(NoteEvent(..., grace=grace))
```

**적용**(`_fill_voice`): 단일음만 그레이스노트 지원(화음엔 미적용).

```python
from guitarpro.models import GraceEffect, GraceEffectTransition
if ev.grace is not None and len(ev.pitches) == 1:
    grace_midi, transition_name = ev.grace
    sf = _midi_to_string_fret(grace_midi, strings)
    if sf is not None:
        _, fret = sf
        trans = (GraceEffectTransition.hammer if transition_name == 'hammer'
                 else GraceEffectTransition.slide)
        gnote.effect.grace = GraceEffect(duration=32, fret=fret, transition=trans)
```

---

## 영향받지 않는 부분

이음줄(tie), 화음(chord) 배정, 마디 그룹화, 박자/조표, 유령 쉼표 제거,
옥타브 보정(-12), tab_hints — 전부 그대로.

## 테스트 계획

1. 셋잇단음(3:2) 합성 MusicXML → GP5 비트의 `duration.tuplet.enters==3, times==2` 확인.
2. 다이나믹 carry-forward → 동적 변화 후 음표 velocity 갱신 확인.
3. 슬러 안 첫 음 normal, 후속음 hammer=True 확인.
4. 아티큘레이션 4종 각각 적용 확인(staccato/accent/strong-accent/tenuto).
5. 그레이스노트 오름→hammer, 내림→slide transition 확인.
6. 기존 전체 테스트 회귀 없음.
