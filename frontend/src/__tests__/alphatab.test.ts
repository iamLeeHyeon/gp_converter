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
