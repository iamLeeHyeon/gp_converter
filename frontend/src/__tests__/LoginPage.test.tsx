import { render, screen } from '@testing-library/react'
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
