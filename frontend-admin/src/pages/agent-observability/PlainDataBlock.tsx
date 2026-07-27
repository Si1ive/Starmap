interface PlainDataBlockProps {
  value: unknown
  emptyText?: string
  maxHeight?: number
}

const PlainDataBlock = ({ value, emptyText = '无数据', maxHeight = 320 }: PlainDataBlockProps) => {
  const text = value === undefined || value === null ? '' : JSON.stringify(value, null, 2)

  return (
    <pre className="memory-data-block" style={{ maxHeight }} tabIndex={0}>
      {text || emptyText}
    </pre>
  )
}

export default PlainDataBlock
