import './PrLink.css'

type CodexStatus = 'not_started' | 'working' | 'progress' | 'pass' | 'exhausted' | 'failed' | 'stale'

interface CodexProgress {
  turn: number
  max_turns: number
  sha: string
}

interface PrLinkProps {
  url: string
  merged?: boolean
  /** @deprecated Use codexStatus instead */
  codexReviewed?: boolean
  codexStatus?: CodexStatus | null
  codexProgress?: CodexProgress | null
}

function extractPrNumber(url: string): string | null {
  const match = url.match(/\/pull\/(\d+)/)
  return match ? match[1] : null
}

function CodexBadge({
  status,
  progress,
}: {
  status: CodexStatus | null | undefined
  progress: CodexProgress | null | undefined
}) {
  if (!status || status === 'not_started') return null

  let label: string
  let className: string

  switch (status) {
    case 'working':
      label = 'codex working'
      className = 'pr-codex-badge pr-codex-badge--working'
      break
    case 'progress':
      label = progress ? `codex ${progress.turn}/${progress.max_turns}` : 'codex …'
      className = 'pr-codex-badge pr-codex-badge--progress'
      break
    case 'pass':
      label = 'codex pass'
      className = 'pr-codex-badge pr-codex-badge--pass'
      break
    case 'exhausted':
      label = 'codex exhausted'
      className = 'pr-codex-badge pr-codex-badge--exhausted'
      break
    case 'failed':
      label = 'codex failed'
      className = 'pr-codex-badge pr-codex-badge--failed'
      break
    case 'stale':
      label = 'codex stale'
      className = 'pr-codex-badge pr-codex-badge--stale'
      break
    default:
      return null
  }

  const titleSuffix = progress?.sha ? ` (${progress.sha.slice(0, 7)})` : ''

  return (
    <span className={className} title={`${label}${titleSuffix}`}>
      {label}
    </span>
  )
}

export function PrLink({ url, merged, codexReviewed, codexStatus, codexProgress }: PrLinkProps) {
  const prNumber = extractPrNumber(url)
  const label = prNumber ? `PR #${prNumber}` : 'PR'

  // Prefer new codexStatus; fall back to deprecated codexReviewed boolean.
  const effectiveStatus: CodexStatus | null | undefined =
    codexStatus !== undefined ? codexStatus : codexReviewed ? 'pass' : null

  return (
    <span className="pr-link-group">
      <a
        className="pr-link"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        title={url}
      >
        <svg className="pr-link-icon" viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
          <path d="M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z" />
        </svg>
        {label}
      </a>
      <CodexBadge status={effectiveStatus} progress={codexProgress} />
      {merged && <span className="pr-merged-badge">Merged</span>}
    </span>
  )
}
