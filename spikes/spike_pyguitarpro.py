"""스파이크: music21이 MusicXML 파싱 + PyGuitarPro가 .gp5 쓰기 가능한지 검증.

사용법:
    python spikes/spike_pyguitarpro.py <input.musicxml> <output.gp5>

=== 스파이크 결과 (2026-06-24) ===
- music21 8.3.0: Audiveris .mxl 파싱 OK (음정 + 박자 quarterLength 획득).
- PyGuitarPro 0.10.1: 기본 Song()은 1트랙 6현 표준튜닝(EADGBE) 제공.
  guitarpro.write(song, path)로 유효한 .gp5 생성, 재파싱(guitarpro.parse)까지 성공.
  헤더: b"FICHIER GUITAR PRO v5.10".
- 결론: TuxGuitar 불필요. 파이프라인 = Audiveris → music21 → PyGuitarPro (순수 파이썬).
- 주의: 아래는 프렛=3 플레이스홀더. 실제 음정→(현,프렛) 매핑은 변환기 본 구현에서.
"""
import os
import sys

import guitarpro
from guitarpro import Beat, Note, NoteType
from music21 import converter, note as m21note


def main(mxl_path: str, out_path: str) -> None:
    # Half 1: music21 파싱
    score = converter.parse(mxl_path)
    notes = [n for n in score.recurse().notes if isinstance(n, m21note.Note)]
    print(f"[music21] parts={len(score.parts)} notes={len(notes)} "
          f"first={[n.nameWithOctave for n in notes[:5]]}")

    # Half 2: PyGuitarPro로 .gp5 생성 (플레이스홀더 비트)
    song = guitarpro.models.Song()
    track = song.tracks[0]
    track.name = "Guitar"
    voice = track.measures[0].voices[0]
    voice.beats = []
    for _ in notes[:4]:
        beat = Beat(voice=voice)
        gnote = Note(beat=beat)
        gnote.value = 3
        gnote.string = 1
        gnote.type = NoteType.normal
        beat.notes = [gnote]
        voice.beats.append(beat)

    guitarpro.write(song, out_path)
    with open(out_path, "rb") as f:
        head = f.read(40)
    assert b"GUITAR PRO" in head, "GP 시그니처 없음"
    print(f"[pgp] wrote {out_path} size={os.path.getsize(out_path)} header={head[:30]!r}")

    back = guitarpro.parse(out_path)
    print(f"[pgp] re-parsed OK tracks={len(back.tracks)} version={back.version}")
    print("SPIKE OK")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python spike_pyguitarpro.py <input.musicxml> <output.gp5>")
    main(sys.argv[1], sys.argv[2])
