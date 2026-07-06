import { render, screen } from '@testing-library/react'
import { vi, beforeEach } from 'vitest'
import { initAlphaTab } from '../lib/alphatab'

beforeEach(() => {
  vi.mocked(initAlphaTab).mockClear()
})

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    noteMouseDown: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
    render: vi.fn(),
    score: null,
  }),
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: vi.fn().mockReturnValue({
    selected: null, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot: vi.fn(), undo: vi.fn(), redo: vi.fn(),
    clearHistory: vi.fn(),
  }),
}))
vi.mock('../lib/useSyncFile', () => ({ useSyncFile: vi.fn() }))
vi.mock('../lib/api', () => ({
  api: {
    downloadGP5: vi.fn().mockResolvedValue(undefined),
    downloadMIDI: vi.fn().mockResolvedValue(undefined),
  },
}))

import ScoreViewer from '../components/Editor/ScoreViewer'

test('gp5Buffer 없으면 안내 문구 표시', () => {
  render(<ScoreViewer gp5Buffer={null} />)
  expect(screen.getByText(/악보를 불러오세요/i)).toBeInTheDocument()
})

test('gp5Buffer 있으면 재생 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
})

test('gp5Buffer 있으면 GP5/PDF/MIDI 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /GP5/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /PDF/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /MIDI/i })).toBeInTheDocument()
})

test('실제 앱과 동일하게 처음엔 gp5Buffer가 null이었다가 나중에 값이 생기면, 그때도 alphaTab에 로드돼야 한다', async () => {
  // MainPage는 항상 gp5Buffer=null로 시작했다가(업로드/파일선택 완료까지는
  // 비동기 갭이 있다) 그 다음에야 값을 채운다. 이 비동기 갭을 재현해야만
  // "container div가 처음 마운트 시점에 아직 없어서 alphaTab 초기화 자체가
  // 스킵되는" 버그를 잡을 수 있다 — 처음부터 buffer를 채워서 렌더링하거나,
  // render 직후 동기적으로 rerender하는 테스트는 이 실제 타이밍을 재현하지
  // 못해 이 버그를 놓친다.
  const { rerender } = render(<ScoreViewer gp5Buffer={null} />)
  await new Promise((resolve) => setTimeout(resolve, 0))

  const buf = new ArrayBuffer(8)
  rerender(<ScoreViewer gp5Buffer={buf} />)

  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  expect(mockApi.load).toHaveBeenCalledWith(buf)

  // alphaTab 초기화 effect는 [setSelected]에만 의존해서 마운트 시 딱 한 번만
  // 실행된다 — 그 유일한 호출에 넘어간 컨테이너가 실제 DOM 엘리먼트여야 한다.
  // gp5Buffer=null인 최초 렌더에서 컨테이너 div 자체가 사라지는 구조였다면
  // 이 인자가 null이 되고, effect는 이후에도 재실행되지 않아 영영 복구 안 됐다.
  expect(vi.mocked(initAlphaTab).mock.calls[0][0]).toBeInstanceOf(HTMLElement)
})
