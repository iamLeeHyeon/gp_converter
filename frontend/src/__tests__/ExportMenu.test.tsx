import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    downloadGP5: vi.fn().mockResolvedValue(undefined),
    downloadMIDI: vi.fn().mockResolvedValue(undefined),
  },
}))

import ExportMenu from '../components/Editor/ExportMenu'

describe('ExportMenu', () => {
  const onPrint = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('GP5/PDF/MIDI 버튼 세 개 렌더링', () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /GP5/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /PDF/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /MIDI/i })).toBeInTheDocument()
  })

  it('fileId 없으면 GP5/MIDI 버튼 비활성화', () => {
    render(<ExportMenu fileId={null} onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /GP5/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /MIDI/i })).toBeDisabled()
    // PDF는 alphaTab print라 항상 활성
    expect(screen.getByRole('button', { name: /PDF/i })).not.toBeDisabled()
  })

  it('GP5 버튼 클릭 → api.downloadGP5 호출', async () => {
    const { api } = await import('../lib/api')
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /GP5/i }))
    expect(api.downloadGP5).toHaveBeenCalledWith('f1', expect.stringContaining('.gp5'))
  })

  it('PDF 버튼 클릭 → onPrint 호출', async () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /PDF/i }))
    expect(onPrint).toHaveBeenCalled()
  })

  it('MIDI 버튼 클릭 → api.downloadMIDI 호출', async () => {
    const { api } = await import('../lib/api')
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /MIDI/i }))
    expect(api.downloadMIDI).toHaveBeenCalledWith('f1', expect.stringContaining('.mid'))
  })
})
