"""
guitar-tab-omr tokenText → Guitar Pro 5 변환기

토큰 포맷:
  TS_4_4                           박자표 (분자_분모)
  BAR / END_BAR                    마디 경계
  DOUBLE_BAR                       겹세로줄 (무시)
  BEAT DUR_N [DOTS_1] [REST] [DYN_X] [BTECH_STRUM_DOWN|UP] [N_Ss_Ff ...]  비트
  DUR_{1|2|4|8|16|32}             음표 길이
  DOTS_1                           점음표 (지속시간 × 1.5)
  REST                             쉼표
  N_S{1-6}_F{0-24}                음표 (현, 프렛)
  N_S{1-6}_FX                     뮤트음 (퍼커시브 X)
  DYN_{ppp|pp|p|mp|mf|f|ff|fff}  다이나믹
  BTECH_STRUM_{DOWN|UP}           스트럼 방향
  NTECH_TIE_DEST                  타이 도착음
  NTECH_LEGATO_ORIGIN             해머온/풀오프 시작
  NTECH_SLIDE_OUT_{1|2|4}         슬라이드 아웃 (1=shift, 2=legato, 4=outUp)
  NTECH_SLIDE_IN_{1|2}            슬라이드 인 (1=fromBelow, 2=fromAbove)
  NTECH_GHOST                     고스트 노트
  NTECH_HARMONIC_VALUE_{n}        하모닉스
  TUPLET_3_2                      셋잇단음 (미지원, 스킵)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus, SlideType

logger = logging.getLogger(__name__)

_DUR_MAP = {"1": 1, "2": 2, "4": 4, "8": 8, "16": 16, "32": 32, "64": 64}
_DYN_MAP = {
    "ppp": 15, "pp": 31, "p": 47, "mp": 63,
    "mf": 79, "f": 95, "ff": 111, "fff": 127,
}
_NOTE_RE = re.compile(r"N_S(\d+)_F(\d+|X)$")

# 음표 길이 → 1/64분음표 단위 환산
_DUR_UNITS: dict = {1: 64, 2: 32, 4: 16, 8: 8, 16: 4, 32: 2, 64: 1}
# 마디를 정확히 채울 때 사용할 음표 후보 (긴 것부터)
_DUR_FILL_ORDER = [1, 2, 4, 8, 16, 32]

_SLIDE_OUT_MAP: dict = {
    "1": SlideType.shiftSlideTo,
    "2": SlideType.legatoSlideTo,
    "4": SlideType.outUpwards,
}
_SLIDE_IN_MAP: dict = {
    "1": SlideType.intoFromBelow,
    "2": SlideType.intoFromAbove,
}


@dataclass
class _NoteData:
    string: int
    fret: int
    is_dead: bool = False
    is_tie: bool = False
    is_ghost: bool = False
    is_harmonic: bool = False
    legato: bool = False
    slides: List[SlideType] = field(default_factory=list)


@dataclass
class _BeatData:
    duration_value: int = 4
    is_rest: bool = False
    is_dotted: bool = False
    velocity: int = 95
    strum_down: Optional[bool] = None
    notes: List[_NoteData] = field(default_factory=list)


@dataclass
class _MeasureData:
    time_sig_num: int = 4
    time_sig_den: int = 4
    beats: List[_BeatData] = field(default_factory=list)


def _apply_ntech(token: str, beat: _BeatData) -> None:
    """NTECH_* 토큰을 현재 비트의 마지막 음표에 적용한다."""
    if not beat.notes:
        logger.warning("NTECH 토큰이 음표 없이 등장: %s", token)
        return
    note = beat.notes[-1]
    if token in ("NTECH_TIE_DEST", "NTECH_TIE_START"):
        # TIE_DEST → NoteType.tie 로 변환; TIE_START는 일반 음표로 유지
        if token == "NTECH_TIE_DEST":
            note.is_tie = True
    elif token == "NTECH_LEGATO_ORIGIN":
        note.legato = True
    elif token == "NTECH_GHOST":
        note.is_ghost = True
    elif token.startswith("NTECH_HARMONIC_VALUE_"):
        note.is_harmonic = True
    elif token.startswith("NTECH_SLIDE_OUT_"):
        suffix = token.rsplit("_", 1)[-1]
        slide_type = _SLIDE_OUT_MAP.get(suffix)
        if slide_type is not None:
            note.slides.append(slide_type)
        else:
            logger.warning("알 수 없는 SLIDE_OUT 타입 스킵: %s", token)
    elif token.startswith("NTECH_SLIDE_IN_"):
        suffix = token.rsplit("_", 1)[-1]
        slide_type = _SLIDE_IN_MAP.get(suffix)
        if slide_type is not None:
            note.slides.append(slide_type)
        else:
            logger.warning("알 수 없는 SLIDE_IN 타입 스킵: %s", token)
    else:
        logger.warning("알 수 없는 NTECH 토큰 스킵: %s", token)


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

                    elif token == "DOTS_1":
                        current_beat.is_dotted = True

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

                    elif token == "TUPLET_3_2":
                        pass  # 셋잇단음 — GP5 tuplet 지원 미구현, 스킵

                    elif token.startswith("NTECH_"):
                        _apply_ntech(token, current_beat)

                    else:
                        m = _NOTE_RE.match(token)
                        if m:
                            fret_str = m.group(2)
                            is_dead = fret_str == "X"
                            fret = 0 if is_dead else int(fret_str)
                            current_beat.notes.append(
                                _NoteData(string=int(m.group(1)), fret=fret, is_dead=is_dead)
                            )
                        else:
                            logger.warning("알 수 없는 토큰 스킵: %s", token)

    flush_measure()
    return measures


def _build_gp5_song(measures: List[_MeasureData]) -> guitarpro.Song:
    """_MeasureData 리스트를 PyGuitarPro Song 객체로 조립한다."""
    song = gpm.Song()
    track = song.tracks[0]
    track.name = "Guitar"

    def _beat_units(bdata: _BeatData) -> float:
        u = _DUR_UNITS.get(bdata.duration_value, 16)
        return u * 1.5 if bdata.is_dotted else float(u)

    def _fill_measure(measure: gpm.Measure, mdata: _MeasureData) -> None:
        voice = measure.voices[0]
        voice.beats = []
        expected = (mdata.time_sig_num / mdata.time_sig_den) * 64
        accumulated = 0.0

        for bdata in mdata.beats:
            units = _beat_units(bdata)
            if accumulated + units > expected + 0.01:
                # 마디 용량 초과 — 해당 비트부터 버림
                logger.debug("마디 용량 초과 비트 제거: dur=%s (%.1f/%.1f)",
                             bdata.duration_value, accumulated, expected)
                break
            accumulated += units

            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = bdata.duration_value
            if bdata.is_dotted:
                beat.duration.isDotted = True

            if bdata.is_rest or not bdata.notes:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                for nd in bdata.notes:
                    gnote = Note(beat)
                    gnote.value = nd.fret
                    # guitar-tab-omr: S1=low E(bottom), S6=high E(top)
                    # PyGuitarPro: string 1=high E(top), string 6=low E(bottom)
                    gnote.string = 7 - nd.string
                    gnote.velocity = bdata.velocity

                    if nd.is_dead:
                        gnote.type = NoteType.dead
                    elif nd.is_tie:
                        gnote.type = NoteType.tie
                    else:
                        gnote.type = NoteType.normal

                    if nd.slides:
                        gnote.effect.slides = nd.slides
                    if nd.legato:
                        gnote.effect.hammer = True
                    if nd.is_ghost:
                        gnote.effect.ghostNote = True
                    if nd.is_harmonic:
                        gnote.effect.harmonic = gpm.NaturalHarmonic()

                    beat.notes.append(gnote)

            voice.beats.append(beat)

        # 남은 공간을 쉼표로 채움 (마디가 비거나 부족한 경우)
        remaining = expected - accumulated
        if remaining > 0.01:
            for dur_val in _DUR_FILL_ORDER:
                fill_units = _DUR_UNITS[dur_val]
                while remaining >= fill_units - 0.01:
                    rest = Beat(voice)
                    rest.status = BeatStatus.rest
                    rest.duration = gpm.Duration()
                    rest.duration.value = dur_val
                    rest.notes = []
                    voice.beats.append(rest)
                    remaining -= fill_units

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
