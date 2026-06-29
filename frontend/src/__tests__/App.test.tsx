import { render } from '@testing-library/react'
import App from '../App'

test('앱이 렌더링된다', () => {
  render(<App />)
  expect(document.body).toBeTruthy()
})
