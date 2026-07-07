import { StrictMode } from 'react'
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

test('StrictMode에서 effect가 두 번 실행돼도 다시 /login으로 튕기지 않는다', () => {
  // 실제 브라우저에서 navigate('/', {replace:true})는 history.replaceState로
  // URL 해시를 지운다. StrictMode는 dev에서 effect를 한 번 더 실행하는데,
  // 재실행 가드가 없으면 두 번째 실행이 "해시 없음"으로 읽어 /login으로
  // 되돌려보낸다(실사례로 재현된 버그).
  Object.defineProperty(window, 'location', {
    value: { hash: '#access_token=abc&refresh_token=xyz', href: '' },
    writable: true,
    configurable: true,
  })
  mockNavigate.mockImplementation((path: string) => {
    if (path === '/') window.location.hash = ''
  })
  render(
    <StrictMode>
      <MemoryRouter><OAuthCallback /></MemoryRouter>
    </StrictMode>
  )
  expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
  expect(mockNavigate).not.toHaveBeenCalledWith('/login', { replace: true })
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
