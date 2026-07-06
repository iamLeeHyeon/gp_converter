import * as alphaTab from '@coderline/alphatab'

export function initAlphaTab(element: HTMLElement): alphaTab.AlphaTabApi {
  const settings = new alphaTab.Settings()
  settings.core.engine = 'html5'
  settings.core.fontDirectory =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/'
  // `enablePlayer`는 deprecated 설정이라 이 버전(1.8.3)에서는 실제로 플레이어를
  // 켜지 않는다(내부적으로 playerMode가 계속 Disabled로 남음) — 재생 버튼을
  // 눌러도 콜백은 정상 실행되는데 조용히 아무 일도 안 일어나던 원인이었다.
  // 백킹트랙 없이 순수 신디사이저 재생만 쓰므로 EnabledSynthesizer를 명시한다.
  settings.player.playerMode = alphaTab.PlayerMode.EnabledSynthesizer
  settings.player.enableCursor = true
  settings.player.soundFont =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2'
  return new alphaTab.AlphaTabApi(element, settings)
}
