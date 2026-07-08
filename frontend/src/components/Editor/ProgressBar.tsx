interface Props {
  pct: number
  step: string
  visible: boolean
}

const STEP_LABELS: Record<string, string> = {
  tab_detect: 'TAB 보표 감지 중...',
  omr: 'OMR 추론 중...',
  gp5_build: 'GP5 변환 중...',
  audiveris: 'Audiveris 변환 중...',
  musicxml_convert: 'MusicXML 변환 중...',
}

export default function ProgressBar({ pct, step, visible }: Props) {
  return (
    <div
      data-testid="progress-container"
      style={{
        visibility: visible ? 'visible' : 'hidden',
        padding: '16px 0',
      }}
    >
      <p style={{ marginBottom: 8, fontSize: 13, color: 'rgba(255,255,255,0.9)' }}>
        {STEP_LABELS[step] || '변환 중...'}  {pct}%
      </p>
      <div
        style={{
          background: 'rgba(255,255,255,0.25)',
          borderRadius: 4,
          height: 8,
          overflow: 'hidden',
        }}
      >
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{
            width: `${pct}%`,
            height: '100%',
            background: '#ffffff',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  )
}
