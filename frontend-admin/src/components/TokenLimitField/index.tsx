import { useEffect, useRef } from 'react'
import { InputNumber, Segmented } from 'antd'

type TokenLimitFieldProps = {
  value?: number | null
  onChange?: (value: number | null) => void
  defaultValue: number
  min?: number
  max?: number
}

const TokenLimitField = ({
  value,
  onChange,
  defaultValue,
  min = 1,
  max = 200000,
}: TokenLimitFieldProps) => {
  const lastLimitedValue = useRef(defaultValue)
  const isUnlimited = value === null

  useEffect(() => {
    if (typeof value === 'number') {
      lastLimitedValue.current = value
    }
  }, [value])

  const switchMode = (mode: string | number) => {
    if (mode === 'unlimited') {
      if (typeof value === 'number') {
        lastLimitedValue.current = value
      }
      onChange?.(null)
      return
    }

    onChange?.(lastLimitedValue.current || defaultValue)
  }

  return (
    <div className={`token-limit-field token-limit-field--${isUnlimited ? 'unlimited' : 'limited'}`}>
      <Segmented
        block
        className="token-limit-field__mode"
        value={isUnlimited ? 'unlimited' : 'limited'}
        options={[
          { label: '按额度', value: 'limited' },
          { label: '不设上限', value: 'unlimited' },
        ]}
        onChange={switchMode}
      />
      <div className="token-limit-field__value" aria-live="polite">
        {isUnlimited ? (
          <div className="token-limit-field__unlimited">
            <span className="token-limit-field__infinity" aria-hidden="true">∞</span>
            <span>
              <strong>不发送输出上限</strong>
              <small>实际长度仍受模型上下文与供应商限制</small>
            </span>
          </div>
        ) : (
          <InputNumber
            aria-label="最大输出 Token 数"
            min={min}
            max={max}
            precision={0}
            value={typeof value === 'number' ? value : lastLimitedValue.current}
            addonAfter="Token"
            onChange={(nextValue) => {
              if (typeof nextValue === 'number') {
                lastLimitedValue.current = nextValue
                onChange?.(nextValue)
              }
            }}
          />
        )}
      </div>
    </div>
  )
}

export default TokenLimitField
