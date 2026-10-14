/**
 * Mock 对话流模拟器：按 API 契约的 SSE 事件协议逐事件推送。
 * 支持：增量文本、引用（RAG）、结构化卡片（判决预测/类案检索）、中断、用量统计。
 * 生成的消息会写回 mock 内存库，刷新消息列表即可取到完整落库结果。
 */
import { delay, nowISO } from '@/api/client'
import { uid } from '@/lib/utils'
import { messages as messageStore, conversations } from './data'
import type { ChatCompletionRequest } from '@/types/api'
import type { ChatEventName } from '@/api/sse'

type EventHandler = (name: ChatEventName, data: Record<string, unknown>) => void

/* ---------- 回答脚本 ---------- */

const GAMBLING_ANSWER = [
  '### 结论\n你描述的情况属于**赌博类违法行为**，可能面临行政处罚，情节严重的可能构成犯罪。\n',
  '### 处罚依据\n根据《治安管理处罚法》第七十条 [1]：\n\n- **一般情形**：以营利为目的为赌博提供条件，或参与赌博赌资较大 → **5 日以下拘留或 500 元以下罚款**\n- **情节严重**：→ **10-15 日拘留，并处 500-3000 元罚款**\n\n若以营利为目的**开设赌场**，则可能构成《刑法》第三百零三条 [2] 规定的开设赌场罪。\n',
  '### 需要关注的因素\n1. 营利金额与抽头数额\n2. 参赌人数、持续时间\n3. 是否有组织、招揽行为\n\n> ⚠️ 以上分析由 AI 生成，仅供参考，不构成法律意见。建议携带材料咨询执业律师。',
].join('\n')

const INJURY_ANSWER = [
  '### 定性\n你的描述可能构成**故意伤害行为**，需依据伤情鉴定结论区分处理：\n\n- **轻微伤**：属治安案件，依《治安管理处罚法》第四十三条处 5-10 日拘留并处罚款\n- **轻伤及以上**：构成故意伤害罪，依《刑法》第二百三十四条 [1] 处三年以下有期徒刑、拘役或管制\n',
  '### 量刑参考\n常见量刑情节：\n\n| 情节 | 倾向 |\n| --- | --- |\n| 自首、认罪认罚 | 从宽 |\n| 赔偿并取得谅解 | 从轻，缓刑可能性大 |\n| 持械、有预谋 | 从重 |\n\n> ⚠️ 以上分析由 AI 生成，仅供参考，不构成法律意见。',
].join('\n')

const GENERIC_ANSWER = (q: string) =>
  [
    `### 回答\n关于「${q.slice(0, 40)}${q.length > 40 ? '…' : ''}」，从法律角度分析如下：\n`,
    '1. **定性分析**：需结合行为主体、主观方面、客体与客观方面四要件判断；\n2. **法律依据**：请补充案件的具体细节（时间、地点、行为、后果），我可以进一步检索对应法条；\n3. **建议**：保留好相关证据材料（合同、转账记录、聊天记录等）。\n\n> ⚠️ 以上内容由 AI 生成，仅供参考，不构成法律意见。',
  ].join('\n')

const PREDICTION_TEXT =
  '基于案情要素抽取与模型推理，预测结果如下（仅供研究参考）：'

const CASE_TEXT = '为你检索到以下相似案例：'

const CONTRACT_TEXT = [
  '### 合同审查结果\n已逐条审查你提供的合同文本，识别出以下法律风险（详见风险清单卡片）：\n\n1. **违约金上限缺失**——建议约定不超过合同总额 30%\n2. **争议解决条款不利**——管辖法院约定在对方所在地\n3. **知识产权归属不明**——成果归属未明确约定\n\n> ⚠️ 以上分析由 AI 生成，仅供参考，不构成法律意见。',
].join('\n')

const DOC_TEXT = '已根据你提供的要素生成文书初稿，可直接复制或下载（见下方文书卡片）：'

const COMPLAINT_DOC = [
  '民事起诉状',
  '',
  '原告：张某某，男，19XX年X月X日出生，汉族，住XX市XX区XX路XX号。',
  '被告：李某某，男，19XX年X月X日出生，汉族，住XX市XX区XX路XX号。',
  '',
  '诉讼请求：',
  '一、判令被告偿还原告借款本金人民币 50,000 元；',
  '二、判令被告支付自 2025 年 6 月 1 日起至实际清偿之日止的利息（按 LPR 计算）；',
  '三、本案诉讼费用由被告承担。',
  '',
  '事实与理由：',
  '2025 年 5 月，被告以资金周转为由向原告借款人民币 50,000 元，约定 2025 年 8 月底归还，并出具借条一份。借款到期后，原告多次催要，被告以各种理由推脱，至今未偿还。原告认为，原、被告之间的借贷关系合法有效，被告拒不还款的行为侵害了原告的合法权益。',
  '',
  '据此，原告依据《中华人民共和国民事诉讼法》第一百二十二条之规定，特向贵院提起诉讼，请求依法判如所请。',
  '',
  '此致',
  'XX市XX区人民法院',
  '',
  '具状人：张某某',
  '2026 年 10 月 14 日',
].join('\n')

const PREDICTION_REASONING =
  '正在抽取案情要素：识别主体、行为方式、危害后果与数额 → 与 CAIL2018 训练分布中的相似案例匹配 → 结合量刑指导意见校验刑期区间回归结果。'

/* ---------- 工具 ---------- */

function* chunkify(text: string): Generator<string> {
  const chunks = text.match(/[\s\S]{1,3}/g) ?? []
  for (const c of chunks) yield c
}

function persistHistory(req: ChatCompletionRequest) {
  const { conversation_id: cid } = req
  if (!messageStore[cid]) messageStore[cid] = []
  // 以请求携带的上下文为准重建历史（天然支持"重新生成"）
  messageStore[cid] = req.messages.map((m) => ({
    id: uid('m'),
    conversation_id: cid,
    role: m.role,
    content_type: 'markdown' as const,
    content: m.content,
    status: 'done' as const,
    created_at: nowISO(),
  }))
  const conv = conversations.find((c) => c.id === cid)
  if (conv) {
    conv.last_message_at = nowISO()
    const firstUser = req.messages.find((m) => m.role === 'user')
    if (conv.title === '新对话' && firstUser) conv.title = firstUser.content.slice(0, 24)
  }
}

function persistAssistant(cid: string, content: string, extra: Partial<import('@/types/api').Message>) {
  const msg: import('@/types/api').Message = {
    id: uid('m'),
    conversation_id: cid,
    role: 'assistant',
    content_type: 'markdown',
    content,
    status: 'done',
    created_at: nowISO(),
    ...extra,
  }
  messageStore[cid] = [...(messageStore[cid] ?? []), msg]
}

/* ---------- 主流程 ---------- */

export async function mockChatStream(
  req: ChatCompletionRequest,
  onEvent: EventHandler,
  signal: AbortSignal,
): Promise<void> {
  await delay(250 + Math.random() * 350) // 首字延迟
  if (signal.aborted) return

  persistHistory(req)
  const question = [...req.messages].reverse().find((m) => m.role === 'user')?.content ?? ''
  const ragOn = !!req.retrieval?.dataset_ids?.length
  const agentId = req.agent_id

  let citations: import('@/types/api').Citation[] | undefined

  // 1'') 思维链（判决预测等推理场景，正文前推送）
  let reasoningText = ''
  if (agentId === 'a_1002') {
    for (const piece of PREDICTION_REASONING.match(/[\s\S]{1,6}/g) ?? []) {
      if (signal.aborted) return
      reasoningText += piece
      onEvent('reasoning', { delta: piece })
      await delay(40)
    }
    await delay(200)
  }

  // 2) 选择回答脚本
  let text: string
  let card: import('@/types/api').MessageCard | undefined
  let citesLaw = false // 脚本正文是否引用了法条（需配套 citations 事件）

  if (agentId === 'a_1002') {
    // 判决预测：短文本 + 结构化卡片
    text = PREDICTION_TEXT
    citesLaw = true
    card = {
      card_type: 'prediction',
      payload: {
        crime: /赌/.test(question) ? '开设赌场罪' : '故意伤害罪',
        confidence: 0.86,
        punishment: {
          type: /赌/.test(question) ? '有期徒刑并处罚金' : '有期徒刑、拘役或者管制',
          detention_days: /赌/.test(question) ? [6, 12] : [6, 24],
          fine: /赌/.test(question) ? [5000, 20000] : undefined,
        },
        basis: ['《刑法》第三百零三条', '《治安管理处罚法》第七十条', '（2023）京0105行初456号'],
        note: '预测基于案情文本要素，准确率受描述完整度影响；刑期区间为统计回归结果。',
      },
    }
  } else if (agentId === 'a_1003') {
    // 类案检索：文本 + 案例列表卡片
    text = CASE_TEXT
    citesLaw = true
    card = {
      card_type: 'case_list',
      payload: [
        {
          case_no: '（2023）京0105行初456号',
          court: '北京市朝阳区人民法院',
          summary: '利用微信群组织"抢红包"式赌博，累计抽头渔利 1.2 万元',
          result: '开设赌场罪 · 有期徒刑八个月缓刑一年',
          score: 0.91,
        },
        {
          case_no: '（2022）沪0104刑初789号',
          court: '上海市徐汇区人民法院',
          summary: '在棋牌室设置麻将机供他人赌博并按局抽头',
          result: '开设赌场罪 · 有期徒刑六个月',
          score: 0.87,
        },
        {
          case_no: '（2023）粤0304行初123号',
          court: '深圳市福田区人民法院',
          summary: '参与网络赌博投注 3 万余元，赌资较大',
          result: '行政拘留十日，罚款 1500 元',
          score: 0.82,
        },
      ],
    }
  } else if (agentId === 'a_1005') {
    // 合同审查：文本 + 风险清单卡片
    text = CONTRACT_TEXT
    citesLaw = true
    card = {
      card_type: 'risk_list',
      payload: [
        {
          clause: '违约金上限缺失',
          position: '第 7 条 违约责任',
          level: 'high',
          suggestion: '约定违约金不超过合同总额的 30%，并明确计算方式',
        },
        {
          clause: '争议解决条款不利',
          position: '第 12 条 争议解决',
          level: 'medium',
          suggestion: '将管辖法院改为"被告所在地或合同签订地人民法院"，或约定仲裁',
        },
        {
          clause: '知识产权归属不明',
          position: '第 9 条 成果交付',
          level: 'high',
          suggestion: '明确约定交付成果的知识产权归委托方所有，并约定源文件交付',
        },
      ],
    }
  } else if (agentId === 'a_1006') {
    // 文书起草：文本 + 文书卡片（可复制/下载）
    text = DOC_TEXT
    card = {
      card_type: 'document',
      payload: { title: '民事起诉状（初稿）', doc_type: '起诉状', content: COMPLAINT_DOC },
    }
  } else if (/赌|麻将|棋牌|抢红包/.test(question)) {
    text = GAMBLING_ANSWER
    citesLaw = true
  } else if (/打|伤害|轻伤|重伤|打架/.test(question)) {
    text = INJURY_ANSWER
    citesLaw = true
  } else {
    text = GENERIC_ANSWER(question)
  }

  // 附件解析提示（多模态占位）
  if (req.attachments?.length) {
    text =
      `已接收并解析 ${req.attachments.length} 个附件：${req.attachments.map((a) => a.filename).join('、')}。\n\n` +
      text
  }

  // 1') 引用事件：凡正文引用法条或开启 RAG 的场景都推送
  if (citesLaw || ragOn) {
    citations = [
      {
        index: 1,
        source: '治安管理处罚法 第七十条',
        snippet:
          '以营利为目的，为赌博提供条件的，或者参与赌博赌资较大的，处五日以下拘留或者五百元以下罚款；情节严重的，处十日以上十五日以下拘留，并处五百元以上三千元以下罚款。',
        score: 0.93,
        doc_id: 'doc_3001',
      },
      {
        index: 2,
        source: '刑法 第三百零三条',
        snippet:
          '以营利为目的，聚众赌博或者以赌博为业的，处三年以下有期徒刑、拘役或者管制，并处罚金。开设赌场的，处五年以下有期徒刑……',
        score: 0.88,
        doc_id: 'doc_3002',
      },
    ]
    onEvent('citations', { items: citations })
    await delay(120)
  }

  // 3) 增量推送正文
  const buffered: string[] = []
  for (const chunk of chunkify(text)) {
    if (signal.aborted) {
      persistAssistant(req.conversation_id, buffered.join(''), { status: 'aborted' })
      return
    }
    buffered.push(chunk)
    onEvent('message', { delta: chunk })
    await delay(14 + Math.random() * 22)
  }

  // 4) 卡片事件
  if (card) {
    await delay(200)
    onEvent('card', { card_type: card.card_type, payload: card.payload })
  }

  // 5) 结束事件（含用量），并落库（卡片随消息持久化）
  const finalMsg: Partial<import('@/types/api').Message> = {
    citations,
    card,
    reasoning: reasoningText || undefined,
    usage: {
      prompt_tokens: Math.floor(question.length * 1.6) + 40,
      completion_tokens: Math.floor(text.length * 1.4),
    },
  }
  persistAssistant(req.conversation_id, text, finalMsg)
  onEvent('done', { message_id: uid('m'), usage: finalMsg.usage })
}
