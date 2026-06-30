"""GP5 파일 → MIDI 변환 (guitarpro + mido)."""
import guitarpro as gpm
import mido


def _track_channel(ti: int) -> int:
    """트랙 인덱스 → MIDI 채널. 채널 9(GM 퍼커션) 건너뜀, 최대 15."""
    ch = ti if ti < 9 else ti + 1
    return min(ch, 15)


def gp5_to_midi(gp5_path: str, out_path: str) -> str:
    """GP5 파일을 MIDI로 변환해 out_path에 저장한다. out_path를 반환."""
    song = gpm.parse(gp5_path)
    ticks_per_beat = 960
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    # 트랙 0: 템포
    t0 = mido.MidiTrack()
    tempo_us = int(60_000_000 / max(song.tempo, 1))
    t0.append(mido.MetaMessage('set_tempo', tempo=tempo_us, time=0))
    mid.tracks.append(t0)

    for ti, track in enumerate(song.tracks):
        # (절대 tick, 메시지 타입, pitch, velocity) 이벤트 수집
        events: list[tuple[int, str, int, int]] = []
        measure_start = 0

        for measure in track.measures:
            # pitch → 현재 진행 중인 note_on의 절대 tick (타이 연장용)
            pending_note_on: dict[int, int] = {}

            for voice in measure.voices:
                abs_tick = measure_start          # voice마다 measure 시작으로 리셋
                for beat in voice.beats:
                    dur = beat.duration.time  # ticks (quarter=960)
                    if beat.status == gpm.BeatStatus.normal:
                        for note in beat.notes:
                            if note.type == gpm.NoteType.normal:
                                try:
                                    open_val = track.strings[note.string - 1].value
                                except IndexError:
                                    continue
                                pitch = min(127, max(0, open_val + note.value))
                                events.append((abs_tick, 'note_on', pitch, 80))
                                # note_off는 일단 이 beat 끝에 예약
                                events.append((abs_tick + dur, 'note_off', pitch, 0))
                                pending_note_on[pitch] = len(events) - 1  # note_off 인덱스
                            elif note.type == gpm.NoteType.tie:
                                try:
                                    open_val = track.strings[note.string - 1].value
                                except IndexError:
                                    continue
                                pitch = min(127, max(0, open_val + note.value))
                                if pitch in pending_note_on:
                                    # 직전 note_off tick을 현재 beat 끝으로 연장
                                    idx = pending_note_on[pitch]
                                    old = events[idx]
                                    events[idx] = (abs_tick + dur, old[1], old[2], old[3])
                                    pending_note_on[pitch] = idx  # 여전히 같은 인덱스
                    abs_tick += dur

            # measure 전체 길이: 마디 헤더 길이 기준 (voice[0] 합 아님)
            measure_start += measure.header.length

        # 같은 tick에서 note_off를 note_on보다 먼저 처리
        events.sort(key=lambda e: (e[0], 0 if e[1] == 'note_off' else 1))

        # 절대 tick → delta tick 변환
        midi_track = mido.MidiTrack()
        ch = _track_channel(ti)
        prev = 0
        for t_abs, msg_type, pitch, vel in events:
            delta = t_abs - prev
            midi_track.append(
                mido.Message(msg_type, channel=ch, note=pitch, velocity=vel, time=delta)
            )
            prev = t_abs
        mid.tracks.append(midi_track)

    mid.save(out_path)
    return out_path
