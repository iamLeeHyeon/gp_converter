import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { connectSSE } from '../lib/sse'
import type { ProgressEvent } from '../lib/sse'

// jsdom은 EventSource 미지원 → 모킹
class MockEventSource {
  url: string
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
  }

  close() {
    this.closed = true
  }

  // 테스트 헬퍼: 메시지 발생 트리거
  emit(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }

  triggerError() {
    this.onerror?.()
  }
}

let mockES: MockEventSource

// MockEventSource 추적용 래퍼 클래스
class TrackingEventSource extends MockEventSource {
  constructor(url: string) {
    super(url)
    mockES = this
  }
}

beforeEach(() => {
  vi.stubGlobal('EventSource', TrackingEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('connectSSE', () => {
  it('함수 호출 시 cleanup 함수 반환', () => {
    const cleanup = connectSSE('job1', vi.fn(), vi.fn(), vi.fn())
    expect(typeof cleanup).toBe('function')
  })

  it('올바른 URL로 EventSource 생성', () => {
    connectSSE('job42', vi.fn(), vi.fn(), vi.fn())
    expect(mockES.url).toBe('/jobs/job42/stream')
  })

  it('진행 메시지 수신 시 onProgress 호출', () => {
    const onProgress = vi.fn()
    connectSSE('job1', onProgress, vi.fn(), vi.fn())
    const event: ProgressEvent = { status: 'running', pct: 50, step: 'OMR' }
    mockES.emit(event)
    expect(onProgress).toHaveBeenCalledWith(event)
  })

  it('status=done 수신 시 onDone 호출 및 연결 종료', () => {
    const onDone = vi.fn()
    connectSSE('job1', vi.fn(), onDone, vi.fn())
    mockES.emit({ status: 'done', pct: 100, step: '완료' })
    expect(onDone).toHaveBeenCalled()
    expect(mockES.closed).toBe(true)
  })

  it('status=failed 수신 시 onError 호출 및 연결 종료', () => {
    const onError = vi.fn()
    connectSSE('job1', vi.fn(), vi.fn(), onError)
    mockES.emit({ status: 'failed', pct: 0, step: 'OMR 실패' })
    expect(onError).toHaveBeenCalledWith('OMR 실패')
    expect(mockES.closed).toBe(true)
  })

  it('onerror 발생 시 onError 호출 및 연결 종료', () => {
    const onError = vi.fn()
    connectSSE('job1', vi.fn(), vi.fn(), onError)
    mockES.triggerError()
    expect(onError).toHaveBeenCalledWith('SSE 연결 오류')
    expect(mockES.closed).toBe(true)
  })

  it('cleanup 함수 호출 시 연결 종료', () => {
    const cleanup = connectSSE('job1', vi.fn(), vi.fn(), vi.fn())
    cleanup()
    expect(mockES.closed).toBe(true)
  })
})
