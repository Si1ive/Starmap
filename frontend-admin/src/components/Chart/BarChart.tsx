import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

interface BarChartProps {
  data: { name: string; value: number }[]
  title?: string
  color?: string
  height?: number
}

const BarChart = ({ data, title = '', color = '#1890ff', height = 300 }: BarChartProps) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return

    chartInstance.current = echarts.init(chartRef.current)

    const option: echarts.EChartsOption = {
      title: {
        text: title,
        left: 'center',
        textStyle: { fontSize: 14, fontWeight: 'normal' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      xAxis: {
        type: 'category',
        data: data.map((item) => item.name),
        axisLine: { lineStyle: { color: '#dce4df' } },
        axisTick: { show: false },
        axisLabel: { color: '#5f6d66', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: '#7b8982', fontSize: 10 },
        splitLine: { lineStyle: { color: '#e7ede9' } },
      },
      series: [
        {
          data: data.map((item) => item.value),
          type: 'bar',
          barMaxWidth: 56,
          itemStyle: {
            color,
            borderRadius: [3, 3, 0, 0],
          },
        },
      ],
      grid: {
        left: 12,
        right: 14,
        top: 22,
        bottom: 4,
        containLabel: true,
      },
    }

    chartInstance.current.setOption(option)

    const handleResize = () => {
      chartInstance.current?.resize()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chartInstance.current?.dispose()
    }
  }, [data, title, color])

  return <div ref={chartRef} style={{ width: '100%', height }} />
}

export default BarChart
