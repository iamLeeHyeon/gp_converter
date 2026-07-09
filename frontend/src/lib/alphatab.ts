import * as alphaTab from '@coderline/alphatab'

// player.scrollElement 기본값은 'html,body' — alphaTab이 페이지 전체가
// 스크롤된다고 가정하고 그 요소를 스크롤한다. 이 앱은 전체 페이지가 아니라
// 악보 영역 안쪽의 div(overflow:auto)만 스크롤되는 구조라, 기본값으로는
// 재생 커서를 따라가는 자동 스크롤이 전혀 동작하지 않았다(커서 자체는 정상
// 이동 중인데 화면 밖에 있어서 안 보이던 문제 — 실사용 중 재현). 실제
// 스크롤 가능한 조상을 찾아 지정한다.
function findScrollContainer(element: HTMLElement): HTMLElement {
  let node = element.parentElement
  while (node) {
    if (getComputedStyle(node).overflowY === 'auto' || getComputedStyle(node).overflowY === 'scroll') {
      return node
    }
    node = node.parentElement
  }
  return document.body
}

export function initAlphaTab(element: HTMLElement): alphaTab.AlphaTabApi {
  const settings = new alphaTab.Settings()
  settings.core.engine = 'html5'
  settings.player.scrollElement = findScrollContainer(element)
  // vite.config.ts의 @coderline/alphatab-vite 플러그인이 폰트/사운드폰트를
  // public/font, public/soundfont로 복사해줘서 로컬 경로로 서빙된다. CDN을 쓰던
  // 이전 방식은 폰트/사운드폰트 자체는 fetch로 받아와 문제없었지만, 워커
  // 스크립트는 same-origin이어야 해서 CDN으로는 애초에 해결 불가능했다.
  settings.core.fontDirectory = '/font/'
  // 기본값 false — 이게 없으면 noteMouseDown/beatMouseDown이 절대 안 뜬다
  // (alphaTab이 노트별 히트박스 자체를 계산 안 해서 클릭해도 편집 패널이
  // 항상 "음표를 클릭하면 편집할 수 있습니다" 상태로 남아있던 원인이었다).
  settings.core.includeNoteBounds = true
  // `enablePlayer`는 deprecated 설정이라 이 버전(1.8.3)에서는 실제로 플레이어를
  // 켜지 않는다(내부적으로 playerMode가 계속 Disabled로 남음) — 재생 버튼을
  // 눌러도 콜백은 정상 실행되는데 조용히 아무 일도 안 일어나던 원인이었다.
  // 백킹트랙 없이 순수 신디사이저 재생만 쓰므로 EnabledSynthesizer를 명시한다.
  settings.player.playerMode = alphaTab.PlayerMode.EnabledSynthesizer
  settings.player.enableCursor = true
  settings.player.soundFont = '/soundfont/sonivox.sf2'
  return new alphaTab.AlphaTabApi(element, settings)
}
