import * as alphaTab from '@coderline/alphatab'

export function initAlphaTab(element: HTMLElement): alphaTab.AlphaTabApi {
  const settings = new alphaTab.Settings()
  settings.core.engine = 'html5'
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
