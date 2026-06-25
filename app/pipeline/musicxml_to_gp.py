"""
MusicXML → Guitar Pro 5 변환기 (PyGuitarPro 기반)

설계 결정:
- 코드(Chord): 코드에서 가장 높은 음(최대 MIDI 값)만 사용한다. MVP 단순화.
- 현/프렛 배정: MIDI 값을 줄 수 있는 모든 현에서 유효(0~24 프렛)한 것 중
  가장 낮은 프렛 번호를 선택한다. 동점이면 가장 높은 줄 번호(낮은 음) 우선.
  유효한 현이 없으면(MIDI가 범위 밖) 해당 음표를 건너뛴다.
- 마디 그룹화: MusicXML의 실제 마디 경계를 그대로 따른다. 박자/조표가 그
  마디에 명시돼 있지 않으면 이전 마디 값을 이어받는다(carry-forward).
- 이음줄(tie): 이어지는 두 번째 이후 음은 길이를 합치지 않고(GP5는 마디당
  박자 총합이 고정이라 합치면 깨짐) NoteType.tie로만 표시한다.
- 점음표: quarterLength가 점음표 값(1.5×기본값)이면 isDotted=True로 설정한다.
- 매핑 불가 박자: 가장 가까운 기본 박자값으로 내림한다(문서화).

주의: Beat.status를 BeatStatus.normal로 명시해야 한다. 기본값(empty)으로 두면
PyGuitarPro가 GP5 작성 시 같은 마디의 비트들을 하나로 합쳐 음표를 전부
동시발음 화음으로 뭉개버린다(순차 음표 구조가 깨짐).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus
from music21 import converter, note as m21note, chord as m21chord, stream as m21stream


logger = logging.getLogger(__name__)


class GpConvertError(Exception):
    """MusicXML → GP 변환 중 발생하는 오류."""


# 표준 기타 튜닝: (줄 번호, MIDI 값) — 1=high E, 6=low E
_STANDARD_STRINGS: List[Tuple[int, int]] = [
    (1, 64), (2, 59), (3, 55), (4, 50), (5, 45), (6, 40)
]

# quarterLength → GP Duration.value 매핑
_QL_TO_GPV = {4.0: 1, 2.0: 2, 1.0: 4, 0.5: 8, 0.25: 16, 0.125: 32}
_DOTTED_QL_TO_GPV = {3.0: 1, 1.5: 2, 0.75: 4, 0.375: 8, 0.1875: 16}

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


@dataclass
class NoteEvent:
    """한 음표(또는 화음 최고음)의 (음높이, 길이, 이음줄 연속 여부)."""

    midi: int
    ql: float
    tied: bool = False  # True면 직전 음에서 이어지는 연속음(NoteType.tie)


@dataclass
class MeasureData:
    """한 마디의 박자/조표/음표 목록."""

    numerator: int
    denominator: int
    key_fifths: int
    events: List[NoteEvent] = field(default_factory=list)


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


def _collect_notes(score) -> List[MeasureData]:
    """첫 번째 파트에서 마디 단위 (박자, 조표, 음표) 목록을 추출한다.

    박자/조표는 명시된 마디가 없으면 이전 마디 값을 이어받는다(carry-forward).
    Chord는 최고음(최대 MIDI) 하나만 사용한다.
    이음줄로 이어지는(continue/stop) 음은 tied=True로 표시한다.
    """
    part = score.parts[0]
    measures = list(part.getElementsByClass(m21stream.Measure))

    result: List[MeasureData] = []
    numerator, denominator, key_fifths = 4, 4, 0

    for m in measures:
        if m.timeSignature is not None:
            numerator = m.timeSignature.numerator
            denominator = m.timeSignature.denominator
        if m.keySignature is not None:
            key_fifths = m.keySignature.sharps

        events: List[NoteEvent] = []
        for n in m.recurse().notes:
            tied = n.tie is not None and n.tie.type in ("continue", "stop")
            if isinstance(n, m21note.Note):
                midi = n.pitch.midi
            elif isinstance(n, m21chord.Chord):
                midi = max(p.midi for p in n.pitches)
            else:
                continue
            midi += _GUITAR_WRITTEN_TO_SOUNDING_OFFSET
            events.append(NoteEvent(midi, float(n.duration.quarterLength), tied))

        result.append(MeasureData(numerator, denominator, key_fifths, events))

    return result


def _build_song(
    measures_data: List[MeasureData],
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> guitarpro.Song:
    """마디 목록으로 GP Song 객체를 생성한다.

    tab_hints가 전체 음표 개수와 같으면 각 음표에 명시적 (현,프렛)을 쓴다.
    길이가 다르면 tab_hints를 무시하고 기존 휴리스틱(최저프렛)을 쓴다.
    """
    total_notes = sum(len(m.events) for m in measures_data)
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

    if not measures_data:
        return song

    def _apply_header(mh: gpm.MeasureHeader, md: MeasureData) -> None:
        mh.timeSignature.numerator = md.numerator
        mh.timeSignature.denominator.value = md.denominator
        fifths = max(-8, min(8, md.key_fifths))
        mh.keySignature = _FIFTHS_TO_KEYSIG[fifths]

    def _fill_measure(measure: gpm.Measure, md: MeasureData) -> None:
        voice = measure.voices[0]
        beats: List[Beat] = []
        for ev in md.events:
            hint = _next_hint()
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(ev.midi, strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    logger.warning("MIDI %d는 어떤 현으로도 표현할 수 없어 건너뜀", ev.midi)
                    continue
                snum, fret = sf
            gp_val, is_dotted = _ql_to_gp_duration(ev.ql)

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
        voice.beats = beats

    first_mh = song.measureHeaders[0]
    first_measure = track.measures[0]
    _apply_header(first_mh, measures_data[0])
    _fill_measure(first_measure, measures_data[0])

    start = first_mh.start + first_mh.length
    for i, md in enumerate(measures_data[1:], start=2):
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        _apply_header(mh, md)
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_measure(m, md)
        track.measures.append(m)

        start += mh.length

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
        measures_data = _collect_notes(score)
    except Exception as e:
        raise GpConvertError("음표 추출 실패") from e

    if not measures_data or not any(m.events for m in measures_data):
        raise GpConvertError("변환할 음표 없음")

    try:
        song = _build_song(measures_data, tab_hints=tab_hints)
        guitarpro.write(song, gp5_path)
    except Exception as e:
        raise GpConvertError("GP5 쓰기 실패") from e

    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise GpConvertError("GP5 쓰기 실패")

    return gp5_path
