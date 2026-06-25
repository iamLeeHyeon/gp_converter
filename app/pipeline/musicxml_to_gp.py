"""
MusicXML → Guitar Pro 5 변환기 (PyGuitarPro 기반)

설계 결정:
- 코드(Chord): 코드에서 가장 높은 음(최대 MIDI 값)만 사용한다. MVP 단순화.
- 현/프렛 배정: MIDI 값을 줄 수 있는 모든 현에서 유효(0~24 프렛)한 것 중
  가장 낮은 프렛 번호를 선택한다. 동점이면 가장 높은 줄 번호(낮은 음) 우선.
  유효한 현이 없으면(MIDI가 범위 밖) 해당 음표를 건너뛴다.
- 마디 그룹화: MusicXML의 실제 마디 경계를 그대로 따른다. 박자/조표가 그
  마디에 명시돼 있지 않으면 이전 마디 값을 이어받는다(carry-forward).
- 다성(보이스): 한 마디에 <backup>으로 만든 보이스가 여러 개면 GP5가 지원
  하는 최대 2개까지 그대로 둔다(3개 이상은 버림). 탭힌트는 voices[0](주
  멜로디)에만 적용한다.
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
# 점음표 ql = (4/value)*1.5 이므로 value = 6/ql. (예: 점8분음표 0.75ql → value=8)
_DOTTED_QL_TO_GPV = {6.0: 1, 3.0: 2, 1.5: 4, 0.75: 8, 0.375: 16, 0.1875: 32}

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
    """한 음표(또는 화음)의 (음높이 목록, 길이, 이음줄 연속 여부).

    pitches는 MIDI 내림차순(높은음 먼저) 리스트다. 단일음은 길이 1,
    화음은 길이 2 이상, 쉼표(is_rest=True)는 빈 리스트다.
    """

    pitches: List[int]
    ql: float
    tied: bool = False  # True면 직전 음에서 이어지는 연속음(NoteType.tie)
    is_rest: bool = False


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


def _collect_notes(score) -> List[MeasureData]:
    """첫 번째 파트에서 마디 단위 (박자, 조표, 보이스별 음표/쉼표) 목록을 추출한다.

    박자/조표는 명시된 마디가 없으면 이전 마디 값을 이어받는다(carry-forward).
    Chord는 최고음(최대 MIDI) 하나만 사용한다.
    이음줄로 이어지는(continue/stop) 음은 tied=True로 표시한다.
    쉼표도 길이가 있는 이벤트로 포함한다(건너뛰면 그 뒤 음표들이 마디 박자
    총합을 못 채워 GP5가 깨진다).
    한 마디에 보이스가 여러 개면(예: <backup>으로 만든 2성) GP5가 지원하는
    최대 2개까지만 voices에 담는다(3개 이상이면 나머지는 버림).
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

        expected_ql = numerator * 4.0 / denominator
        voice_streams = list(m.voices)[:2] if m.hasVoices() else [m]
        voices_events = [
            _drop_phantom_leading_rest(_extract_events(vs), expected_ql) for vs in voice_streams
        ]

        result.append(MeasureData(numerator, denominator, key_fifths, voices_events))

    return result


def _build_song(
    measures_data: List[MeasureData],
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> guitarpro.Song:
    """마디 목록으로 GP Song 객체를 생성한다.

    tab_hints는 주 멜로디(voices[0])의 음표 개수(쉼표 제외)와 같을 때만, 그
    보이스에 명시적 (현,프렛)을 쓴다. 두 번째 보이스는 항상 휴리스틱을 쓴다
    (탭보표는 한 줄짜리 멜로디만 읽으므로 다성에는 대응 불가).
    """
    total_notes = sum(
        1 for m in measures_data for ev in m.voices[0] if not ev.is_rest
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

    if not measures_data:
        return song

    def _apply_header(mh: gpm.MeasureHeader, md: MeasureData) -> None:
        mh.timeSignature.numerator = md.numerator
        mh.timeSignature.denominator.value = md.denominator
        fifths = max(-8, min(8, md.key_fifths))
        mh.keySignature = _FIFTHS_TO_KEYSIG[fifths]

    def _fill_voice(voice: gpm.Voice, events: List[NoteEvent], use_hints: bool) -> None:
        beats: List[Beat] = []
        for ev in events:
            gp_val, is_dotted = _ql_to_gp_duration(ev.ql)

            if ev.is_rest:
                beat = Beat(voice=voice)
                beat.status = BeatStatus.rest
                beat.duration.value = gp_val
                beat.duration.isDotted = is_dotted
                beat.notes = []
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
        voice.beats = beats

    def _fill_measure(measure: gpm.Measure, md: MeasureData) -> None:
        for vi, events in enumerate(md.voices):
            _fill_voice(measure.voices[vi], events, use_hints=(vi == 0))

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

    if not any(
        not ev.is_rest for m in measures_data for voice_events in m.voices for ev in voice_events
    ):
        raise GpConvertError("변환할 음표 없음")

    try:
        song = _build_song(measures_data, tab_hints=tab_hints)
        guitarpro.write(song, gp5_path)
    except Exception as e:
        raise GpConvertError("GP5 쓰기 실패") from e

    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise GpConvertError("GP5 쓰기 실패")

    return gp5_path
