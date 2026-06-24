#!/usr/bin/env bash
# 스파이크: Audiveris CLI로 PDF → MusicXML 변환 검증.
#
# 사용법: ./spike_audiveris.sh <input.pdf> <output_dir>
#
# === 스파이크 결과 (2026-06-24, Audiveris 5.10.2, macOS arm64) ===
# - 설치: GitHub 릴리스 Audiveris-5.10.2-macosx-arm64.dmg → /Applications/Audiveris.app
# - CLI 실행 경로(앱 번들 런처):
#     /Applications/Audiveris.app/Contents/MacOS/Audiveris
# - 확정 명령: audiveris -batch -export -output <dir> -- <pdf>
# - 산출물: <dir>/<name>.mxl (압축 MusicXML), <name>.omr (book), 로그
# - 6페이지 기타 악보 처리 ~7분(느림). 표준 오선보 부분에서 559음표 인식.
# - 경고/주의: 박자표 누락 시 "No target duration" 경고, 일부 Fermata에서
#   비치명적 NPE가 나도 export는 완료됨.
# - 한계: Audiveris는 5선 표준악보 전용 → 기타 탭(6선)은 부정확할 수 있음.
set -euo pipefail

IN="${1:?input.pdf 경로 필요}"
OUT="${2:?output_dir 경로 필요}"
AUDIVERIS="${GPC_AUDIVERIS_CMD:-/Applications/Audiveris.app/Contents/MacOS/Audiveris}"

mkdir -p "$OUT"
"$AUDIVERIS" -batch -export -output "$OUT" -- "$IN"

echo "=== 산출물 ==="
find "$OUT" -name '*.mxl' -o -name '*.xml'
