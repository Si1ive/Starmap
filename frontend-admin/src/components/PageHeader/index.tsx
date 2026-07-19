import type { ReactNode } from 'react'

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
}

const PageHeader = ({ eyebrow, title, description, actions }: PageHeaderProps) => (
  <header className="admin-page-header">
    <div className="admin-page-header__copy">
      {eyebrow ? <p className="admin-eyebrow">{eyebrow}</p> : null}
      <h1>{title}</h1>
      {description ? <p>{description}</p> : null}
    </div>
    {actions ? <div className="admin-page-header__actions">{actions}</div> : null}
  </header>
)

export default PageHeader
