import './PrLink.css'

interface PrLinkProps {
  url: string
  merged?: boolean
  codexReviewed?: boolean
}

function extractPrNumber(url: string): string | null {
  const match = url.match(/\/pull\/(\d+)/)
  return match ? match[1] : null
}

export function PrLink({ url, merged, codexReviewed }: PrLinkProps) {
  const prNumber = extractPrNumber(url)
  const label = prNumber ? `PR #${prNumber}` : 'PR'

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
      {codexReviewed && (
        <span
          className="pr-codex-badge"
          title="codex has engaged with this PR"
        >
          codex reviewed
        </span>
      )}
      {merged && <span className="pr-merged-badge">Merged</span>}
    </span>
  )
}
