"""首次启动种子数据：内置法律智能体 / 提示词 / 示例知识库。

仅当对应集合为空时写入（幂等）。语料种子（法条全文/案例）由 seed_corpus.py 单独导入。
"""
from .store import agents_db, datasets_db, now, prompts_db, workflows_db


def _node(nid: str, node_type: str, name: str, x: int, config: dict, y: int = 200) -> dict:
    return {"id": nid, "type": "workflow", "position": {"x": x, "y": y},
            "data": {"nodeType": node_type, "name": name, "config": config}}


def _edges(*pairs: tuple[str, str]) -> list[dict]:
    return [{"id": f"e{i + 1}", "source": s, "target": t} for i, (s, t) in enumerate(pairs)]


# 工作流模板 ID 与前端「新建工作流」中的模板一一对应；llm 节点不写死模型，运行时用默认对话模型
WORKFLOW_TEMPLATES = [
    {"id": "w_1001", "name": "案情分析流水线",
     "description": "要素抽取 → 法条检索 → 类案检索 → 综合分析，输出结构化分析结论",
     "dsl": {"nodes": [
         _node("nd_1", "start", "开始", 0, {"vars": [{"name": "case_facts", "label": "案情事实"}]}),
         _node("nd_2", "llm", "要素抽取", 220, {"prompt": "从以下案情中抽取时间、地点、人物、行为、后果等要素，分条列出：\n{{case_facts}}", "temperature": 0.2}),
         _node("nd_3", "retrieval", "法条检索", 440, {"dataset": "d_seed_law", "dataset_name": "法律法规库", "top_k": 5}, y=120),
         _node("nd_4", "retrieval", "类案检索", 440, {"dataset": "d_seed_case", "dataset_name": "赌博类案例库", "top_k": 3}, y=280),
         _node("nd_5", "llm", "综合分析", 660, {"prompt": "案情要素：\n{{要素抽取}}\n\n相关法条：\n{{法条检索}}\n\n相关案例：\n{{类案检索}}\n\n请输出：定性、法律依据（注明条文）、处理建议。资料不足时如实说明。", "temperature": 0.4}),
         _node("nd_6", "reply", "直接回复", 880, {}),
     ], "edges": _edges(("nd_1", "nd_2"), ("nd_2", "nd_3"), ("nd_2", "nd_4"), ("nd_3", "nd_5"), ("nd_4", "nd_5"), ("nd_5", "nd_6"))}},
    {"id": "w_1002", "name": "判决预测（CAIL）",
     "description": "要素抽取后调用外部预测模型 API（需在 HTTP 节点填写地址），法条核对后汇总输出",
     "dsl": {"nodes": [
         _node("nd_1", "start", "开始", 0, {"vars": [{"name": "facts", "label": "案情事实"}]}),
         _node("nd_2", "llm", "要素抽取", 220, {"prompt": "抽取以下案件的关键要素（行为、数额、人数、情节）：\n{{facts}}", "temperature": 0.2}),
         _node("nd_3", "http", "预测模型 API", 440, {"method": "POST", "url": ""}),
         _node("nd_4", "retrieval", "法条核对", 660, {"dataset": "d_seed_law", "dataset_name": "法律法规库", "top_k": 5}),
         _node("nd_5", "llm", "结论汇总", 880, {"prompt": "预测结果：\n{{预测模型 API}}\n\n法条：\n{{法条核对}}\n\n请汇总预测结论，并指出与法条不一致之处。", "temperature": 0.3}),
         _node("nd_6", "reply", "直接回复", 1100, {}),
     ], "edges": _edges(("nd_1", "nd_2"), ("nd_2", "nd_3"), ("nd_3", "nd_4"), ("nd_4", "nd_5"), ("nd_5", "nd_6"))}},
    {"id": "w_1003", "name": "合同风险扫描",
     "description": "合同文本 → 逐条审查 → 风险聚合 → 报告输出",
     "dsl": {"nodes": [
         _node("nd_1", "start", "开始", 0, {"vars": [{"name": "contract_text", "label": "合同文本"}]}),
         _node("nd_2", "llm", "逐条审查", 220, {"prompt": "逐条识别以下合同中的风险条款，给出位置、风险等级（高/中/低）与修改建议：\n{{contract_text}}", "temperature": 0.2}),
         _node("nd_3", "aggregate", "风险聚合", 440, {}),
         _node("nd_4", "template", "报告模板", 660, {"template": "## 风险清单\n\n{{aggregate}}"}),
         _node("nd_5", "reply", "直接回复", 880, {}),
     ], "edges": _edges(("nd_1", "nd_2"), ("nd_2", "nd_3"), ("nd_3", "nd_4"), ("nd_4", "nd_5"))}},
]


def seed():
    if not datasets_db.data:
        datasets_db.data = [
            {"id": "d_seed_law", "name": "法律法规库", "description": "刑法、治安管理处罚法等常用法律法规（上传经核对的现行条文）",
             "chunk_config": {"max_length": 500, "overlap": 50},
             "retrieval_config": {"top_k": 5, "score_threshold": 0.35},
             "doc_count": 0, "created_by": "u_system", "created_at": now()},
            {"id": "d_seed_case", "name": "赌博类案例库", "description": "赌博类行政处罚 / 刑事案例（上传可溯源的真实决定书、裁判文书）",
             "chunk_config": {"max_length": 800, "overlap": 80},
             "retrieval_config": {"top_k": 5, "score_threshold": 0.35},
             "doc_count": 0, "created_by": "u_system", "created_at": now()},
        ]
        datasets_db.save()

    existing = {w["id"] for w in workflows_db.data}
    missing = [t for t in WORKFLOW_TEMPLATES if t["id"] not in existing]
    if missing:
        workflows_db.data.extend({**t, "status": "published", "is_template": True,
                                  "created_by": "u_system", "created_at": now()} for t in missing)
        workflows_db.save()

    if not agents_db.data:
        agents_db.data = [
            {"id": "a_seed_consult", "name": "法律咨询助手", "category": "法律咨询",
             "description": "多轮法律问答，自动检索法条与案例辅助回答",
             "system_prompt": "你是专业的法律咨询助手。回答需引用具体法条（如《治安管理处罚法》第七十条），结构化输出，语言通俗，结尾给出行动建议并声明不构成法律意见。",
             "opening_statement": "你好，我是法律咨询助手。请描述你遇到的法律问题。",
             "suggested_questions": ["网络赌博被行政拘留会有案底吗？", "参与赌博赌资较大怎么处罚？", "开设赌场和赌博罪有什么区别？"],
             "tool_ids": [], "dataset_ids": ["d_seed_law", "d_seed_case"], "scope": "public",
             "status": "published", "usage_count": 0, "created_by": "u_system", "created_at": now()},
            {"id": "a_seed_predict", "name": "判决预测", "category": "司法辅助",
             "description": "输入案情事实，基于法律知识预测罪名、法条与量刑区间",
             "system_prompt": "你是判决预测助手。根据案情事实输出：1) 最可能的罪名及理由；2) 适用法条；3) 量刑/处罚区间估计；4) 影响量刑的情节。明确声明结果仅供研究参考。",
             "opening_statement": "请描述案件事实（时间、地点、行为、后果等要素），我将预测可能的罪名与量刑区间。",
             "suggested_questions": ["张三以营利为目的在棋牌室组织他人赌博，抽头渔利8000元", "李四酒后殴打他人致轻伤二级，事后自首并赔偿"],
             "tool_ids": [], "dataset_ids": ["d_seed_case"], "scope": "public",
             "status": "published", "usage_count": 0, "created_by": "u_system", "created_at": now()},
            {"id": "a_seed_case", "name": "类案检索", "category": "司法辅助",
             "description": "基于案例知识库检索相似案例并总结裁判要旨",
             "system_prompt": "你是类案检索助手。根据案情从检索到的案例中找出相似案例，输出：案号/来源、案情要点、处理结果、与当前案情的相似点。",
             "opening_statement": "请描述案情，我将检索相似案例。",
             "suggested_questions": ["利用微信群组织赌博抽头", "帮朋友看管赌场算不算开设赌场"],
             "tool_ids": [], "dataset_ids": ["d_seed_case"], "scope": "public",
             "status": "published", "usage_count": 0, "created_by": "u_system", "created_at": now()},
            {"id": "a_seed_law", "name": "法条解释", "category": "法律咨询",
             "description": "定位条文、通俗解释、关联条文与典型案例",
             "system_prompt": "你是法条解释助手。输出：条文原文、白话解释、适用条件、一个典型例子。",
             "opening_statement": "请输入法条名称或关键词，如\"治安管理处罚法 第七十条\"。",
             "suggested_questions": ["治安管理处罚法 第七十条", "刑法 第三百零三条"],
             "tool_ids": [], "dataset_ids": ["d_seed_law"], "scope": "public",
             "status": "published", "usage_count": 0, "created_by": "u_system", "created_at": now()},
        ]
        agents_db.save()

    if not prompts_db.data:
        prompts_db.data = [
            {"id": "p_seed_1", "name": "案情分析", "content": "请从法律角度分析以下案情，给出定性、争议焦点和处理建议：\n{{案情}}", "category": "分析", "starred": True},
            {"id": "p_seed_2", "name": "生成起诉状", "content": "请根据以下信息生成一份民事起诉状：\n原告：{{原告}}\n被告：{{被告}}\n诉讼请求：{{诉求}}\n事实与理由：{{事实}}", "category": "文书", "starred": True},
            {"id": "p_seed_3", "name": "检索类案", "content": "请检索与以下案情相似的已决案例，并总结裁判要旨：\n{{案情}}", "category": "检索", "starred": False},
            {"id": "p_seed_4", "name": "解释法条", "content": "请用通俗语言解释以下法条，包括适用条件、法律后果和一个典型例子：\n{{法条}}", "category": "解释", "starred": False},
        ]
        prompts_db.save()
