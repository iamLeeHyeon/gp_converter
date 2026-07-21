"""
MusicXML → Guitar Pro 5 변환기 (PyGuitarPro 기반)

설계 결정:
- 코드(Chord): 모든 구성음을 서로 다른 현/프렛에 동시발음으로 배정한다
  (_assign_chord_strings). 높은음부터 그리디하게 배정하고, 1순위 현이
  막히면 다음 후보로 넘어간다(fallback). 끝까지 못 들어가는 음만 건너뛴다.
- 현/프렛 배정: MIDI 값을 줄 수 있는 모든 현에서 유효(0~24 프렛)한 것 중
  가장 낮은 프렛 번호를 선택한다. 동점이면 가장 높은 줄 번호(낮은 음) 우선.
  유효한 현이 없으면(MIDI가 범위 밖) 해당 음표를 건너뛴다.
- 마디 그룹화: MusicXML의 실제 마디 경계를 그대로 따른다. 박자/조표가 그
  마디에 명시돼 있지 않으면 이전 마디 값을 이어받는다(carry-forward).
- 다성(보이스): 한 마디에 <backup>으로 만든 보이스가 여러 개면 GP5가 지원
  하는 최대 2개까지 그대로 둔다(3개 이상은 버림). 탭힌트는 voices[0](주
  멜로디)에만 적용한다.
- 이음줄(tie): 이어지는 두 번째 이후 음은 길이를 합치지 않고(GP5는 마디당
  박자 총합이 고정이라 합치면 깨짐) NoteType.tie로만 표시한다. 화음은 음별로
  따로 추적한다(NoteEvent.tied가 pitches와 같은 길이의 리스트) — music21
  Chord.tie는 구성음 중 하나의 tie만 대표로 골라 화음 전체에 적용해서, 화음
  안에서 음마다 tie 상태가 다른 실제 케이스(한 음은 이어지고 한 음은 새로
  침)를 못 구분하기 때문이다. 이어지는 음은 직전 비트와 같은 줄을 그대로
  유지한다(_assign_with_tie_carryover) — GP5는 이어지는 음의 프렛 값을 따로
  안 믿고 직전 비트의 같은 줄 값을 그대로 베껴오므로, 화음 구성이 바뀌며
  같은 음이 다른 줄로 옮겨가면 엉뚱한 음높이로 깨진다.
- 점음표: quarterLength가 점음표 값(1.5×기본값)이면 isDotted=True로 설정한다.
- 매핑 불가 박자: 가장 가까운 기본 박자값으로 내림한다(문서화).
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

주의: Beat.status를 BeatStatus.normal로 명시해야 한다. 기본값(empty)으로 두면
PyGuitarPro가 GP5 작성 시 같은 마디의 비트들을 하나로 합쳐 음표를 전부
동시발음 화음으로 뭉개버린다(순차 음표 구조가 깨짐).
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus
from music21 import converter, bar as m21bar, harmony as m21harmony, expressions as m21expr, note as m21note, chord as m21chord, stream as m21stream, spanner as m21spanner, articulations as m21art, dynamics as m21dyn, tempo as m21tempo, repeat as m21repeat


logger = logging.getLogger(__name__)


class GpConvertError(Exception):
    """MusicXML → GP 변환 중 발생하는 오류."""


# 표준 기타 튜닝: (줄 번호, MIDI 값) — 1=high E, 6=low E
_STANDARD_STRINGS: List[Tuple[int, int]] = [
    (1, 64), (2, 59), (3, 55), (4, 50), (5, 45), (6, 40)
]

# quarterLength → GP Duration.value 매핑
_QL_TO_GPV = {4.0: 1, 2.0: 2, 1.0: 4, 0.5: 8, 0.25: 16, 0.125: 32}
# 점음표 ql = (4/value)*1.5 이므로 value = 6/ql. (예: 점8분음표 0.75ql → value=8)
_DOTTED_QL_TO_GPV = {6.0: 1, 3.0: 2, 1.5: 4, 0.75: 8, 0.375: 16, 0.1875: 32}

# 지원 잇단음 (enters, times) 튜플들
_SUPPORTED_TUPLETS: frozenset = frozenset([
    (3, 2), (5, 4), (6, 4), (7, 4),
    (9, 8), (10, 8), (11, 8), (12, 8), (13, 8),
])

# MusicXML 다이나믹 기호 → Note.velocity 매핑
_DYNAMIC_VELOCITY: Dict[str, int] = {
    'ppp': 15, 'pp': 31, 'p': 47, 'mp': 63,
    'mf': 79,  'f':  95, 'ff': 111, 'fff': 127,
}

_ARTICULATION_MAP: Dict[type, str] = {
    m21art.Staccato:     'staccato',
    m21art.Accent:       'accent',
    m21art.StrongAccent: 'strong-accent',
    m21art.Tenuto:       'tenuto',
}

# <fingering>은 클래식기타 관행상 오른손(피킹) 표기(p=엄지,i=검지,m=중지,a=약지,
# c=새끼) — GP5 NoteEffect.rightHandFinger로 대응.
_FINGERING_TO_GP: Dict[str, gpm.Fingering] = {
    'p': gpm.Fingering.thumb,
    'i': gpm.Fingering.index,
    'm': gpm.Fingering.middle,
    'a': gpm.Fingering.annular,
    'c': gpm.Fingering.little,
}

# music21 Tremolo.numberOfMarks(슬래시 개수) → GP5 Duration.value(트레몰로 속도)
_TREMOLO_MARKS_TO_GPV: Dict[int, int] = {
    1: gpm.Duration.eighth,
    2: gpm.Duration.sixteenth,
    3: gpm.Duration.thirtySecond,
}

# 클래식/핑거스타일 기타 표준악보(탭 아님) 표기 관행: 작은 "8" 표기 유무와
# 무관하게 적힌 음보다 항상 1옥타브 낮게 소리난다. Audiveris는 그려진 대로
# 정확히 읽으므로, 실제 소리나는 음을 얻으려면 적힌 MIDI에서 12를 빼야 한다.
_GUITAR_WRITTEN_TO_SOUNDING_OFFSET = -12

# MusicXML fifths(장조 기준) → PyGuitarPro KeySignature. -8~8 범위 밖은 클램프.
_FIFTHS_TO_KEYSIG = {
    -8: gpm.KeySignature.FMajorFlat,
    -7: gpm.KeySignature.CMajorFlat,
    -6: gpm.KeySignature.GMajorFlat,
    -5: gpm.KeySignature.DMajorFlat,
    -4: gpm.KeySignature.AMajorFlat,
    -3: gpm.KeySignature.EMajorFlat,
    -2: gpm.KeySignature.BMajorFlat,
    -1: gpm.KeySignature.FMajor,
    0: gpm.KeySignature.CMajor,
    1: gpm.KeySignature.GMajor,
    2: gpm.KeySignature.DMajor,
    3: gpm.KeySignature.AMajor,
    4: gpm.KeySignature.EMajor,
    5: gpm.KeySignature.BMajor,
    6: gpm.KeySignature.FMajorSharp,
    7: gpm.KeySignature.CMajorSharp,
    8: gpm.KeySignature.GMajorSharp,
}

# 곡 구조 표지: 목표 지점(Coda/Segno/Fine)은 MeasureHeader.direction,
# 점프 지시(D.C./D.S. 등)는 fromDirection에 대응한다. GP5가 지원하는
# 이름 문자열 그대로 매핑(guitarpro.gp5.writeDirections 참고). AlSegno는
# GP5 fromDirection 목록에 대응하는 항목이 없어 제외.
_REPEAT_MARKER_TO_GP = {
    m21repeat.Coda: 'Coda',
    m21repeat.Segno: 'Segno',
    m21repeat.Fine: 'Fine',
}
_REPEAT_COMMAND_TO_GP = {
    m21repeat.DaCapo: 'Da Capo',
    m21repeat.DaCapoAlFine: 'Da Capo al Fine',
    m21repeat.DaCapoAlCoda: 'Da Capo al Coda',
    m21repeat.DalSegno: 'Da Segno',
    m21repeat.DalSegnoAlFine: 'Da Segno al Fine',
    m21repeat.DalSegnoAlCoda: 'Da Segno al Coda',
}


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
    tied: List[bool] = field(default_factory=list)  # True면 그 음은 이어지는 연속음(NoteType.tie)
    is_rest: bool = False
    tuplet: Optional[Tuple[int, int]] = None
    velocity: Optional[int] = None
    hammer: bool = False
    articulations: List[str] = field(default_factory=list)
    grace: Optional[Tuple[int, str]] = None
    tremolo_picking: Optional[int] = None  # music21 Tremolo.numberOfMarks(1|2|3)
    harmonic: Optional[str] = None  # 'natural' | 'artificial' (music21 Harmonic.harmonicType)
    bend: Optional[float] = None  # <bend-alter> 반음(semitone) 값. None이면 벤드 없음
    slide: bool = False  # <slide>/<glissando> 시작 음표면 True → NoteEffect.slides
    palm_mute: bool = False
    vibrato: bool = False  # <notations><technical><vibrato/>
    trill_alt_midi: Optional[int] = None  # <trill-mark> 대체음(사운딩 MIDI). None이면 트릴 없음
    ghost: bool = False  # <notehead parentheses="yes"> (고스트/뮤트 노트)
    right_hand_finger: Optional[str] = None  # 'p'|'i'|'m'|'a'|'c' (<fingering>, 클래식기타 오른손 표기)
    tempo_change: Optional[int] = None  # 이 음표에서 시작되는 곡중간 템포 변화(BPM)


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
    direction: Optional[str] = None  # 'Coda'|'Segno'|'Fine' 등 (GP MeasureHeader.direction)
    from_direction: Optional[str] = None  # 'Da Capo'|'Da Segno al Coda' 등 (GP fromDirection)


def _midi_to_string_fret(
    midi: int,
    strings: List[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    """MIDI 값을 (줄 번호, 프렛) 으로 변환한다.

    유효 프렛(0~24) 중 가장 낮은 프렛을 선택한다.
    유효한 현이 없으면 None 반환 → 해당 음표 건너뜀.
    """
    best: Optional[Tuple[int, int]] = None
    for snum, sval in strings:
        fret = midi - sval
        if 0 <= fret <= 24:
            if best is None or fret < best[1]:
                best = (snum, fret)
    return best


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


def _assign_with_tie_carryover(
    pitches: List[int],
    tied: List[bool],
    strings: List[Tuple[int, int]],
    prev_pitch_to_string: Dict[int, int],
) -> List[Optional[Tuple[int, int]]]:
    """이음줄로 이어지는 음은 직전 비트와 같은 줄을 유지하고, 새로 치는
    음만 남은 줄 중에서 새로 배정한다.

    GP5 포맷은 이어지는 음(NoteType.tie)의 프렛 값을 따로 믿지 않고 직전
    비트의 같은 줄 값을 그대로 이어받는다(실측: Flower of the Field 36마디
    — 화음 구성이 비트마다 바뀌면서 이어지는 음이 다른 줄로 옮겨가, 결과적
    으로 직전 비트의 다른 음 값을 베껴 엉뚱한 음높이로 깨졌다). 그래서
    이어지는 음은 줄을 새로 그리디 배정하면 안 되고, 직전 비트에서 쓰던
    줄을 그대로 고정해야 한다.
    """
    placements: List[Optional[Tuple[int, int]]] = [None] * len(pitches)
    pinned_strings: set = set()
    string_val = dict(strings)

    fresh_indices = []
    for i, (midi, is_tied) in enumerate(zip(pitches, tied)):
        prev_string = prev_pitch_to_string.get(midi) if is_tied else None
        if prev_string is not None:
            placements[i] = (prev_string, midi - string_val[prev_string])
            pinned_strings.add(prev_string)
        else:
            fresh_indices.append(i)

    remaining_strings = [s for s in strings if s[0] not in pinned_strings]
    fresh_pitches = [pitches[i] for i in fresh_indices]
    fresh_placements = _assign_chord_strings(fresh_pitches, remaining_strings)
    for i, placement in zip(fresh_indices, fresh_placements):
        placements[i] = placement

    return placements


def _build_velocity_map(stream_like) -> Dict[float, int]:
    """스트림에서 Dynamic 객체를 찾아 offset → velocity 딕셔너리를 만든다."""
    result: Dict[float, int] = {}
    for el in stream_like.recurse().getElementsByClass(m21dyn.Dynamic):
        v = _DYNAMIC_VELOCITY.get(el.value)
        if v is not None:
            result[float(el.offset)] = v
    return result


def _build_hairpin_velocities(part) -> Dict[int, int]:
    """크레센도/디미누엔도(hairpin) 구간의 음표들에 velocity를 선형보간한다.

    반환값은 (음표 객체의 id() → velocity) — 오프셋 좌표계(마디 로컬 vs
    전체 파트) 불일치 문제를 피하려고 객체 identity로 직접 매핑한다.

    시작 velocity는 하이핀이 시작되는 시점까지 유효했던 명시적 다이내믹
    (없으면 기본 forte=95), 도착 velocity는 하이핀이 끝난 뒤 가장 가까운
    명시적 다이내믹 마킹이다. 도착 다이내믹이 없으면(목표 크기가 안 적힌
    하이핀) 보간 근거가 없어 건너뛴다 — 기존처럼 flat하게 남는다.
    """
    all_notes = list(part.recurse().getElementsByClass((m21note.Note, m21chord.Chord)))
    offsets = [float(n.getOffsetInHierarchy(part)) for n in all_notes]

    dynamics_by_offset: Dict[float, int] = {}
    for el in part.recurse().getElementsByClass(m21dyn.Dynamic):
        v = _DYNAMIC_VELOCITY.get(el.value)
        if v is not None:
            dynamics_by_offset[float(el.getOffsetInHierarchy(part))] = v

    result: Dict[int, int] = {}
    for wedge in part.recurse().getElementsByClass(m21dyn.DynamicWedge):
        first, last = wedge.getFirst(), wedge.getLast()
        if first is None or last is None:
            continue
        start_offset = float(first.getOffsetInHierarchy(part))
        end_offset = float(last.getOffsetInHierarchy(part))
        if end_offset <= start_offset:
            continue

        prior = [o for o in dynamics_by_offset if o <= start_offset]
        start_v = dynamics_by_offset[max(prior)] if prior else 95

        after = [o for o in dynamics_by_offset if o >= end_offset]
        if not after:
            continue
        end_v = dynamics_by_offset[min(after)]

        span = end_offset - start_offset
        for n, off in zip(all_notes, offsets):
            if start_offset <= off <= end_offset:
                frac = (off - start_offset) / span
                result[id(n)] = round(start_v + (end_v - start_v) * frac)
    return result


def _ql_to_gp_duration(ql: float) -> Tuple[int, bool]:
    """quarterLength → (GP Duration.value, isDotted).

    정확히 매핑되지 않으면 가장 가까운 기본 박자값으로 내림한다.
    """
    if ql in _QL_TO_GPV:
        return _QL_TO_GPV[ql], False
    if ql in _DOTTED_QL_TO_GPV:
        return _DOTTED_QL_TO_GPV[ql], True

    # 가장 가까운 기본 박자값으로 fallback
    base_list = sorted(_QL_TO_GPV.keys(), reverse=True)
    nearest = min(base_list, key=lambda x: abs(x - ql))
    return _QL_TO_GPV[nearest], False


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


def _is_tied(tie) -> bool:
    """music21 Tie 객체가 '이어지는 연속음'(continue/stop)인지 판정한다."""
    return tie is not None and tie.type in ("continue", "stop")


def _extract_events(
    stream_like,
    initial_velocity: Optional[int] = None,
    technicals: Optional[Dict[int, Dict[str, Optional[float]]]] = None,
    hairpin_velocities: Optional[Dict[int, int]] = None,
    tempo_changes: Optional[Dict[int, int]] = None,
) -> List[NoteEvent]:
    """한 보이스(또는 단일 보이스 마디)에서 음표/쉼표 이벤트 목록을 뽑는다.

    initial_velocity: 이전 마디에서 이어지는 velocity 초기값(없으면 None=
    기본값 사용). 마디 간 carry-forward는 _collect_notes에서 처리한다.
    technicals: raw XML에서 스캔한 (순번 → {'bend': 반음수, 'palm_mute': None})
    매핑(_scan_raw_technicals 참고). None이면 벤드/팜뮤트 없음으로 처리.
    hairpin_velocities: 크레센도/디미누엔도 구간 보간값((id(음표) → velocity),
    _build_hairpin_velocities 참고). 명시적 다이내믹보다 우선 적용한다.
    tempo_changes: 곡중간 템포 변화((id(음표) → BPM), _build_tempo_changes 참고).
    """
    events: List[NoteEvent] = []
    ordinal = 0
    vel_map = _build_velocity_map(stream_like)
    sorted_vel_offsets = sorted(vel_map)
    pending_grace: Optional[Tuple[int, str]] = None
    for n in stream_like.notesAndRests:
        ql = float(n.duration.quarterLength)
        note_offset = float(n.offset)
        current_velocity: Optional[int] = initial_velocity
        for off in sorted_vel_offsets:
            if off <= note_offset:
                current_velocity = vel_map[off]
            else:
                break
        if hairpin_velocities is not None:
            hairpin_v = hairpin_velocities.get(id(n))
            if hairpin_v is not None:
                current_velocity = hairpin_v
        tempo_change = tempo_changes.get(id(n)) if tempo_changes else None
        # 그레이스노트는 NoteEvent로 만들지 않고, 다음 일반음에 첨부한다.
        if isinstance(n, m21note.Note) and n.duration.isGrace:
            grace_midi = n.pitch.midi + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
            pending_grace = (grace_midi, 'grace_pending')
            continue

        if isinstance(n, m21note.Rest):
            rest_tuplet = None
            if n.duration.tuplets:
                tp = n.duration.tuplets[0]
                e, t = tp.numberNotesActual, tp.numberNotesNormal
                if (e, t) in _SUPPORTED_TUPLETS:
                    rest_tuplet = (e, t)
                else:
                    logger.warning("미지원 잇단음 %d:%d(쉼표) — 무시", e, t)
            pending_grace = None  # 쉼표를 만나면 꾸밈음 버퍼 초기화
            events.append(NoteEvent(pitches=[], ql=ql, is_rest=True, tuplet=rest_tuplet, velocity=current_velocity))
            continue

        if isinstance(n, m21chord.Chord):
            chord_notes = sorted(n.notes, key=lambda cn: cn.pitch.midi, reverse=True)
            midis = [cn.pitch.midi for cn in chord_notes]
            tied = [_is_tied(cn.tie) for cn in chord_notes]
        else:
            midis = [n.pitch.midi]
            tied = [_is_tied(n.tie)]
        pitches = [m + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET for m in midis]

        tremolo_picking = None
        if not isinstance(n, m21chord.Chord):
            for expr in n.expressions:
                if isinstance(expr, m21expr.Tremolo):
                    tremolo_picking = expr.numberOfMarks
                    break

        harmonic = None
        right_hand_finger = None
        if not isinstance(n, m21chord.Chord):
            for art in n.articulations:
                if isinstance(art, m21art.Harmonic):
                    harmonic = art.harmonicType
                elif isinstance(art, m21art.Fingering) and isinstance(art.fingerNumber, str):
                    letter = art.fingerNumber.strip().lower()
                    if letter in _FINGERING_TO_GP:
                        right_hand_finger = letter

        # <notehead parentheses="yes">는 고스트/뮤트 노트 표기(괄호 노트헤드).
        # music21이 .noteheadParenthesis로 바로 노출해준다.
        ghost = not isinstance(n, m21chord.Chord) and bool(n.noteheadParenthesis)

        # <slide>/<glissando>는 music21이 Glissando 스패너로 파싱한다(라인타입만
        # 다름). 슬라이드가 시작되는 음표(getFirst())에만 표시한다 — 도착
        # 음표에 또 붙이면 그쪽에서도 슬라이드가 나가는 것처럼 보인다.
        slide = False
        if not isinstance(n, m21chord.Chord):
            for gl in n.getSpannerSites(m21spanner.Glissando):
                if gl.getFirst() is n:
                    slide = True
                    break

        # <trill-mark>는 music21이 Trill expression으로 파싱한다. realize()가
        # 현재 조표(key)를 반영해 온음/반음을 알맞게 판단한 대체음을 준다 —
        # (main, alt, main, alt...) 시퀀스의 두 번째 음이 대체음이다.
        trill_alt_midi = None
        if not isinstance(n, m21chord.Chord):
            for expr in n.expressions:
                if isinstance(expr, m21expr.Trill):
                    try:
                        realized = expr.realize(n)
                        trill_alt_midi = realized[0][1].pitch.midi + _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
                    except Exception:
                        logger.warning("트릴 대체음 계산 실패 — 트릴 없이 계속 진행", exc_info=True)
                    break

        marks = technicals.get(ordinal, {}) if technicals else {}
        bend = marks.get("bend")
        palm_mute = "palm_mute" in marks
        vibrato = "vibrato" in marks
        ordinal += 1

        # 잇단음 감지
        tuplet = None
        if n.duration.tuplets:
            tp = n.duration.tuplets[0]
            enters = tp.numberNotesActual
            times = tp.numberNotesNormal
            if (enters, times) in _SUPPORTED_TUPLETS:
                tuplet = (enters, times)
            else:
                logger.warning("미지원 잇단음 %d:%d — 무시", enters, times)

        arts: List[str] = []
        if hasattr(n, 'articulations'):
            for a in n.articulations:
                key = _ARTICULATION_MAP.get(type(a))
                if key:
                    arts.append(key)

        # 직전에 버퍼링된 그레이스노트가 있으면 transition 결정 후 첨부
        grace: Optional[Tuple[int, str]] = None
        if pending_grace is not None:
            grace_midi, _ = pending_grace
            main_midi = pitches[0] if pitches else 0
            transition = 'hammer' if grace_midi < main_midi else 'slide'
            grace = (grace_midi, transition)
            pending_grace = None

        events.append(NoteEvent(pitches=pitches, ql=ql, tied=tied, tuplet=tuplet, velocity=current_velocity, articulations=arts, grace=grace, tremolo_picking=tremolo_picking, harmonic=harmonic, bend=bend, palm_mute=palm_mute, slide=slide, vibrato=vibrato, trill_alt_midi=trill_alt_midi, ghost=ghost, right_hand_finger=right_hand_finger, tempo_change=tempo_change))
    return events


def _drop_phantom_leading_rest(events: List[NoteEvent], expected_ql: float) -> List[NoteEvent]:
    """첫 이벤트가 쉼표이고 빼면 정확히 마디 길이가 되는 경우에만 제거한다.

    실측(Flower of the Field, 12개 박자-초과 마디 중 11개): 원본 페이지에는
    없는 선행 쉼표를 Audiveris가 만들어내 마디 박자합이 초과됐다. 그 쉼표를
    빼면 정확히 마디 길이가 맞아떨어지는 경우만 좁게 제거한다 — 그래야 실제
    있는 쉼표(빼도 안 맞아떨어짐, test_rest_represented_as_silent_beat가
    회귀를 막음)는 건드리지 않는다.
    """
    if not events or not events[0].is_rest:
        return events
    total = sum(e.ql for e in events)
    if abs(total - expected_ql) < 1e-6:
        return events
    first_ql = events[0].ql
    if abs((total - first_ql) - expected_ql) < 1e-6:
        logger.warning(
            "마디 박자 초과(%.3f > %.3f) — 유령 선행 쉼표(%.3f박) 제거",
            total, expected_ql, first_ql,
        )
        return events[1:]
    return events


def _extract_tempo(score) -> Optional[int]:
    """악보 최초 템포 마킹(BPM)을 4분음표 기준으로 환산해 반환한다.

    referent가 4분음표가 아닌 마킹(예: 점4분음표=76)도 getQuarterBPM()으로
    정규화한다. 마킹이 없으면 None(호출부가 PyGuitarPro 기본값 120을 유지).
    """
    marks = score.flatten().getElementsByClass(m21tempo.MetronomeMark)
    if not marks:
        return None
    bpm = marks[0].getQuarterBPM()
    if not bpm or bpm <= 0:
        return None
    return round(bpm)


def _build_tempo_changes(part) -> Dict[int, int]:
    """최초 이후의 곡중간 템포 변화를 (id(음표) → BPM)으로 매핑한다.

    최초 템포는 song.tempo(_extract_tempo)가 이미 담당하므로 여기서는
    두 번째 마킹부터 다룬다. 각 마킹이 적용되는 첫 음표에 표시해두면,
    _build_song이 그 음표의 beat에 MixTableChange(tempo=...)를 붙인다.
    """
    marks = sorted(
        part.recurse().getElementsByClass(m21tempo.MetronomeMark),
        key=lambda mm: mm.getOffsetInHierarchy(part),
    )
    if len(marks) < 2:
        return {}

    all_notes = list(part.recurse().getElementsByClass((m21note.Note, m21chord.Chord)))
    offsets = [float(n.getOffsetInHierarchy(part)) for n in all_notes]

    result: Dict[int, int] = {}
    for mm in marks[1:]:
        bpm = mm.getQuarterBPM()
        if not bpm or bpm <= 0:
            continue
        mark_offset = float(mm.getOffsetInHierarchy(part))
        candidates = [(off, n) for off, n in zip(offsets, all_notes) if off >= mark_offset]
        if not candidates:
            continue
        target_note = min(candidates, key=lambda pair: pair[0])[1]
        result[id(target_note)] = round(bpm)
    return result


def _collect_lyrics(score) -> Tuple[Optional[int], str]:
    """악보 전체에서 가사를 순서대로 모아 한 줄로 합친다(1절만, YAGNI).

    음절이 이어지면(syllabic이 'middle'|'end') 앞 토큰에 공백 없이 '+'로 붙인다
    (GP 관례). 여러 줄(verse) 지원은 안 함 — 첫 줄만 채운다(1절 ly.number==1만).
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
                if ly.number != 1:
                    continue
                if ly.syllabic in ("middle", "end") and tokens:
                    tokens[-1] = tokens[-1] + "+" + ly.text
                else:
                    tokens.append(ly.text)
    return starting_measure, " ".join(tokens)


def _read_xml_root(xml_path: str) -> ET.Element:
    """일반 .musicxml/.xml과 압축된 .mxl(zip 컨테이너) 둘 다 지원해서 루트를 반환한다.

    Audiveris는 기본적으로 .mxl(zip)로 내보내는데(pdf_to_musicxml이 .mxl을
    .xml보다 우선 선택), .mxl은 XML이 아니라 zip이라 ET.parse에 그대로
    넘기면 "not well-formed" 파싱 에러가 난다 — 실사용 입력 대부분에서
    _scan_raw_technicals가 항상 조용히 실패하고 있었다(예외는 호출부에서
    잡아 변환 자체는 안 죽지만, 벤드/팜뮤트/비브라토 감지가 통째로 빠짐).
    """
    if xml_path.endswith(".mxl"):
        with zipfile.ZipFile(xml_path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile_el = container.find(".//rootfile")
            rootfile = rootfile_el.get("full-path") if rootfile_el is not None else None
            if not rootfile:
                raise ValueError(f".mxl 컨테이너에서 rootfile을 못 찾음: {xml_path}")
            return ET.fromstring(zf.read(rootfile))
    return ET.parse(xml_path).getroot()


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

        chord_syms = list(m.recurse().getElementsByClass(m21harmony.ChordSymbol))
        chord_name = chord_syms[0].figure if chord_syms else None

        direction = None
        for rm in m.recurse().getElementsByClass(m21repeat.RepeatExpressionMarker):
            direction = _REPEAT_MARKER_TO_GP.get(type(rm))
            if direction:
                break
        from_direction = None
        for rc in m.recurse().getElementsByClass(m21repeat.RepeatExpressionCommand):
            from_direction = _REPEAT_COMMAND_TO_GP.get(type(rc))
            if from_direction:
                break

        expected_ql = numerator * 4.0 / denominator
        voice_streams = list(m.voices)[:2] if m.hasVoices() else [m]
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
                    hairpin_velocities=hairpin_velocities,
                    tempo_changes=tempo_changes,
                ),
                expected_ql,
            )
            for voice_index, vs in enumerate(voice_streams)
        ]
        # 이 마디 voices[0]에서 마지막으로 설정된 velocity를 다음 마디로 이어받는다.
        for ev in voices_events[0]:
            if ev.velocity is not None:
                running_velocity = ev.velocity

        result.append(MeasureData(
            numerator, denominator, key_fifths, voices_events,
            is_repeat_open=is_repeat_open,
            repeat_close=repeat_close,
            repeat_alternative=repeat_alternative,
            chord_name=chord_name,
            direction=direction,
            from_direction=from_direction,
        ))

    # 곡 전체에서 2번째 보이스가 단 한 마디라도 쓰였다면, 그 보이스를 안 쓰는
    # 다른 마디들도 voices 리스트에 빈 배열로라도 자리를 만들어둔다 — 그래야
    # _fill_measure가 그 마디의 2번째 보이스에도 _fill_voice를 호출해서
    # "완전히 빈 배열 대신 마디 전체 쉼표 비트"로 채워준다(안 그러면 그 마디는
    # voices 길이가 1인 채로 남아 2번째 보이스 자체가 구성 안 되고, alphaTab이
    # 이후 로드 시 "Cannot read properties of undefined (reading 'beats')"로
    # 죽는다 — 실사례로 재현 확인).
    if any(len(md.voices) >= 2 for md in result):
        for md in result:
            while len(md.voices) < 2:
                md.voices.append([])

    return result


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

        build_headers=False인 트랙은 gpm.Track 생성 시점에 이미
        song.measureHeaders(트랙 0이 먼저 다 만들어놓음) 개수만큼 빈 Measure
        스텁이 자동으로 채워져 있다(PyGuitarPro Track 생성자 동작) — 그래서
        여기서 새 Measure를 만들어 append하면 안 되고, 이미 존재하는 스텁을
        인덱스로 찾아 그 자리에서 채워야 한다(안 그러면 실제 내용이 뒤로 밀려
        GP5 writer가 못 읽는 위치에 남는 버그가 생긴다).
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
                m = gpm.Measure(cur_track, mh)
                cur_track.measures.append(m)
            else:
                mh = song.measureHeaders[i - 1]
                m = cur_track.measures[i - 1]

            _fill_measure(m, md, allow_hints)
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


def musicxml_to_gp5(
    xml_path: str,
    gp5_path: str,
    timeout: int = 0,
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> str:
    """MusicXML을 .gp5로 변환하고 출력 경로를 반환한다.

    Parameters
    ----------
    xml_path:
        입력 MusicXML(.musicxml 또는 .mxl) 파일 경로.
    gp5_path:
        출력 .gp5 파일 경로.
    timeout:
        오케스트레이터 호환용 파라미터. 순수 Python 구현이므로 사용하지 않는다.
    tab_hints:
        탭보표에서 읽은 (현 번호, 프렛) 목록. 음표 개수와 정확히 일치할 때만
        휴리스틱(최저프렛) 대신 그대로 쓴다. None이거나 개수가 다르면 무시한다.

    Returns
    -------
    str
        생성된 .gp5 파일의 경로.

    Raises
    ------
    GpConvertError
        음표가 없거나 파일 생성에 실패한 경우.
    """
    try:
        score = converter.parse(xml_path)
    except Exception as e:
        raise GpConvertError("MusicXML 파싱 실패") from e

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

    # ponytail: 템포 추출 실패가 전체 변환을 막으면 안 됨. 실패 시 기본값(120) 유지.
    try:
        tempo = _extract_tempo(score)
        if tempo is not None:
            song.tempo = tempo
    except Exception:
        logger.warning("템포 추출 실패 — 기본값(120bpm) 유지", exc_info=True)

    # ponytail: 메타데이터 추출 실패가 전체 변환을 막으면 안 됨. 실패 시 빈 값 유지.
    # music21은 <identification><creator type="composer">가 없어도 자체 기본값
    # "Music21"을 composer로 채워 넣는다(알려진 동작) — 그대로 쓰면 작곡가 정보
    # 없는 곡마다 엉뚱하게 "Music21"이 아티스트로 찍히므로 걸러낸다.
    try:
        if score.metadata is not None:
            song.title = score.metadata.title or ''
            composer = score.metadata.composer or ''
            song.artist = composer if composer != 'Music21' else ''
    except Exception:
        logger.warning("곡 메타데이터 추출 실패 — 제목/아티스트 없이 계속 진행", exc_info=True)

    # ponytail: 악기 추출 실패가 전체 변환을 막으면 안 됨. 실패 시 기본값(어쿠스틱 기타) 유지.
    # Audiveris는 표준악보에서 실제 악기를 알아낼 방법이 없으면(대부분의 경우)
    # "Voice Oohs"/midi-program 54를 고정 placeholder로 찍어낸다(실측: 이
    # 프로젝트에서 시도한 모든 실제 변환이 소스 PDF 내용과 무관하게 예외 없이
    # 동일한 값이었음) — 이걸 그대로 쓰면 기타 변환기인데 결과가 전부 보컬
    # 음색으로 재생된다. 이 특정 placeholder는 걸러내고 기본값을 유지한다.
    try:
        inst = score.parts[0].getInstrument()
        if inst.instrumentName != 'Voice Oohs' and inst.midiProgram is not None:
            song.tracks[0].channel.instrument = inst.midiProgram
    except Exception:
        logger.warning("악기 정보 추출 실패 — 기본 음색 유지", exc_info=True)

    # ponytail: 가사 매핑 실패가 전체 변환을 막으면 안 됨. 실패 시 경고만 남기고 계속 진행.
    try:
        starting_measure, lyrics_text = _collect_lyrics(score)
    except Exception:
        logger.warning("가사 추출 실패 — 가사 없이 계속 진행", exc_info=True)
        starting_measure, lyrics_text = None, ""

    if lyrics_text:
        song.lyrics.trackChoice = 0
        song.lyrics.lines[0].startingMeasure = 1 if starting_measure is None else starting_measure
        song.lyrics.lines[0].lyrics = lyrics_text

    try:
        guitarpro.write(song, gp5_path)
    except Exception as e:
        raise GpConvertError("GP5 쓰기 실패") from e

    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise GpConvertError("GP5 쓰기 실패")

    return gp5_path
