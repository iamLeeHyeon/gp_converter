import { render, screen } from '@testing-library/react'
import ProgressBar from '../components/Editor/ProgressBar'

test('pct 60이면 바 너비 60%', () => {
  render(<ProgressBar pct={60} step="omr" visible={true} />)
  const bar = screen.getByRole('progressbar')
  expect(bar).toHaveStyle({ width: '60%' })
})

test('visible=false면 숨김', () => {
  render(<ProgressBar pct={50} step="" visible={false} />)
  const container = screen.getByTestId('progress-container')
  expect(container).not.toBeVisible()
})
