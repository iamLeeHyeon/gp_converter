import { render, screen, fireEvent } from '@testing-library/react'
import { vi, beforeEach } from 'vitest'
import { initAlphaTab } from '../lib/alphatab'
import { useEditorStore } from '../store/editorStore'

beforeEach(() => {
  vi.mocked(initAlphaTab).mockClear()
})

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    noteMouseDown: { on: vi.fn() },
    postRenderFinished: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
    render: vi.fn(),
    score: null,
  }),
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: Object.assign(
    vi.fn().mockReturnValue({
      selected: null, fileId: null, present: null, saveStatus: 'idle',
      setSelected: vi.fn(), pushSnapshot: vi.fn(), undo: vi.fn(), redo: vi.fn(),
      clearHistory: vi.fn(),
    }),
    { getState: vi.fn().mockReturnValue({ present: null }) },
  ),
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

test('악보 최초 로드(scoreLoaded) 시 present가 비어있으면 pushSnapshot으로 채워야 한다(트랙/구조 패널이 항상 비어보이던 버그)', () => {
  const pushSnapshot = vi.fn()
  vi.mocked(useEditorStore).mockReturnValue({
    selected: null, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot, undo: vi.fn(), redo: vi.fn(), clearHistory: vi.fn(),
  } as any)
  vi.mocked(useEditorStore.getState).mockReturnValue({ present: null } as any)

  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  // scoreLoaded.on의 mock 호출 이력은 initAlphaTab이 매번 같은 mock 객체를
  // 반환하므로 이전 테스트들 등록분까지 누적된다 — 이번 렌더가 등록한 콜백은
  // 항상 마지막 호출이다.
  const onCalls = mockApi.scoreLoaded.on.mock.calls
  const scoreLoadedCallback = onCalls[onCalls.length - 1][0]
  scoreLoadedCallback({ tracks: [] })

  expect(pushSnapshot).toHaveBeenCalledTimes(1)
})

test('present가 이미 있으면(구조편집 후 재로드) scoreLoaded에서 다시 pushSnapshot하지 않는다(undo 히스토리 중복 방지)', () => {
  const pushSnapshot = vi.fn()
  vi.mocked(useEditorStore).mockReturnValue({
    selected: null, fileId: null, present: { tracks: [] } as any, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot, undo: vi.fn(), redo: vi.fn(), clearHistory: vi.fn(),
  } as any)
  vi.mocked(useEditorStore.getState).mockReturnValue({ present: { tracks: [] } } as any)

  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  // scoreLoaded.on의 mock 호출 이력은 initAlphaTab이 매번 같은 mock 객체를
  // 반환하므로 이전 테스트들 등록분까지 누적된다 — 이번 렌더가 등록한 콜백은
  // 항상 마지막 호출이다.
  const onCalls = mockApi.scoreLoaded.on.mock.calls
  const scoreLoadedCallback = onCalls[onCalls.length - 1][0]
  scoreLoadedCallback({ tracks: [] })

  expect(pushSnapshot).not.toHaveBeenCalled()
})

test('scoreLoaded에서 초기 스냅샷 생성이 실패해도 예외가 새어나가면 안 된다(실제 렌더링이 멈추던 버그)', () => {
  const pushSnapshot = vi.fn()
  vi.mocked(useEditorStore).mockReturnValue({
    selected: null, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot, undo: vi.fn(), redo: vi.fn(), clearHistory: vi.fn(),
  } as any)
  vi.mocked(useEditorStore.getState).mockReturnValue({ present: null } as any)
  const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  const onCalls = mockApi.scoreLoaded.on.mock.calls
  const scoreLoadedCallback = onCalls[onCalls.length - 1][0]

  // tracks 프로퍼티가 없는 score → serializeScore 내부에서 실제로 TypeError 발생
  expect(() => scoreLoadedCallback({})).not.toThrow()
  expect(pushSnapshot).not.toHaveBeenCalled()
  expect(consoleErrorSpy).toHaveBeenCalled()

  consoleErrorSpy.mockRestore()
})

test('음표 선택 후 ArrowUp/ArrowDown으로 프렛 입력창 없이 화면에서 바로 음을 옮긴다', () => {
  const note = { string: 1, fret: 5 }
  const beat = { notes: [note] }
  const score = { tracks: [{ staves: [{ bars: [{ voices: [{ beats: [beat] }] }] }] }] }
  const selected = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }
  vi.mocked(useEditorStore).mockReturnValue({
    selected, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot: vi.fn(), undo: vi.fn(), redo: vi.fn(), clearHistory: vi.fn(),
  } as any)
  vi.mocked(useEditorStore.getState).mockReturnValue({ present: null, selected } as any)
  vi.spyOn(console, 'error').mockImplementation(() => {})

  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  mockApi.score = score

  fireEvent.keyDown(window, { key: 'ArrowUp' })
  expect(note.fret).toBe(6)

  fireEvent.keyDown(window, { key: 'ArrowDown' })
  fireEvent.keyDown(window, { key: 'ArrowDown' })
  expect(note.fret).toBe(4)

  expect(mockApi.render).toHaveBeenCalled()
  vi.mocked(console.error).mockRestore()
})

test('ArrowUp/ArrowDown은 프렛 0~24 범위를 벗어나지 않는다', () => {
  const note = { string: 1, fret: 0 }
  const beat = { notes: [note] }
  const score = { tracks: [{ staves: [{ bars: [{ voices: [{ beats: [beat] }] }] }] }] }
  const selected = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }
  vi.mocked(useEditorStore).mockReturnValue({
    selected, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot: vi.fn(), undo: vi.fn(), redo: vi.fn(), clearHistory: vi.fn(),
  } as any)
  vi.mocked(useEditorStore.getState).mockReturnValue({ present: null, selected } as any)
  vi.spyOn(console, 'error').mockImplementation(() => {})

  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  const mockApi = vi.mocked(initAlphaTab).mock.results[0].value
  mockApi.score = score

  fireEvent.keyDown(window, { key: 'ArrowDown' })
  expect(note.fret).toBe(0)

  vi.mocked(console.error).mockRestore()
})
