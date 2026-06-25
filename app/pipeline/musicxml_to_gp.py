"""
MusicXML → Guitar Pro 5 변환기 (PyGuitarPro 기반)

설계 결정:
- 코드(Chord): 코드에서 가장 높은 음(최대 MIDI 값)만 사용한다. MVP 단순화.
- 현/프렛 배정: MIDI 값을 줄 수 있는 모든 현에서 유효(0~24 프렛)한 것 중
  가장 낮은 프렛 번호를 선택한다. 동점이면 가장 높은 줄 번호(낮은 음) 우선.
  유효한 현이 없으면(MIDI가 범위 밖) 해당 음표를 건너뛴다.
- 마디 그룹화: 4/4박자 기준 quarterLength 4.0씩 묶어 마디를 생성한다.
  한 마디가 채워지지 않으면 마지막 마디에 나머지 음표를 넣는다.
- 점음표: quarterLength가 점음표 값(1.5×기본값)이면 isDotted=True로 설정한다.
- 매핑 불가 박자: 가장 가까운 기본 박자값으로 내림한다(문서화).

주의: Beat.status를 BeatStatus.normal로 명시해야 한다. 기본값(empty)으로 두면
PyGuitarPro가 GP5 작성 시 같은 마디의 비트들을 하나로 합쳐 음표를 전부
동시발음 화음으로 뭉개버린다(순차 음표 구조가 깨짐).
"""

from __future__ import annotations

import os
from fractions import Fraction
from typing import List, Optional, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus
from music21 import converter, note as m21note, chord as m21chord


class GpConvertError(Exception):
    """MusicXML → GP 변환 중 발생하는 오류."""


# 표준 기타 튜닝: (줄 번호, MIDI 값) — 1=high E, 6=low E
_STANDARD_STRINGS: List[Tuple[int, int]] = [
    (1, 64), (2, 59), (3, 55), (4, 50), (5, 45), (6, 40)
]

# quarterLength → GP Duration.value 매핑
_QL_TO_GPV = {4.0: 1, 2.0: 2, 1.0: 4, 0.5: 8, 0.25: 16, 0.125: 32}
_DOTTED_QL_TO_GPV = {3.0: 1, 1.5: 2, 0.75: 4, 0.375: 8, 0.1875: 16}

# 4/4 한 마디 = 4.0 quarterLength
_BAR_QL = 4.0


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


def _collect_notes(score) -> List[Tuple[int, float]]:
    """첫 번째 파트에서 (MIDI, quarterLength) 목록을 추출한다.

    Chord는 최고음(최대 MIDI) 하나만 사용한다.
    """
    part = score.parts[0]
    result: List[Tuple[int, float]] = []
    for n in part.recurse().notes:
        if isinstance(n, m21note.Note):
            result.append((n.pitch.midi, float(n.duration.quarterLength)))
        elif isinstance(n, m21chord.Chord):
            # 최고음만 사용
            midi = max(p.midi for p in n.pitches)
            result.append((midi, float(n.duration.quarterLength)))
    return result


def _build_song(
    note_data: List[Tuple[int, float]],
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> guitarpro.Song:
    """(MIDI, quarterLength) 목록으로 GP Song 객체를 생성한다.

    tab_hints가 note_data와 길이가 같으면 각 음표에 명시적 (현,프렛)을 쓴다.
    길이가 다르면 tab_hints를 무시하고 기존 휴리스틱(최저프렛)을 쓴다.
    """
    if tab_hints is not None and len(tab_hints) != len(note_data):
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

    hints = tab_hints if tab_hints is not None else [None] * len(note_data)
    items = list(zip(note_data, hints))

    # (음표,힌트) 쌍을 4/4 마디 단위로 그룹화
    measures_items: List[List[Tuple[Tuple[int, float], Optional[Tuple[int, int]]]]] = []
    current_bar: List[Tuple[Tuple[int, float], Optional[Tuple[int, int]]]] = []
    current_ql = 0.0

    for (midi, ql), hint in items:
        current_bar.append(((midi, ql), hint))
        current_ql += ql
        if current_ql >= _BAR_QL:
            measures_items.append(current_bar)
            current_bar = []
            current_ql = 0.0

    if current_bar:
        measures_items.append(current_bar)

    if not measures_items:
        return song

    first_mh = song.measureHeaders[0]
    first_measure = track.measures[0]

    def _fill_measure(measure: gpm.Measure, bar_items) -> None:
        voice = measure.voices[0]
        beats: List[Beat] = []
        for (midi, ql), hint in bar_items:
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(midi, strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    continue
                snum, fret = sf
            gp_val, is_dotted = _ql_to_gp_duration(ql)

            beat = Beat(voice=voice)
            beat.status = BeatStatus.normal
            beat.duration.value = gp_val
            beat.duration.isDotted = is_dotted

            gnote = Note(beat=beat)
            gnote.value = fret
            gnote.string = snum
            gnote.type = NoteType.normal
            beat.notes = [gnote]
            beats.append(beat)
        voice.beats = beats

    _fill_measure(first_measure, measures_items[0])

    start = first_mh.start + first_mh.length
    for i, bar_items in enumerate(measures_items[1:], start=2):
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_measure(m, bar_items)
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
        raise GpConvertError("gp 생성 실패") from e

    try:
        note_data = _collect_notes(score)
    except Exception as e:
        raise GpConvertError("gp 생성 실패") from e

    if not note_data:
        raise GpConvertError("변환할 음표 없음")

    try:
        song = _build_song(note_data, tab_hints=tab_hints)
        guitarpro.write(song, gp5_path)
    except Exception as e:
        raise GpConvertError("gp 생성 실패") from e

    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise GpConvertError("gp 생성 실패")

    return gp5_path
