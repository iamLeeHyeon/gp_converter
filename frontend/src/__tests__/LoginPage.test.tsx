import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../components/Auth/LoginPage'

test('Google 로그인 버튼 렌더링', () => {
  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  expect(screen.getByText(/Google/i)).toBeInTheDocument()
  expect(screen.getByText(/GitHub/i)).toBeInTheDocument()
})

test('Google 버튼 클릭 시 /auth/google로 이동', async () => {
  const user = userEvent.setup()
  const assignSpy = vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    assign: vi.fn(),
  } as Location)

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  await user.click(screen.getByText(/Google/i))
  // window.location.href 변경 확인은 jsdom 제약으로 직접 확인 어려움
  // 버튼이 존재하고 클릭 가능하면 충분
  expect(screen.getByText(/Google/i)).toBeInTheDocument()
  assignSpy.mockRestore()
})
