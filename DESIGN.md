---
name: GP Converter
description: PDF 악보를 Guitar Pro 탭으로 바꿔주는 기타리스트용 변환/편집 도구
colors:
  bg: "#eef6ff"
  surface: "#ffffff"
  surface-alt: "#f4f9ff"
  ink: "#16233a"
  muted: "#64748b"
  border: "#e0ecfc"
  primary: "#4a9df0"
  primary-hover: "#308fea"
  primary-soft: "#58affb"
  primary-light: "#a8d3fb"
  danger: "#e5787a"
typography:
  display:
    fontFamily: "Pretendard, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontWeight: 700
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Pretendard, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "16px"
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "12px 24px"
  button-ghost:
    backgroundColor: "{colors.surface-alt}"
    textColor: "{colors.primary-hover}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
---

# Design System: GP Converter

## 1. Overview

**Creative North Star: "The Sky-Blue Tuner"**

정밀한 악기 튜너처럼 정확함을 조용히 증명하되, 무겁고 어두운 도구 느낌 대신 맑고 화창한 하늘색 톤으로 표현한다. 밝은 배경 위에 하늘색 계열(연한 것부터 진한 것까지)을 그라디언트로 적극적으로 활용해 "따뜻하고 캐주얼"하면서도 "정확하고 신뢰감 있는" 인상을 동시에 전달한다. klang.io/guitar2tabs에서 가져온 "둥근 산세리프 + 절제된 UI 구조"는 유지하되, 어두운 배경 대신 밝고 화사한 톤으로 방향을 바꿨다(실제 사용 피드백으로 확정됨: 다크 테마는 너무 어두컴컴하다는 판단, 쨍한 단색 블록보다 부드러운 그라디언트가 낫다는 판단).

이 시스템이 명시적으로 거부하는 것: 크림색/파스텔 배경에 보라-핑크 그라디언트를 쓰는 전형적 SaaS 룩, 손그림풍 일러스트나 과한 이모지 같은 장난감스러운 느낌, 쨍하고 평평한 단색 블록(그라디언트로 부드럽게 풀어낸다).

**Key Characteristics:**
- 밝은 배경(연한 하늘색 틴트) + 하늘색 계열 그라디언트를 사이드바/버튼 등 핵심 표면에 적극 사용
- 둥글고 따뜻한 느낌의 한국어 지원 산세리프(Pretendard) 하나로 전체 통일, 굵기로 위계 구분
- 반응형 모션 — 상태변화/피드백에만 트랜지션, 연출성 애니메이션 없음
- 카드에 옅은 그림자로 가벼운 입체감(완전 플랫은 아님, 부드러운 부양감)

## 2. Colors

밝은 배경 위에 하늘색 계열 그라디언트가 핵심 표면(사이드바, 주요 버튼)을 채우는 팔레트.

### Primary
- **Sky** (`#4a9df0`): 링크, 포커스 링, 강조 텍스트의 기본 톤.
- **Sky Deep** (`#308fea`): 버튼 그라디언트의 진한 쪽, 호버 상태.
- **Sky Soft** (`#58affb`): 그라디언트의 밝은 쪽, 사이드바 그라디언트 시작색 계열.
- **Sky Light** (`#a8d3fb`): ghost 버튼 보더, 호버 배경, 은은한 강조.

### Neutral
- **Cloud** (`#eef6ff`): 전체 배경(옅은 하늘색 틴트), 실제로는 `#f4f9ff → #e6f2ff` 세로 그라디언트로 적용.
- **Paper** (`#ffffff`): 카드/패널 표면.
- **Paper Alt** (`#f4f9ff`): 인풋 배경 대비용 보조 표면(ghost 버튼 배경).
- **Ink** (`#16233a`): 본문/제목 텍스트.
- **Muted** (`#64748b`): 보조 텍스트, 플레이스홀더. 명도대비 4.5:1 이상 유지.
- **Border** (`#e0ecfc`): 옅은 하늘색 보더.

### Named Rules
**The Gradient-Over-Flat Rule.** 강조 표면(사이드바, 주요 버튼)은 단색 대신 하늘색 계열 그라디언트로 채운다. 쨍한 단색 블록은 피하고, 톤이 자연스럽게 이어지도록 한다.

## 3. Typography

**Display/Body Font:** Pretendard (CDN: `pretendard@v1.3.9`), fallback `system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif`

**Character:** 하나의 한국어 지원 산세리프를 굵기 차이로만 위계를 나눈다. 둥근 느낌이 있으면서도 UI 텍스트로서 충분히 또렷하게 읽힌다(대부분 한글 텍스트이므로 Hangul 커버리지가 최우선 조건).

### Hierarchy
- **Display** (bold 700, `1.75~2rem`): 페이지 제목("GP Converter", 인증 페이지 타이틀)
- **Headline** (bold 700, `1.25rem`): 섹션 제목
- **Title** (semibold 600, `0.9~1rem`): 카드/패널 제목("내 파일", "마디 구조")
- **Body** (regular 400, `1rem`, line-height 1.5): 본문
- **Label** (semibold 600, `0.8125~0.875rem`): 버튼 라벨, 폼 라벨

### Named Rules
**The Single Voice Rule.** 폰트 패밀리는 Pretendard 하나만 쓴다. 위계는 굵기와 크기로만 표현한다.

## 4. Elevation

가벼운 입체감을 쓴다. 카드는 옅은 하늘색 톤 그림자(`rgba(74,157,240,0.06~0.08)`)로 배경에서 살짝 떠 보이게 하고, 버튼은 호버 시에만 그림자가 더 진해진다.

### Shadow Vocabulary
- **Card Rest** (`box-shadow: 0 2px 16px rgba(74,157,240,0.06)`): 카드의 기본 상태.
- **Hover Lift** (`box-shadow: 0 4px 16px rgba(74,157,240,0.28)`): 주요 버튼 호버 시.

### Named Rules
**The Soft Float Rule.** 카드는 항상 옅은 그림자로 떠 있고, 상호작용 요소는 호버 시 그림자가 진해지는 것으로 반응한다.

## 5. Components

### Buttons
- **Shape:** 8px 라운드
- **Primary:** 배경 `linear-gradient(135deg, #76beff, #4a9df0)`, 텍스트 흰색, 패딩 `12px 24px`, 호버 시 그림자 강조
- **Ghost:** 배경 `surface-alt`(`#f4f9ff`), 텍스트 `primary-hover`(`#308fea`), 보더 1px `primary-light`, 호버 시 배경이 `primary-light`로 채워지고 텍스트는 `ink`로 전환
- **on-blue(사이드바 내부처럼 컬러 표면 위)**: 배경 흰색, 텍스트 강조색(반전 배치)

### Cards / Containers
- **Corner Style:** 12px 라운드
- **Background:** `surface`(흰색), 보더 1px `border`
- **Shadow Strategy:** Card Rest 그림자 항상 적용

### Inputs / Fields
- **Style:** 흰색 배경, 1px `border` 보더, 8px 라운드
- **Focus:** 보더가 `primary`로, `box-shadow: 0 0 0 3px rgba(74,157,240,0.15)` 링

### Navigation (사이드바)
- 배경: `linear-gradient(160deg, #5b9fe8, #8cc6fb)`, 텍스트 흰색(투명도로 위계: 본문 85%, 보조 60~70%)
- 로그인/로그아웃 등 보조 액션은 흰색 반투명(`rgba(255,255,255,0.15)`) 배경 + 흰색 보더 ghost 스타일

## 6. Do's and Don'ts

### Do:
- **Do** 강조 표면(사이드바, 주요 버튼)에 하늘색 그라디언트를 적극적으로 쓴다.
- **Do** 밝은 배경 위에서 명도대비 4.5:1 이상을 항상 확인한다(특히 `Muted` 보조텍스트, 사이드바 위 반투명 흰 텍스트).
- **Do** Pretendard 하나의 폰트 패밀리를 굵기/크기로만 위계를 나눠 쓴다.
- **Do** 카드에는 옅은 그림자로 가벼운 부양감을 준다.

### Don't:
- **Don't** 크림색/파스텔 배경에 보라-핑크 그라디언트를 쓰는 전형적 SaaS 룩을 만들지 않는다.
- **Don't** 손그림풍 일러스트, 과한 이모지, 장난감스러운 애니메이션을 쓰지 않는다.
- **Don't** 강조 표면을 쨍한 단색 블록으로 채우지 않는다 — 항상 그라디언트로 부드럽게 푼다.
- **Don't** `border-left`/`border-right` 컬러 스트라이프를 카드나 알림에 장식으로 쓰지 않는다.
- **Don't** 1px 보더와 16px 이상 블러의 넓은 그림자를 같이 쓰지 않는다(고스트카드 패턴).
- **Don't** 카드/섹션/인풋에 32px 이상 라운드를 쓰지 않는다.
