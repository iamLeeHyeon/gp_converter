import type { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  children: ReactNode
}

export default function AuthLayout({ title, subtitle, children }: Props) {
  return (
    <div style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div className="card" style={{ width: '100%', maxWidth: 360 }}>
        <h1 style={{ fontSize: '1.75rem', textAlign: 'center' }}>{title}</h1>
        {subtitle && (
          <p style={{ marginTop: 8, color: 'var(--color-muted)', fontSize: '0.875rem', textAlign: 'center' }}>
            {subtitle}
          </p>
        )}
        <div style={{ marginTop: 24 }}>{children}</div>
      </div>
    </div>
  )
}
