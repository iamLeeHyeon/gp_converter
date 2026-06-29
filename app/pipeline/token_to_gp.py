"""
guitar-tab-omr tokenText → Guitar Pro 5 변환기

토큰 포맷:
  TS_4_4                           박자표 (분자_분모)
  BAR / END_BAR                    마디 경계
  DOUBLE_BAR                       겹세로줄 (무시)
  BEAT DUR_N [REST] [DYN_X] [BTECH_STRUM_DOWN|UP] [N_Ss_Ff ...]  비트
  DUR_{1|2|4|8|16|32}             음표 길이
  REST                             쉼표
  N_S{1-6}_F{0-24}                음표 (현, 프렛)
  DYN_{ppp|pp|p|mp|mf|f|ff|fff}  다이나믹
  BTECH_STRUM_{DOWN|UP}           스트럼 방향
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus

logger = logging.getLogger(__name__)

_DUR_MAP = {"1": 1, "2": 2, "4": 4, "8": 8, "16": 16, "32": 32}
_DYN_MAP = {
    "ppp": 15, "pp": 31, "p": 47, "mp": 63,
    "mf": 79, "f": 95, "ff": 111, "fff": 127,
}
_NOTE_RE = re.compile(r"N_S(\d+)_F(\d+)$")


@dataclass
class _BeatData:
    duration_value: int = 4
    is_rest: bool = False
    velocity: int = 95
    strum_down: Optional[bool] = None
    notes: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class _MeasureData:
    time_sig_num: int = 4
    time_sig_den: int = 4
    beats: List[_BeatData] = field(default_factory=list)


def _parse_token_texts(token_texts: List[str]) -> List[_MeasureData]:
    """tokenText 리스트를 파싱해 마디 데이터 리스트를 반환한다."""
    measures: List[_MeasureData] = []
    current_ts_num, current_ts_den = 4, 4
    current_measure: Optional[_MeasureData] = None
    current_beat: Optional[_BeatData] = None

    def flush_beat() -> None:
        nonlocal current_beat
        if current_beat is not None and current_measure is not None:
            current_measure.beats.append(current_beat)
            current_beat = None

    def flush_measure() -> None:
        nonlocal current_measure
        if current_measure is not None:
            flush_beat()
            measures.append(current_measure)
            current_measure = None

    for token_text in token_texts:
        for line in token_text.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("TS_"):
                parts = line.split("_")
                if len(parts) == 3:
                    try:
                        current_ts_num = int(parts[1])
                        current_ts_den = int(parts[2])
                    except ValueError:
                        logger.warning("박자표 파싱 실패: %s", line)

            elif line == "BAR":
                flush_measure()
                current_measure = _MeasureData(
                    time_sig_num=current_ts_num,
                    time_sig_den=current_ts_den,
                )

            elif line == "END_BAR":
                flush_measure()

            elif line == "DOUBLE_BAR":
                pass

            elif line.startswith("BEAT"):
                flush_beat()
                if current_measure is None:
                    current_measure = _MeasureData(
                        time_sig_num=current_ts_num,
                        time_sig_den=current_ts_den,
                    )
                current_beat = _BeatData()
                tokens = line.split()[1:]
                for token in tokens:
                    if token.startswith("DUR_"):
                        val = token[4:]
                        if val in _DUR_MAP:
                            current_beat.duration_value = _DUR_MAP[val]
                        else:
                            logger.warning("알 수 없는 DUR 토큰: %s", token)

                    elif token == "REST":
                        current_beat.is_rest = True

                    elif token.startswith("DYN_"):
                        dyn = token[4:].lower()
                        if dyn in _DYN_MAP:
                            current_beat.velocity = _DYN_MAP[dyn]
                        else:
                            logger.warning("알 수 없는 DYN 토큰: %s", token)

                    elif token == "BTECH_STRUM_DOWN":
                        current_beat.strum_down = True

                    elif token == "BTECH_STRUM_UP":
                        current_beat.strum_down = False

                    else:
                        m = _NOTE_RE.match(token)
                        if m:
                            current_beat.notes.append((int(m.group(1)), int(m.group(2))))
                        else:
                            logger.warning("알 수 없는 토큰 스킵: %s", token)

    flush_measure()
    return measures


def _build_gp5_song(measures: List[_MeasureData]) -> guitarpro.Song:
    """_MeasureData 리스트를 PyGuitarPro Song 객체로 조립한다."""
    song = gpm.Song()
    track = song.tracks[0]
    track.name = "Guitar"

    def _fill_measure(measure: gpm.Measure, mdata: _MeasureData) -> None:
        voice = measure.voices[0]
        voice.beats = []
        for bdata in mdata.beats:
            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = bdata.duration_value

            if bdata.is_rest or not bdata.notes:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                for string_num, fret_num in bdata.notes:
                    gnote = Note(beat)
                    gnote.value = fret_num
                    # guitar-tab-omr: S1=low E(bottom), S6=high E(top)
                    # PyGuitarPro: string 1=high E(top), string 6=low E(bottom)
                    gnote.string = 7 - string_num
                    gnote.type = NoteType.normal
                    gnote.velocity = bdata.velocity
                    beat.notes.append(gnote)

            voice.beats.append(beat)

        if not voice.beats:
            beat = Beat(voice)
            beat.status = BeatStatus.rest
            beat.duration = gpm.Duration()
            beat.duration.value = 4
            beat.notes = []
            voice.beats.append(beat)

    first_mh = song.measureHeaders[0]
    first_mh.number = 1
    first_mh.timeSignature.numerator = measures[0].time_sig_num
    first_mh.timeSignature.denominator.value = measures[0].time_sig_den
    _fill_measure(track.measures[0], measures[0])

    start = first_mh.start + first_mh.length
    for i, mdata in enumerate(measures[1:], start=2):
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = mdata.time_sig_num
        mh.timeSignature.denominator.value = mdata.time_sig_den
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_measure(m, mdata)
        track.measures.append(m)

        start += mh.length

    return song


def token_texts_to_gp5(token_texts: List[str], out_path: str) -> str:
    """tokenText 리스트를 파싱해 .gp5 파일로 저장하고 경로를 반환한다.

    Raises
    ------
    ValueError
        파싱된 마디가 없는 경우.
    """
    measures = _parse_token_texts(token_texts)
    if not measures:
        raise ValueError("파싱된 마디가 없습니다.")
    song = _build_gp5_song(measures)
    guitarpro.write(song, out_path)
    return out_path
