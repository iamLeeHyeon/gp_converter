import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../components/Auth/LoginPage'

const savedLocation = window.location

afterEach(() => {
  Object.defineProperty(window, 'location', {
    value: savedLocation,
    writable: true,
    configurable: true,
  })
})

test('Google/GitHub 로그인 버튼 렌더링', () => {
  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  expect(screen.getByText(/Google/i)).toBeInTheDocument()
  expect(screen.getByText(/GitHub/i)).toBeInTheDocument()
})

test('Google 버튼 클릭 시 /auth/google로 이동', async () => {
  const user = userEvent.setup()
  const hrefSetter = vi.fn()
  Object.defineProperty(window, 'location', {
    value: {
      get href() { return '' },
      set href(v: string) { hrefSetter(v) },
      assign: vi.fn(),
      replace: vi.fn(),
    },
    writable: true,
    configurable: true,
  })

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  await user.click(screen.getByText(/Google/i))
  expect(hrefSetter).toHaveBeenCalledWith('/auth/google')
})

test('GitHub 버튼 클릭 시 /auth/github로 이동', async () => {
  const user = userEvent.setup()
  const hrefSetter = vi.fn()
  Object.defineProperty(window, 'location', {
    value: {
      get href() { return '' },
      set href(v: string) { hrefSetter(v) },
      assign: vi.fn(),
      replace: vi.fn(),
    },
    writable: true,
    configurable: true,
  })

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  await user.click(screen.getByText(/GitHub/i))
  expect(hrefSetter).toHaveBeenCalledWith('/auth/github')
})

test('logs in with email and password', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'a', refresh_token: 'r' }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ email: 'a@x.com', plan: 'free', email_verified: true }),
    }))

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByPlaceholderText('비밀번호'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByText('이메일로 로그인'))

  await waitFor(() => {
    expect(localStorage.getItem('access_token')).toBe('a')
  })
})

test('shows error on failed login', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
    ok: false,
    json: async () => ({ detail: '이메일 또는 비밀번호가 올바르지 않습니다.' }),
  }))

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByPlaceholderText('비밀번호'), { target: { value: 'wrong' } })
  fireEvent.click(screen.getByText('이메일로 로그인'))

  await waitFor(() => {
    expect(screen.getByText('이메일 또는 비밀번호가 올바르지 않습니다.')).toBeInTheDocument()
  })
})
