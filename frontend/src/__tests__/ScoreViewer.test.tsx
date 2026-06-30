import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

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

import ScoreViewer from '../components/Editor/ScoreViewer'

test('gp5Buffer 없으면 안내 문구 표시', () => {
  render(<ScoreViewer gp5Buffer={null} />)
  expect(screen.getByText(/악보를 불러오세요/i)).toBeInTheDocument()
})

test('gp5Buffer 있으면 재생 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
})
