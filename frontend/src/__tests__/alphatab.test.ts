import { vi, test, expect } from 'vitest'

const { AlphaTabApiMock } = vi.hoisted(() => ({ AlphaTabApiMock: vi.fn() }))

vi.mock('@coderline/alphatab', async () => {
  const actual = await vi.importActual<typeof import('@coderline/alphatab')>('@coderline/alphatab')
  return {
    ...actual,
    AlphaTabApi: AlphaTabApiMock,
  }
})

import { initAlphaTab } from '../lib/alphatab'

test('includeNoteBounds를 true로 켜야 한다(꺼져있으면 noteMouseDown이 영원히 안 뜸)', () => {
  const element = document.createElement('div')
  initAlphaTab(element)

  const settings = AlphaTabApiMock.mock.calls[0][1]
  expect(settings.core.includeNoteBounds).toBe(true)
})

test('scrollElement로 overflow:auto인 실제 스크롤 조상을 찾아 지정한다(기본값 html,body는 이 앱 구조에서 동작 안 함)', () => {
  const scrollParent = document.createElement('div')
  scrollParent.style.overflowY = 'auto'
  const middle = document.createElement('div')
  const element = document.createElement('div')
  scrollParent.appendChild(middle)
  middle.appendChild(element)
  document.body.appendChild(scrollParent)

  initAlphaTab(element)

  const settings = AlphaTabApiMock.mock.calls.at(-1)![1]
  expect(settings.player.scrollElement).toBe(scrollParent)

  document.body.removeChild(scrollParent)
})

test('스크롤 가능한 조상이 없으면 document.body로 폴백한다', () => {
  const orphan = document.createElement('div')
  initAlphaTab(orphan)

  const settings = AlphaTabApiMock.mock.calls.at(-1)![1]
  expect(settings.player.scrollElement).toBe(document.body)
})
