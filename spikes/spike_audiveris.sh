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
#
# === 추가 스파이크 (2026-06-25): pdfResolution 상수 ===
# - 디폴트 해상도로는 8분음표 꼬리(플래그)를 별도 노트헤드로 오인식해 화음+
#   잘못된 박자로 잘못 읽는 사례 실측 확인(같은 PDF 마디18).
# - -constant org.audiveris.omr.image.ImageLoading.pdfResolution=400 으로
#   올리면 해당 사례가 정확히 고쳐짐(원본 이미지 직접 확대 대조로 검증).
# - 주의: A4 기준 400dpi 근처가 한도(20,000,000 픽셀 cap, 600dpi는 cap 초과로
#   "Too large image" 에러 발생 확인). 너무 올리면 안 됨.
# - 주의: 해상도를 올리면 페이지 다른 부분 인식이 달라질 수 있음(이 PDF 기준
#   전체 마디 수가 187→182로 변함) — 만능 해결책 아니고 트레이드오프.
# - app/pipeline/audiveris.py의 pdf_to_musicxml()이 이 -constant를 기본
#   적용하도록 반영됨(_PDF_RESOLUTION_DPI=400).
set -euo pipefail

IN="${1:?input.pdf 경로 필요}"
OUT="${2:?output_dir 경로 필요}"
AUDIVERIS="${GPC_AUDIVERIS_CMD:-/Applications/Audiveris.app/Contents/MacOS/Audiveris}"

mkdir -p "$OUT"
"$AUDIVERIS" -batch -export -constant org.audiveris.omr.image.ImageLoading.pdfResolution=400 -output "$OUT" -- "$IN"

echo "=== 산출물 ==="
find "$OUT" -name '*.mxl' -o -name '*.xml'
