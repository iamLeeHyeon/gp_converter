import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import RegisterPage from '../components/Auth/RegisterPage'

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    localStorage.clear()
  })

  it('shows verification message after successful registration', async () => {
    (fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'a', refresh_token: 'r' }),
    })

    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('가입 완료')).toBeInTheDocument()
    })
  })

  it('shows error when passwords do not match', async () => {
    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'different123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('비밀번호가 일치하지 않습니다.')).toBeInTheDocument()
    })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows server error message on failed registration', async () => {
    (fetch as any).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '이미 가입된 이메일입니다.' }),
    })

    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('이미 가입된 이메일입니다.')).toBeInTheDocument()
    })
  })
})
