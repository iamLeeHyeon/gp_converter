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
  NTECH_HARMONIC_{NATURAL|ARTIFICIAL|PINCH|SEMI|TAP|FEEDBACK}  하모닉스 종류
  NTECH_HARMONIC_VALUE_{n}        하모닉스 프렛/노드 값(종류와 별개 토큰)
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
from guitarpro.models import BeatStatus, BeatStrokeDirection, KeySignature, SlideType

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

# harmonic_type → PyGuitarPro 하모닉 클래스. 'feedback'과 미지정(None)은 GP5에
# 대응 타입이 없어 가장 가까운 natural로 대체한다(과거부터의 기본 동작 유지).
_HARMONIC_TYPE_TO_GP: dict = {
    "natural": gpm.NaturalHarmonic,
    "artificial": gpm.ArtificialHarmonic,
    "pinch": gpm.PinchHarmonic,
    "semi": gpm.SemiHarmonic,
    "tap": gpm.TappedHarmonic,
}


def _pad_voice_with_rests(voice: gpm.Voice, remaining: float) -> None:
    """마디의 남은 용량을 쉼표 비트로 채운다. voice가 완전히 비면 4분쉼표 하나를 넣는다."""
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
        rest = Beat(voice)
        rest.status = BeatStatus.rest
        rest.duration = gpm.Duration()
        rest.duration.value = 4
        rest.notes = []
        voice.beats.append(rest)


@dataclass
class _NoteData:
    string: int
    fret: int
    is_dead: bool = False
    is_tie: bool = False
    is_ghost: bool = False
    is_harmonic: bool = False
    harmonic_type: Optional[str] = None  # 'natural'|'artificial'|'pinch'|'semi'|'tap'|'feedback'
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
    elif token in (
        "NTECH_HARMONIC_NATURAL", "NTECH_HARMONIC_ARTIFICIAL", "NTECH_HARMONIC_PINCH",
        "NTECH_HARMONIC_SEMI", "NTECH_HARMONIC_TAP", "NTECH_HARMONIC_FEEDBACK",
    ):
        note.is_harmonic = True
        note.harmonic_type = token[len("NTECH_HARMONIC_"):].lower()
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
                if not tokens:
                    logger.warning("bare BEAT 토큰 (DUR 없음) → 기본 4분음표 쉼표로 처리")
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
                # 마디 용량 초과 — 이 비트 하나만 버리고 계속 진행한다(OMR이
                # 비트 하나의 길이를 잘못 읽은 경우, 그 뒤에 이어지는 정상
                # 비트들까지 통째로 버려지면 안 되므로 break 대신 skip한다).
                logger.warning("마디 용량 초과 비트 제거: dur=%s (%.1f/%.1f units)",
                               bdata.duration_value, accumulated, expected)
                continue
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
                        harmonic_cls = _HARMONIC_TYPE_TO_GP.get(nd.harmonic_type, gpm.NaturalHarmonic)
                        gnote.effect.harmonic = harmonic_cls()

                    beat.notes.append(gnote)

            if bdata.strum_down is True:
                beat.effect.pickStroke = BeatStrokeDirection.down
                beat.effect.stroke.direction = BeatStrokeDirection.down
                beat.effect.stroke.value = bdata.duration_value
            elif bdata.strum_down is False:
                beat.effect.pickStroke = BeatStrokeDirection.up
                beat.effect.stroke.direction = BeatStrokeDirection.up
                beat.effect.stroke.value = bdata.duration_value

            voice.beats.append(beat)

        # 남은 공간을 쉼표로 채움 (마디가 비거나 부족한 경우)
        _pad_voice_with_rests(voice, expected - accumulated)

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


def snapshot_to_gp5(snapshot: dict, out_path: str) -> str:
    """ScoreSnapshot JSON dict → .gp5 파일 저장.

    ScoreSnapshot 스트링 번호는 GP 컨벤션(1=high E)을 따르므로 반전 없음.

    Raises
    ------
    ValueError
        트랙 또는 마디 없는 경우.
    """
    _SLIDE_MAP = {
        "slide-shift": SlideType.shiftSlideTo,
        "slide-legato": SlideType.legatoSlideTo,
        "slide-in-above": SlideType.intoFromAbove,
        "slide-out-below": SlideType.outUpwards,
    }

    tracks_data = snapshot.get("tracks", [])
    if not tracks_data:
        raise ValueError("snapshot에 트랙 없음")
    measures_data = tracks_data[0].get("measures", [])
    if not measures_data:
        raise ValueError("snapshot에 마디 없음")

    song = gpm.Song()
    track = song.tracks[0]
    track.name = tracks_data[0].get("name", "Guitar")

    def _fill_voice_beats(voice: gpm.Voice, beats_data: list, expected: float) -> None:
        """beats_data 리스트를 voice 객체에 채운다."""
        voice.beats = []
        accumulated = 0.0

        for bdata in beats_data:
            dur_val = bdata.get("duration", 4)
            is_dotted = bdata.get("dotted", False)
            base = _DUR_UNITS.get(dur_val, 16)
            units = base * 1.5 if is_dotted else float(base)
            if accumulated + units > expected + 0.01:
                # 이 비트 하나만 버리고 계속 진행(이유는 _fill_measure 참고 —
                # 비트 하나 잘못 읽었다고 그 뒤 전부를 버리면 안 됨).
                logger.warning("snapshot 마디 초과 비트 제거: dur=%s", dur_val)
                continue
            accumulated += units

            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = dur_val
            if is_dotted:
                beat.duration.isDotted = True

            notes_data = bdata.get("notes", [])
            if bdata.get("status") == "rest" or not notes_data:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                vel = _DYN_MAP.get(bdata.get("dynamic", "mf"), 95)
                for nd in notes_data:
                    gnote = Note(beat)
                    gnote.string = nd.get("string", 1)
                    gnote.value = nd.get("fret", 0)
                    gnote.velocity = vel
                    eff = nd.get("effect")
                    if eff in ("hammer-on", "pull-off"):
                        gnote.effect.hammer = True
                        gnote.type = NoteType.normal
                    elif eff == "mute":
                        gnote.type = NoteType.dead
                    elif eff == "ghost":
                        gnote.effect.ghostNote = True
                        gnote.type = NoteType.normal
                    elif eff == "harmonic":
                        # ponytail: scoreSerializer.ts의 getNoteEffect가 alphaTab의
                        # HarmonicType(natural/artificial/pinch/tap/semi)을 전부
                        # 'harmonic' 문자열 하나로 뭉개서 넘기므로, 여기선 애초에
                        # 종류를 구분할 정보가 없다. 프론트엔드 스냅샷 스키마에
                        # harmonicType을 추가하면 해소 가능(트릴/운지법과 동일 패턴).
                        gnote.effect.harmonic = gpm.NaturalHarmonic()
                        gnote.type = NoteType.normal
                    elif eff in _SLIDE_MAP:
                        gnote.effect.slides = [_SLIDE_MAP[eff]]
                        gnote.type = NoteType.normal
                    elif eff == "trill":
                        gnote.effect.trill = gpm.TrillEffect(
                            fret=nd.get("trillFret", gnote.value),
                            duration=gpm.Duration(value=gpm.Duration.sixteenth),
                        )
                        gnote.type = NoteType.normal
                    elif eff == "vibrato":
                        gnote.effect.vibrato = True
                        gnote.type = NoteType.normal
                    else:
                        gnote.type = NoteType.normal
                    rh_finger = nd.get("rightHandFinger")
                    if rh_finger is not None:
                        gnote.effect.rightHandFinger = gpm.Fingering(rh_finger)
                    beat.notes.append(gnote)

            strum = bdata.get("strumDown")
            if strum is True:
                beat.effect.pickStroke = BeatStrokeDirection.down
                beat.effect.stroke.direction = BeatStrokeDirection.down
                beat.effect.stroke.value = dur_val
            elif strum is False:
                beat.effect.pickStroke = BeatStrokeDirection.up
                beat.effect.stroke.direction = BeatStrokeDirection.up
                beat.effect.stroke.value = dur_val

            voice.beats.append(beat)

        _pad_voice_with_rests(voice, expected - accumulated)

    def _fill_snap(measure: gpm.Measure, mdata: dict) -> None:
        ts = mdata.get("timeSignature", {})
        expected = (ts.get("num", 4) / ts.get("den", 4)) * 64

        voices_v2 = mdata.get("voices")
        beats_v0 = (voices_v2[0] if voices_v2 else None) or mdata.get("beats", [])
        _fill_voice_beats(measure.voices[0], beats_v0, expected)

        # voices[1] 지원
        if voices_v2 and len(voices_v2) > 1 and voices_v2[1]:
            _fill_voice_beats(measure.voices[1], voices_v2[1], expected)

    ts0 = measures_data[0].get("timeSignature", {})
    first_mh = song.measureHeaders[0]
    first_mh.number = 1
    first_mh.timeSignature.numerator = ts0.get("num", 4)
    first_mh.timeSignature.denominator.value = ts0.get("den", 4)
    first_mh.keySignature = KeySignature((measures_data[0].get("keySignature", 0), 0))
    _marker = measures_data[0].get("sectionMarker")
    if _marker:
        first_mh.marker = gpm.Marker(title=_marker)
    _fill_snap(track.measures[0], measures_data[0])

    start = first_mh.start + first_mh.length
    for i, mdata in enumerate(measures_data[1:], start=2):
        ts = mdata.get("timeSignature", {})
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = ts.get("num", 4)
        mh.timeSignature.denominator.value = ts.get("den", 4)
        mh.keySignature = KeySignature((mdata.get("keySignature", 0), 0))
        _loop_marker = mdata.get("sectionMarker")
        if _loop_marker:
            mh.marker = gpm.Marker(title=_loop_marker)
        song.measureHeaders.append(mh)
        m = gpm.Measure(track, mh)
        _fill_snap(m, mdata)
        track.measures.append(m)
        start += mh.length

    # 첫 번째 트랙 튜닝 설정
    tuning_0 = tracks_data[0].get("tuning")
    if tuning_0 and len(tuning_0) == 6:
        for i, val in enumerate(tuning_0[:6]):
            track.strings[i].value = val

    # 추가 트랙 (tracks[1:])
    _default_tuning = [64, 59, 55, 50, 45, 40]
    for ti, track_data in enumerate(tracks_data[1:], start=1):
        tuning = track_data.get("tuning", _default_tuning)
        if len(tuning) < 6:
            tuning = tuning + _default_tuning[len(tuning):]
        new_strings = [gpm.GuitarString(number=j + 1, value=tuning[j]) for j in range(6)]

        new_track = gpm.Track(song, number=ti + 1, strings=new_strings)
        new_track.name = track_data.get("name", f"Track {ti + 1}")

        track_measures_data = track_data.get("measures", [])
        for mi, mh in enumerate(song.measureHeaders):
            mdata = track_measures_data[mi] if mi < len(track_measures_data) else {}
            m = gpm.Measure(new_track, mh)
            _fill_snap(m, mdata)
            new_track.measures.append(m)

        song.tracks.append(new_track)

    guitarpro.write(song, out_path)
    return out_path


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
