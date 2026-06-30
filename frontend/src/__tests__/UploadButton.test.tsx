import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import UploadButton from '../components/FileManager/UploadButton'

vi.mock('../lib/api', () => ({
  api: { upload: vi.fn().mockResolvedValue({ job_id: 'job1', file_id: null }) },
}))
vi.mock('../lib/sse', () => ({
  connectSSE: vi.fn().mockImplementation((_id, _onP, onDone) => { onDone(); return () => {} }),
}))
vi.spyOn(global, 'fetch').mockResolvedValue({
  ok: true, arrayBuffer: async () => new ArrayBuffer(8),
} as Response)

test('파일 선택 후 업로드 버튼 활성화', async () => {
  render(<UploadButton onComplete={vi.fn()} />)
  const input = screen.getByLabelText(/PDF/i)
  const file = new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })
  await userEvent.upload(input, file)
  expect(screen.getByRole('button', { name: /변환/i })).not.toBeDisabled()
})
