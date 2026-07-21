import { AlertTriangle, ArrowRight, Check, LoaderCircle, RefreshCw, Save, X } from 'lucide-react'
import {
  Button,
  EmptyState,
  PageHeading,
  ProgressBar,
  SourceBadge,
  StatusMark,
} from '../components/Primitives'

export default function StateGalleryPage() {
  return (
    <div className="page page--wide state-page">
      <PageHeading
        description="用于检查状态语义、控件尺寸、长文案与键盘焦点，不是面向用户的功能页。"
        eyebrow="UI 状态检查"
        title="408 Agent 组件基线"
      />

      <section className="state-section">
        <h2>操作</h2>
        <div className="state-row">
          <Button icon={<ArrowRight size={16} />}>主要操作</Button>
          <Button icon={<Save size={16} />} tone="secondary">保存草稿</Button>
          <Button tone="quiet">稍后处理</Button>
          <Button icon={<X size={16} />} tone="danger">删除记录</Button>
          <Button disabled icon={<LoaderCircle size={16} />}>正在提交</Button>
        </div>
      </section>

      <section className="state-section">
        <h2>任务状态</h2>
        <div className="state-row">
          <StatusMark tone="success">已完成</StatusMark>
          <StatusMark tone="running">运行中</StatusMark>
          <StatusMark tone="warning">等待确认</StatusMark>
          <StatusMark tone="error">可重试</StatusMark>
          <StatusMark tone="neutral">证据不足</StatusMark>
        </div>
      </section>

      <section className="state-section">
        <h2>来源边界</h2>
        <div className="state-row">
          <SourceBadge type="outline">官方大纲</SourceBadge>
          <SourceBadge type="question">原题</SourceBadge>
          <SourceBadge type="knowledge">平台知识</SourceBadge>
          <SourceBadge type="personal">个人资料</SourceBadge>
          <SourceBadge type="generated">AI 补充</SourceBadge>
          <SourceBadge type="inference">模型推断</SourceBadge>
        </div>
      </section>

      <section className="state-section state-section--grid">
        <div>
          <h2>进度</h2>
          <div className="gallery-progress">
            <span>资料解析 · 18/28 页</span>
            <ProgressBar value={64} />
          </div>
          <div className="gallery-progress">
            <span>Agent 执行 · 4/6 步</span>
            <ProgressBar value={72} />
          </div>
        </div>
        <div>
          <h2>持久错误</h2>
          <div className="gallery-error">
            <AlertTriangle size={19} />
            <span>
              <strong>生成逐题提示时响应超时</strong>
              <small>3 道练习草稿已保留。</small>
            </span>
            <Button icon={<RefreshCw size={15} />} tone="secondary">局部重试</Button>
          </div>
        </div>
      </section>

      <section className="state-section">
        <EmptyState
          action={<Button icon={<ArrowRight size={16} />}>与 Agent 对话</Button>}
          description="开始一次对话后，学习内容会根据问题和记录逐渐形成。"
          title="还没有学习记录"
        />
      </section>

      <section className="state-section">
        <h2>稳定尺寸检查</h2>
        <div className="state-option-list">
          <button className="is-selected" type="button"><span>A</span><strong>短选项</strong><i><Check size={15} /></i></button>
          <button type="button">
            <span>B</span>
            <strong>这是一个会换行的长选项，用于确认两行以上文字不会改变标记、图标和点击区域的对齐方式</strong>
            <i />
          </button>
        </div>
      </section>
    </div>
  )
}
