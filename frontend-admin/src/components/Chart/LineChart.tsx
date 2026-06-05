import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

interface LineChartProps {
  data: { date: string; count: number }[]
  title?: string
  color?: string
  height?: number
}

const LineChart = ({ data, title = '', color = '#1890ff', height = 300 }: LineChartProps) => {
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
        formatter: '{b}: {c}',
      },
      xAxis: {
        type: 'category',
        data: data.map((item) => item.date),
        axisLabel: { rotate: 30 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
      },
      series: [
        {
          data: data.map((item) => item.count),
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 8,
          lineStyle: { color, width: 3 },
          itemStyle: { color },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: color + '40' },
                { offset: 1, color: color + '05' },
              ],
            },
          },
        },
      ],
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
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

export default LineChart
