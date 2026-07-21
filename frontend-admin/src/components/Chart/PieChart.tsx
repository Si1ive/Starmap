import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

interface PieChartProps {
  data: { name: string; value: number }[]
  title?: string
  height?: number
}

const COLORS = ['#31594e', '#527d6d', '#b87922', '#b24c45', '#6f7d76', '#7c9d8f', '#4c7568', '#d29a4d']

const PieChart = ({ data, title = '', height = 300 }: PieChartProps) => {
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
        trigger: 'item',
        formatter: '{b}: {c} ({d}%)',
      },
      legend: {
        orient: 'vertical',
        right: '5%',
        top: 'center',
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
        textStyle: {
          color: '#5f6d66',
          fontSize: 11,
        },
      },
      series: [
        {
          type: 'pie',
          radius: ['48%', '72%'],
          center: ['36%', '50%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 3,
            borderColor: '#fff',
            borderWidth: 3,
          },
          label: {
            show: false,
            position: 'center',
          },
          emphasis: {
            label: {
              show: true,
              color: '#18211d',
              fontSize: 18,
              fontWeight: 700,
            },
          },
          labelLine: { show: false },
          data: data.map((item, index) => ({
            ...item,
            itemStyle: { color: COLORS[index % COLORS.length] },
          })),
        },
      ],
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
  }, [data, title])

  return <div ref={chartRef} style={{ width: '100%', height }} />
}

export default PieChart
