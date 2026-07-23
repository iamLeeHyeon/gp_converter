import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

vi.mock('../store/fileStore', () => ({
  useFileStore: () => ({
    files: [
      { id: '1', name: 'Song A', created_at: '2026-01-01' },
      { id: '2', name: 'Song B', created_at: '2026-01-02' },
    ],
    loading: false,
    load: vi.fn(),
    remove: vi.fn(),
  }),
}))
vi.mock('../lib/api', () => ({ api: { getGP5Buffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } }))

import { api } from '../lib/api'
import FileList from '../components/FileManager/FileList'

test('파일 목록 렌더링', () => {
  render(<FileList onSelect={vi.fn()} />)
  expect(screen.getByText('Song A')).toBeInTheDocument()
  expect(screen.getByText('Song B')).toBeInTheDocument()
})

test('파일 클릭 시 api.getGP5Buffer(fileId) 호출 후 onSelect 호출', async () => {
  const onSelect = vi.fn()
  render(<FileList onSelect={onSelect} />)
  await userEvent.click(screen.getByText('Song A'))
  await vi.waitFor(() => expect(onSelect).toHaveBeenCalled())
  expect(api.getGP5Buffer).toHaveBeenCalledWith('1')
})

test('파일 열기 실패 시 unhandled rejection 없이 에러 메시지를 보여준다', async () => {
  vi.mocked(api.getGP5Buffer).mockRejectedValueOnce(new Error('HTTP 404'))
  const onSelect = vi.fn()
  render(<FileList onSelect={onSelect} />)

  await userEvent.click(screen.getByText('Song A'))

  expect(await screen.findByText('"Song A" 파일을 여는 데 실패했습니다')).toBeInTheDocument()
  expect(onSelect).not.toHaveBeenCalled()
})
