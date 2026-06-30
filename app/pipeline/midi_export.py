"""GP5 파일 → MIDI 변환 (guitarpro + mido)."""
import os
import tempfile

import guitarpro as gpm
import mido


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
        abs_tick = 0

        for measure in track.measures:
            for voice in measure.voices:
                for beat in voice.beats:
                    dur = beat.duration.time  # ticks (quarter=960)
                    if beat.status == gpm.BeatStatus.normal:
                        for note in beat.notes:
                            if note.type == gpm.NoteType.normal:
                                open_val = track.strings[note.string - 1].value
                                pitch = min(127, max(0, open_val + note.value))
                                events.append((abs_tick, 'note_on', pitch, 80))
                                events.append((abs_tick + dur, 'note_off', pitch, 0))
                    abs_tick += dur

        # 같은 tick에서 note_off를 note_on보다 먼저 처리
        events.sort(key=lambda e: (e[0], 0 if e[1] == 'note_off' else 1))

        # 절대 tick → delta tick 변환
        midi_track = mido.MidiTrack()
        ch = min(ti, 15)
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
