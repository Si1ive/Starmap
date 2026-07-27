import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownContentProps {
  content: string | null | undefined
  className?: string
}

/**
 * Render model-authored Markdown without enabling raw HTML.
 * GFM adds tables, task lists, strikethrough and autolinks while ReactMarkdown
 * keeps HTML-looking model output as text instead of injecting it into the DOM.
 */
export default function MarkdownContent({ content, className }: MarkdownContentProps) {
  const value = typeof content === 'string' ? content.trim() : ''
  if (!value) return null

  return (
    <div className={['agent-markdown', className].filter(Boolean).join(' ')}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{value}</ReactMarkdown>
    </div>
  )
}
