import './BreadcrumbPills.css'

interface BreadcrumbPillsProps {
  epicTitle: string
  featureTitle: string
  epicColor: string
  onEpicClick?: () => void
  onFeatureClick?: () => void
}

export function BreadcrumbPills({
  epicTitle,
  featureTitle,
  epicColor,
  onEpicClick,
  onFeatureClick,
}: BreadcrumbPillsProps) {
  return (
    <div className="breadcrumb-pills">
      <span
        className="pill pill-epic"
        style={{ '--pill-color': epicColor } as React.CSSProperties}
        onClick={onEpicClick}
        role={onEpicClick ? 'button' : undefined}
      >
        {epicTitle}
      </span>
      {featureTitle && (
        <span
          className="pill pill-feature"
          style={{ '--pill-color': epicColor } as React.CSSProperties}
          onClick={onFeatureClick}
          role={onFeatureClick ? 'button' : undefined}
        >
          {featureTitle}
        </span>
      )}
    </div>
  )
}
