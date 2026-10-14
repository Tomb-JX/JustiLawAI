"""首次启动种子数据：内置法律智能体 / 提示词 / 示例知识库。

仅当对应集合为空时写入（幂等）。语料种子（法条全文/案例）由 seed_corpus.py 单独导入。
"""
from .store import agents_db, prompts_db, datasets_db, now


def seed():
    if not datasets_db.data:
        datasets_db.data = [
            {"id": "d_seed_law", "name": "法律法规库", "description": "刑法、治安管理处罚法等常用法律法规（运行 seed_corpus.py 导入全文）",
             "chunk_config": {"max_length": 500, "overlap": 50},
             "retrieval_config": {"top_k": 5, "score_threshold": 0.35},
             "doc_count": 0, "created_at": now()},
            {"id": "d_seed_case", "name": "赌博类案例库", "description": "赌博/开设赌场相关案例（可从 CAIL2018 提取子集导入）",
             "chunk_config": {"max_length": 800, "overlap": 80},
             "retrieval_config": {"top_k": 5, "score_threshold": 0.35},
             "doc_count": 0, "created_at": now()},
        ]
        datasets_db.save()

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
