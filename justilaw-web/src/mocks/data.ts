import type {
  Agent,
  Chunk,
  Conversation,
  Dataset,
  Document,
  Message,
  ModelInfo,
  Prompt,
} from '@/types/api'

const now = Date.now()
const iso = (offsetMinutes: number) => new Date(now - offsetMinutes * 60_000).toISOString()

/* ============ 模型 ============ */

export const models: ModelInfo[] = [
  {
    id: 'justilaw-legal',
    name: 'JustiLaw 法律增强',
    provider: 'JustiLawAI',
    description: '在通用基座上用法律语料（CAIL2018 等）继续训练，法律问答与文书场景优先',
    default_params: { temperature: 0.3, top_p: 0.9, max_tokens: 2048 },
  },
  {
    id: 'justilaw-base',
    name: 'JustiLaw 基座',
    provider: 'JustiLawAI',
    description: '通用对话基座模型，响应速度优先',
    default_params: { temperature: 0.7, top_p: 0.9, max_tokens: 2048 },
  },
  {
    id: 'cail-predict',
    name: 'CAIL 判决预测',
    provider: 'JustiLawAI',
    description: '基于 CAIL2018 微调的分类模型，输出罪名/法条/刑期结构化预测',
    default_params: { temperature: 0.1, top_p: 0.8, max_tokens: 1024 },
  },
]

/* ============ 会话与消息 ============ */

export const conversations: Conversation[] = [
  {
    id: 'c_1001',
    title: '开设赌场罪与赌博罪的区别',
    pinned: true,
    last_message_at: iso(30),
    created_at: iso(60 * 24 * 2),
  },
  {
    id: 'c_1002',
    title: '故意伤害致人轻伤的量刑',
    pinned: false,
    last_message_at: iso(60 * 5),
    created_at: iso(60 * 26),
  },
]

export const messages: Record<string, Message[]> = {
  c_1001: [
    {
      id: 'm_2001',
      conversation_id: 'c_1001',
      role: 'user',
      content_type: 'markdown',
      content: '开设赌场罪和赌博罪有什么区别？分别怎么处罚？',
      status: 'done',
      created_at: iso(31),
    },
    {
      id: 'm_2002',
      conversation_id: 'c_1001',
      role: 'assistant',
      content_type: 'markdown',
      content: [
        '### 结论\n两者同属涉赌犯罪，但**开设赌场罪**针对经营性、组织性的"开赌场"行为，**赌博罪**针对聚众赌博、以赌博为业的行为，前者的法定刑明显更重。\n',
        '### 主要区别\n\n| 维度 | 赌博罪（聚众赌博） | 开设赌场罪 |\n| --- | --- | --- |\n| 行为核心 | 聚众赌博、以赌博为业 | 开设、经营赌场，提供赌具与场所 |\n| 组织程度 | 临时性、松散 | 持续性、有分工 |\n| 盈利方式 | 抽头渔利 | 抽头、门票、服务费等多种方式 |\n\n### 处罚\n1. **赌博罪**：处三年以下有期徒刑、拘役或者管制，并处罚金\n2. **开设赌场罪**：处五年以下有期徒刑、拘役或者管制，并处罚金；情节严重的，处五年以上十年以下有期徒刑，并处罚金\n\n> ⚠️ 以上内容由 AI 生成，仅供参考，不构成正式法律意见。',
      ].join('\n'),
      citations: [
        {
          index: 1,
          source: '刑法 第三百零三条',
          snippet:
            '以营利为目的，聚众赌博或者以赌博为业的，处三年以下有期徒刑、拘役或者管制，并处罚金。开设赌场的，处五年以下有期徒刑、拘役或者管制，并处罚金；情节严重的，处五年以上十年以下有期徒刑，并处罚金。',
          score: 0.93,
          doc_id: 'doc_3002',
        },
      ],
      status: 'done',
      usage: { prompt_tokens: 86, completion_tokens: 342 },
      created_at: iso(30),
    },
  ],
  c_1002: [
    {
      id: 'm_2003',
      conversation_id: 'c_1002',
      role: 'user',
      content_type: 'markdown',
      content: '把人打成轻伤一级，一般会怎么判？',
      status: 'done',
      created_at: iso(60 * 5 - 1),
    },
    {
      id: 'm_2004',
      conversation_id: 'c_1002',
      role: 'assistant',
      content_type: 'markdown',
      content:
        '故意伤害致人**轻伤一级**的，构成故意伤害罪，依据《刑法》第二百三十四条，处**三年以下**有期徒刑、拘役或者管制。\n\n实践中量刑会综合考量：\n\n- 是否**自首、认罪认罚**（可从宽）\n- 是否**赔偿并取得谅解**（常见从轻情节）\n- 是否**持械、有预谋**等从重情节\n\n如积极赔偿并获得被害人谅解，争取缓刑的可能性较大。需要我帮你检索类似案例吗？',
      citations: [
        {
          index: 1,
          source: '刑法 第二百三十四条',
          snippet:
            '故意伤害他人身体的，处三年以下有期徒刑、拘役或者管制。犯前款罪，致人重伤的，处三年以上十年以下有期徒刑……',
          score: 0.95,
          doc_id: 'doc_3002',
        },
      ],
      status: 'done',
      usage: { prompt_tokens: 42, completion_tokens: 186 },
      created_at: iso(60 * 5),
    },
  ],
}

/* ============ 智能体 ============ */

export const agents: Agent[] = [
  {
    id: 'a_1001',
    name: '法律咨询助手',
    category: '法律咨询',
    description: '多轮法律问答，自动检索法条与案例辅助回答，覆盖民事、刑事、行政常见问题',
    system_prompt: '你是专业的法律咨询助手，回答需引用具体法条，语言通俗，结尾给出行动建议，并声明不构成法律意见。',
    opening_statement: '你好，我是法律咨询助手。请描述你遇到的法律问题，我会结合法条和案例为你分析。',
    suggested_questions: [
      '网络赌博被行政拘留会有案底吗？',
      '民间借贷利息超过多少不受法律保护？',
      '劳动仲裁的时效是多久？',
    ],
    tool_ids: [],
    dataset_ids: ['d_1001', 'd_1002'],
    scope: 'public',
    status: 'published',
    usage_count: 1284,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 30),
  },
  {
    id: 'a_1002',
    name: '判决预测',
    category: '司法辅助',
    description: '输入案情事实，基于 CAIL 微调模型预测罪名、适用法条与量刑区间（结构化卡片输出）',
    system_prompt: '你是判决预测引擎，根据案情事实输出结构化预测结果。',
    opening_statement: '请描述案件事实（时间、地点、行为、后果等要素），我将预测可能的罪名与量刑区间。',
    suggested_questions: [
      '张三以营利为目的在棋牌室组织他人赌博，抽头渔利8000元',
      '李四酒后殴打他人致轻伤二级，事后主动投案并赔偿',
    ],
    tool_ids: [],
    dataset_ids: ['d_1002'],
    scope: 'public',
    status: 'published',
    usage_count: 862,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 28),
  },
  {
    id: 'a_1003',
    name: '类案检索',
    category: '司法辅助',
    description: '输入案情，语义检索相似已决案例，返回案例卡片（案号/法院/结果/相似度）',
    system_prompt: '你是类案检索助手，根据案情检索相似案例并结构化输出。',
    opening_statement: '请描述案情，我将为你检索相似案例。',
    suggested_questions: ['利用微信群组织赌博抽头', '帮朋友代购彩票从中获利'],
    tool_ids: [],
    dataset_ids: ['d_1002'],
    scope: 'public',
    status: 'published',
    usage_count: 654,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 25),
  },
  {
    id: 'a_1004',
    name: '法条解释',
    category: '法律咨询',
    description: '定位条文、通俗解释、关联条文与典型案例',
    system_prompt: '你是法条解释助手，输出条文原文、白话解释、关联条文与典型案例。',
    opening_statement: '请输入法条名称或关键词，如"治安管理处罚法 第七十条"。',
    suggested_questions: ['治安管理处罚法 第七十条', '刑法 第三百零三条'],
    tool_ids: [],
    dataset_ids: ['d_1001'],
    scope: 'public',
    status: 'published',
    usage_count: 421,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 20),
  },
  {
    id: 'a_1005',
    name: '合同审查',
    category: '合同文书',
    description: '上传或粘贴合同文本，识别风险条款并输出风险清单卡片（位置/等级/修改建议）',
    system_prompt: '你是合同审查助手，逐条识别法律风险并输出结构化风险清单。',
    opening_statement: '请粘贴合同文本或描述合同类型与关键条款，我将输出风险清单。',
    suggested_questions: ['审查一份房屋租赁合同的关键风险点'],
    tool_ids: [],
    dataset_ids: [],
    scope: 'public',
    status: 'published',
    usage_count: 312,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 15),
  },
  {
    id: 'a_1006',
    name: '文书起草',
    category: '合同文书',
    description: '分步收集当事人、案由、诉求等要素，生成起诉状/答辩状/处罚决定书初稿',
    system_prompt: '你是法律文书起草助手，先收集必要要素，再生成规范文书。',
    opening_statement: '请告诉我文书类型（起诉状/答辩状/法律意见书等）与基本案情，我会引导你补全要素后生成初稿。',
    suggested_questions: ['帮我起草一份民间借贷纠纷的起诉状'],
    tool_ids: [],
    dataset_ids: [],
    scope: 'private',
    status: 'draft',
    usage_count: 96,
    created_by: 'u_admin',
    created_at: iso(60 * 24 * 3),
  },
]

/* ============ 知识库 ============ */

export const datasets: Dataset[] = [
  {
    id: 'd_1001',
    name: '法律法规库',
    description: '刑法、治安管理处罚法等常用法律法规全文',
    chunk_config: { max_length: 500, overlap: 50 },
    retrieval_config: { top_k: 5, score_threshold: 0.6 },
    doc_count: 3,
    created_at: iso(60 * 24 * 40),
  },
  {
    id: 'd_1002',
    name: '赌博类案例库',
    description: '赌博/开设赌场相关的刑事判决与行政处罚案例（CAIL2018 子集 + 裁判文书精选）',
    chunk_config: { max_length: 800, overlap: 80 },
    retrieval_config: { top_k: 5, score_threshold: 0.55 },
    doc_count: 2,
    created_at: iso(60 * 24 * 35),
  },
]

export const documents: Document[] = [
  {
    id: 'doc_3001',
    dataset_id: 'd_1001',
    filename: '中华人民共和国治安管理处罚法.pdf',
    size: 1_240_000,
    status: 'completed',
    chunk_count: 412,
    created_at: iso(60 * 24 * 40),
  },
  {
    id: 'doc_3002',
    dataset_id: 'd_1001',
    filename: '中华人民共和国刑法.pdf',
    size: 4_860_000,
    status: 'completed',
    chunk_count: 1866,
    created_at: iso(60 * 24 * 39),
  },
  {
    id: 'doc_3003',
    dataset_id: 'd_1001',
    filename: '公安机关办理行政案件程序规定.pdf',
    size: 980_000,
    status: 'completed',
    chunk_count: 305,
    created_at: iso(60 * 24 * 38),
  },
  {
    id: 'doc_3004',
    dataset_id: 'd_1002',
    filename: 'CAIL2018 赌博类案例精选.json',
    size: 15_600_000,
    status: 'completed',
    chunk_count: 2048,
    created_at: iso(60 * 24 * 35),
  },
  {
    id: 'doc_3005',
    dataset_id: 'd_1002',
    filename: '行政处罚决定书汇编（2023）.docx',
    size: 3_200_000,
    status: 'parsing',
    chunk_count: 0,
    created_at: iso(2),
  },
]

export const chunks: Chunk[] = [
  {
    id: 'ch_4001',
    document_id: 'doc_3001',
    index: 128,
    enabled: true,
    content:
      '第七十条 以营利为目的，为赌博提供条件的，或者参与赌博赌资较大的，处五日以下拘留或者五百元以下罚款；情节严重的，处十日以上十五日以下拘留，并处五百元以上三千元以下罚款。',
  },
  {
    id: 'ch_4002',
    document_id: 'doc_3001',
    index: 129,
    enabled: true,
    content:
      '第七十一条 明知他人从事前条违法行为，为其提供赌博工具、场所或者其他便利条件的，依照前条的规定处罚。',
  },
  {
    id: 'ch_4003',
    document_id: 'doc_3002',
    index: 980,
    enabled: true,
    content:
      '第三百零三条 以营利为目的，聚众赌博或者以赌博为业的，处三年以下有期徒刑、拘役或者管制，并处罚金。开设赌场的，处五年以下有期徒刑、拘役或者管制，并处罚金；情节严重的，处五年以上十年以下有期徒刑，并处罚金。',
  },
  {
    id: 'ch_4004',
    document_id: 'doc_3004',
    index: 56,
    enabled: true,
    content:
      '（2023）京0105行初456号：王某利用微信群组织他人进行"抢红包"式赌博，累计抽头渔利人民币1.2万元。法院认定其行为构成开设赌场罪，判处有期徒刑八个月，缓刑一年，并处罚金人民币一万元。',
  },
]

/* ============ 提示词 ============ */

export const prompts: Prompt[] = [
  {
    id: 'p_5001',
    name: '案情分析',
    content: '请从法律角度分析以下案情，给出定性、争议焦点和处理建议：\n{{案情}}',
    category: '分析',
    starred: true,
  },
  {
    id: 'p_5002',
    name: '生成起诉状',
    content:
      '请根据以下信息生成一份民事起诉状：\n原告：{{原告}}\n被告：{{被告}}\n诉讼请求：{{诉求}}\n事实与理由：{{事实}}',
    category: '文书',
    starred: true,
  },
  {
    id: 'p_5003',
    name: '检索类案',
    content: '请检索与以下案情相似的已决案例，并总结裁判要旨：\n{{案情}}',
    category: '检索',
    starred: false,
  },
  {
    id: 'p_5004',
    name: '解释法条',
    content: '请用通俗语言解释以下法条，包括适用条件、法律后果和一个典型例子：\n{{法条}}',
    category: '解释',
    starred: false,
  },
  {
    id: 'p_5005',
    name: '合同风险审查',
    content: '请审查以下合同条款的法律风险，按高/中/低分级并给出修改建议：\n{{合同文本}}',
    category: '合同',
    starred: false,
  },
]
