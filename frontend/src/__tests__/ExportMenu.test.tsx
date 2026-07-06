import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    downloadGP5: vi.fn().mockResolvedValue(undefined),
    downloadMIDI: vi.fn().mockResolvedValue(undefined),
    downloadBuffer: vi.fn(),
    getShareStatus: vi.fn().mockResolvedValue({ token: null, expires_at: null }),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
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

  it('fileId/gp5Buffer 둘 다 없으면 GP5/MIDI 버튼 비활성화', () => {
    render(<ExportMenu fileId={null} gp5Buffer={null} onPrint={onPrint} />)
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

  it('fileId 없어도 gp5Buffer 있으면 GP5 버튼 활성화 + 클릭 시 api.downloadBuffer 호출(익명 다운로드)', async () => {
    const { api } = await import('../lib/api')
    const buf = new ArrayBuffer(8)
    render(<ExportMenu fileId={null} gp5Buffer={buf} onPrint={onPrint} />)
    const gp5Button = screen.getByRole('button', { name: /GP5/i })
    expect(gp5Button).not.toBeDisabled()
    await userEvent.click(gp5Button)
    expect(api.downloadBuffer).toHaveBeenCalledWith(buf, expect.stringContaining('.gp5'))
  })

  it('fileId 없이 gp5Buffer만 있어도 MIDI 버튼은 계속 비활성화(서버 변환 필요)', () => {
    render(<ExportMenu fileId={null} gp5Buffer={new ArrayBuffer(8)} onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /MIDI/i })).toBeDisabled()
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

  it('공유 버튼 클릭 → ShareModal 오픈', async () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /공유/i }))
    expect(await screen.findByText('공유 링크')).toBeInTheDocument()
  })

  it('fileId 없으면 공유 버튼 비활성화', () => {
    render(<ExportMenu fileId={null} onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /공유/i })).toBeDisabled()
  })
})
