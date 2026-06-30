import * as alphaTab from '@coderline/alphatab'

export function initAlphaTab(element: HTMLElement): alphaTab.AlphaTabApi {
  const settings = new alphaTab.Settings()
  settings.core.engine = 'html5'
  settings.core.fontDirectory =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/'
  settings.player.enablePlayer = true
  settings.player.enableCursor = true
  settings.player.soundFont =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2'
  return new alphaTab.AlphaTabApi(element, settings)
}
