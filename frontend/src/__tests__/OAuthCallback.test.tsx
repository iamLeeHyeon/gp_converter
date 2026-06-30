import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import OAuthCallback from '../components/Auth/OAuthCallback'
import { useAuthStore } from '../store/authStore'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

beforeEach(() => {
  mockNavigate.mockClear()
  useAuthStore.getState().logout()
})

afterEach(() => {
  Object.defineProperty(window, 'location', {
    value: { hash: '', href: '' },
    writable: true,
    configurable: true,
  })
})

test('토큰 있음: setToken 호출 및 /로 이동', () => {
  Object.defineProperty(window, 'location', {
    value: { hash: '#access_token=abc&refresh_token=xyz', href: '' },
    writable: true,
    configurable: true,
  })
  render(<MemoryRouter><OAuthCallback /></MemoryRouter>)
  expect(localStorage.getItem('access_token')).toBe('abc')
  expect(localStorage.getItem('refresh_token')).toBe('xyz')
  expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
})

test('토큰 없음: /login으로 이동', () => {
  Object.defineProperty(window, 'location', {
    value: { hash: '', href: '' },
    writable: true,
    configurable: true,
  })
  render(<MemoryRouter><OAuthCallback /></MemoryRouter>)
  expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
})
