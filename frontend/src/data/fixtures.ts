export type TaskState = 'ready' | 'running' | 'review' | 'done'

export interface StudyTask {
  id: string
  title: string
  subject: string
  duration: number
  reason: string
  state: TaskState
  kind: 'review' | 'practice' | 'lesson'
}

export interface AgentStep {
  id: string
  title: string
  detail: string
  duration: string
  status: 'completed' | 'running' | 'failed' | 'waiting'
}

export type AgentHistoryState = 'complete' | 'failed' | 'approval'

export interface AgentHistoryItem {
  id: string
  title: string
  subject: string
  time: string
  state: AgentHistoryState
}

export type ActiveTaskKind = 'agent' | 'source' | 'practice'

export interface ActiveTask {
  id: string
  kind: ActiveTaskKind
  title: string
  detail: string
  status: string
  route: string
}

export const agentHistory: AgentHistoryItem[] = [
  {
    id: 'queue-front',
    title: '循环队列的 front 怎么算',
    subject: '数据结构 · 栈和队列',
    time: '今天 09:42',
    state: 'complete',
  },
  {
    id: 'practice-draft',
    title: '根据错题生成一组专项练习',
    subject: '循环队列 · 练习生成',
    time: '昨天 20:16',
    state: 'failed',
  },
  {
    id: 'priority-adjustment',
    title: '调整巩固优先级',
    subject: '操作系统 · 死锁',
    time: '昨天 18:03',
    state: 'approval',
  },
  {
    id: 'interrupt-explanation',
    title: '中断、异常和系统调用的区别',
    subject: '计算机组成原理 · 中央处理器',
    time: '7 月 16 日',
    state: 'complete',
  },
  {
    id: 'cache-access-time',
    title: 'Cache 平均访问时间怎么分析',
    subject: '计算机组成原理 · 存储系统',
    time: '7 月 15 日',
    state: 'complete',
  },
]

export const activeTasks: ActiveTask[] = [
  {
    id: 'agent-queue',
    kind: 'agent',
    title: '循环队列讲解',
    detail: '正在组织分层讲解 · 4/6',
    status: '运行中',
    route: '/agent/queue?state=running&hold=1',
  },
  {
    id: 'source-ingestion',
    kind: 'source',
    title: '我的组成原理错题笔记.pdf',
    detail: '正在建立索引 · 第 18/28 页',
    status: '入库中',
    route: '/sources',
  },
  {
    id: 'practice-queue',
    kind: 'practice',
    title: '循环队列验证',
    detail: '第 1/2 题 · 草稿已自动保存',
    status: '进行中',
    route: '/practice/queue-check?question=1',
  },
]

export const todayTasks: StudyTask[] = [
  {
    id: 'queue-review',
    title: '循环队列复习与 2 题验证',
    subject: '数据结构 · 栈和队列',
    duration: 12,
    reason: '昨日同类题答错，今天到达首次复习间隔',
    state: 'review',
    kind: 'review',
  },
  {
    id: 'cache-practice',
    title: 'Cache 平均访问时间专项',
    subject: '计算机组成原理 · 存储系统',
    duration: 25,
    reason: '本周目标中还有 6 道专项题未完成',
    state: 'ready',
    kind: 'practice',
  },
  {
    id: 'interrupt-lesson',
    title: '中断与异常易混点讲解',
    subject: '计算机组成原理 · 中央处理器',
    duration: 18,
    reason: '最近两次练习都混淆了响应时机',
    state: 'ready',
    kind: 'lesson',
  },
  {
    id: 'mistake-recap',
    title: '昨日错题快速复盘',
    subject: '跨学科 · 4 道到期错题',
    duration: 15,
    reason: '4 道错题已到首次回忆间隔',
    state: 'ready',
    kind: 'review',
  },
]

export const agentSteps: AgentStep[] = [
  {
    id: 'intent',
    title: '识别学习意图',
    detail: '希望理解公式来源，而不是直接记忆结论',
    duration: '0.3s',
    status: 'completed',
  },
  {
    id: 'outline',
    title: '检索大纲考点',
    detail: '栈和队列的顺序存储结构',
    duration: '0.7s',
    status: 'completed',
  },
  {
    id: 'knowledge',
    title: '检索知识与相关题',
    detail: '2 个知识片段，4 道候选题',
    duration: '1.4s',
    status: 'completed',
  },
  {
    id: 'mastery',
    title: '读取掌握证据',
    detail: '同类题最近 2 次错误，未使用提示',
    duration: '0.5s',
    status: 'completed',
  },
  {
    id: 'explain',
    title: '组织分层讲解',
    detail: '正在核对公式定义与题目中的 rear 语义',
    duration: '进行中',
    status: 'running',
  },
  {
    id: 'practice',
    title: '准备验证题',
    detail: '等待讲解完成',
    duration: '—',
    status: 'waiting',
  },
]

export const completedAgentSteps: AgentStep[] = agentSteps.map((step) => ({
  ...step,
  status: 'completed',
  duration: step.id === 'explain' ? '2.1s' : step.id === 'practice' ? '1.2s' : step.duration,
  detail:
    step.id === 'explain'
      ? '已生成结论、推导和易错点'
      : step.id === 'practice'
        ? '已创建 2 道验证题草稿'
        : step.detail,
}))

export const queueQuestion = {
  stem:
    '若循环队列以数组 Q[0...m-1] 作为其存储结构，变量 rear 表示循环队列中队尾元素的实际位置，其移动按 rear=(rear+1) MOD m 进行，变量 length 表示当前循环队列中的元素个数，则循环队列队首元素的实际位置是（ ）。',
  options: [
    { key: 'A', text: 'rear-length' },
    { key: 'B', text: '(rear-length+m) MOD m' },
    { key: 'C', text: '(1+rear+m-length) MOD m' },
    { key: 'D', text: '(rear+length-1) MOD m' },
  ],
  answer: 'C',
}

export const agentSources = [
  {
    type: 'outline',
    label: '官方大纲',
    title: '栈和队列的顺序存储结构',
    detail: '数据结构 / 栈、队列和数组',
  },
  {
    type: 'question',
    label: '原题',
    title: '试卷4.pdf · 第 1 题',
    detail: '第 1 页 · 已审核',
  },
  {
    type: 'knowledge',
    label: '平台知识',
    title: '循环队列',
    detail: '定义、下标关系与判空判满',
  },
]

export const outlineSubjects = [
  {
    id: 'data-structure',
    name: '数据结构',
    progress: '学习中',
    active: 4,
    review: 3,
    chapters: [
      { name: '线性表', state: '待巩固', evidence: '最近 8 题 · 6 题正确' },
      { name: '栈、队列和数组', state: '待巩固', evidence: '循环队列连续错误 2 次' },
      { name: '树与二叉树', state: '学习中', evidence: '最近复习于 2 天前' },
      { name: '图', state: '证据不足', evidence: '仅完成 1 道题' },
    ],
  },
  {
    id: 'computer-organization',
    name: '计算机组成原理',
    progress: '学习中',
    active: 5,
    review: 4,
    chapters: [
      { name: '数据的表示和运算', state: '学习中', evidence: '补码运算待验证' },
      { name: '存储系统', state: '待巩固', evidence: 'Cache 访问时间用时偏长' },
      { name: '中央处理器', state: '学习中', evidence: '中断与异常容易混淆' },
    ],
  },
  {
    id: 'operating-system',
    name: '操作系统',
    progress: '待巩固',
    active: 3,
    review: 5,
    chapters: [
      { name: '进程与线程', state: '学习中', evidence: '同步互斥正确率稳定' },
      { name: '死锁', state: '待巩固', evidence: '连续错误 3 次' },
      { name: '内存管理', state: '学习中', evidence: '页表计算待复习' },
    ],
  },
  {
    id: 'network',
    name: '计算机网络',
    progress: '证据不足',
    active: 2,
    review: 1,
    chapters: [
      { name: '数据链路层', state: '证据不足', evidence: '尚未完成本周诊断' },
      { name: '网络层', state: '学习中', evidence: '完成 4 道路由题' },
      { name: '传输层', state: '未学习', evidence: '暂无学习记录' },
    ],
  },
]

export const mistakeClusters = [
  {
    title: '条件遗漏',
    description: '公式中漏掉边界或“包含当前元素”的条件',
    point: '循环队列下标计算',
    count: 3,
    state: '待首次复习',
    next: '今天 · 1 道无提示验证',
  },
  {
    title: '概念混淆',
    description: '把中断、异常和系统调用的触发来源混为一谈',
    point: '中断与异常',
    count: 2,
    state: '待验证',
    next: '建议继续 · 对比辨析 3 题',
  },
  {
    title: '计算路径不稳定',
    description: 'Cache 平均访问时间分母选择不一致',
    point: 'Cache 性能计算',
    count: 2,
    state: '学习中',
    next: '等待新证据 · 变式题',
  },
]

export const sourceFiles = [
  {
    name: '王道数据结构复习指导.pdf',
    meta: '平台资料 · 312 页',
    status: 'ready',
    detail: '最近引用：循环队列 · 今天 09:42',
  },
  {
    name: '试卷4.pdf',
    meta: '个人资料 · 47 道题',
    status: 'ready',
    detail: '已完成解析与题目审核',
  },
  {
    name: '我的组成原理错题笔记.pdf',
    meta: '个人资料 · 28 页',
    status: 'processing',
    detail: '正在建立索引 · 第 18/28 页',
  },
  {
    name: '网络层补充讲义.pdf',
    meta: '个人资料 · 16 页',
    status: 'partial',
    detail: '14 页可用，2 页图片识别失败',
  },
]
