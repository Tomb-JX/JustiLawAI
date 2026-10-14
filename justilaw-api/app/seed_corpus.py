"""法律语料导入：把内置法条/案例文本经真实 RAG 管线（切分→bge-m3 嵌入→入库）导入种子知识库。

用法：cd justilaw-api && python -m app.seed_corpus
也支持导入本地文件：python -m app.seed_corpus <文件路径> <dataset_id>
"""
from __future__ import annotations

import asyncio
import sys

from app.model_gateway.gateway import embed_texts
from app.rag.pipeline import VectorStore, chunk_text
from app.store import chunks_db, datasets_db, documents_db, find, now, uid

EMBED_MODEL = "ollama/bge-m3"

LAW_TEXT = """《中华人民共和国治安管理处罚法》相关条文

第十条 治安管理处罚的种类分为：（一）警告；（二）罚款；（三）行政拘留；（四）吊销公安机关发放的许可证。对违反治安管理的外国人，可以附加适用限期出境或者驱逐出境。

第十九条 违反治安管理有下列情形之一的，减轻处罚或者不予处罚：（一）情节特别轻微的；（二）主动消除或者减轻违法后果，并取得被侵害人谅解的；（三）出于他人胁迫或者诱骗的；（四）主动投案，向公安机关如实陈述自己的违法行为的；（五）有立功表现的。

第七十条 以营利为目的，为赌博提供条件的，或者参与赌博赌资较大的，处五日以下拘留或者五百元以下罚款；情节严重的，处十日以上十五日以下拘留，并处五百元以上三千元以下罚款。

第七十四条 旅馆业、饮食服务业、文化娱乐业、出租汽车业等单位的人员，在公安机关查处吸毒、赌博、卖淫、嫖娼活动时，为违法犯罪行为人通风报信的，处十日以上十五日以下拘留。

《中华人民共和国刑法》相关条文

第二百三十四条 故意伤害他人身体的，处三年以下有期徒刑、拘役或者管制。犯前款罪，致人重伤的，处三年以上十年以下有期徒刑；致人死亡或者以特别残忍手段致人重伤造成严重残疾的，处十年以上有期徒刑、无期徒刑或者死刑。

第三百零三条 以营利为目的，聚众赌博或者以赌博为业的，处三年以下有期徒刑、拘役或者管制，并处罚金。开设赌场的，处五年以下有期徒刑、拘役或者管制，并处罚金；情节严重的，处五年以上十年以下有期徒刑，并处罚金。

《关于办理赌博刑事案件具体应用法律若干问题的解释》要点

以营利为目的，有下列情形之一的，属于刑法第三百零三条规定的"聚众赌博"：（一）组织3人以上赌博，抽头渔利数额累计达到5000元以上的；（二）组织3人以上赌博，赌资数额累计达到5万元以上的；（三）组织3人以上赌博，参赌人数累计达到20人以上的。

开设赌场的认定：提供赌场、赌具，组织、招引他人进行赌博，从中渔利的行为，包括在计算机网络中建立赌博网站并接受投注、为赌博网站担任代理接受投注等情形。

网络赌博的界限：利用微信群以"抢红包"方式赌博、设定赌博规则（如抢到特定尾数者输）并从中抽头的，可认定为开设赌场或聚众赌博；亲友间不带营利性质的娱乐活动不构成违法。
"""

CASES_TEXT = """赌博类行政处罚与刑事案例汇编

案例1（行政处罚）：王某在经营棋牌室期间，为顾客提供麻将机及筹码，按每桌每小时50元收取台费，另按赢家金额5%抽头。公安机关查获时现场参赌人员12人，王某累计抽头渔利人民币3800元。依据《治安管理处罚法》第七十条，王某以营利目的为赌博提供条件且情节较重，处行政拘留十二日，并处罚款二千元。

案例2（行政处罚）：李某使用手机在微信群内组织"红包接龙"赌博，群成员40余人，设定"抢到尾数为指定数字者输"的规则，李某每局抽取赢家金额10%作为"管理费"，三个月累计渔利1.2万元。因数额较大、参赌人数多，法院认定构成开设赌场罪，判处有期徒刑八个月，缓刑一年，并处罚金一万元。

案例3（行政处罚）：赵某长期参与网络赌博平台投注，累计投注金额3万余元，个人亏损8000元。公安机关依据《治安管理处罚法》第七十条认定其参与赌博赌资较大，处行政拘留十日，并处罚款一千五百元。

案例4（刑事）：孙某租赁门面房设置赌博机8台，供他人赌博并兑换现金，经营三个月，非法获利5万余元。法院认定其构成开设赌场罪，考虑其自首、退赃情节，判处有期徒刑一年二个月，并处罚金二万元。

案例5（刑事·对比参考）：周某受雇于赌场担任发牌员，月薪4000元，不参与分红。法院认为其系受雇佣从事辅助劳务，情节显著轻微，不构成犯罪，建议行政机关予以治安处罚。

案例6（轻罪参考）：吴某酒后因琐事与邻居发生争执，挥拳击打对方面部致鼻骨骨折，经鉴定为轻伤二级。案发后吴某主动投案、赔偿并取得谅解。法院认定构成故意伤害罪，判处有期徒刑八个月，缓刑一年。

案例7（赌博与娱乐界限）：郑某与同事六人在家中打麻将，约定输赢相互转账，单局输赢数十元，无抽头渔利。公安机关未认定赌博违法行为，予以批评教育后放行。

案例8（网络开设赌场）：陈某架设境外赌博网站镜像站并发展下级代理，接受投注流水200余万元，个人获利18万元。法院认定构成开设赌场罪且情节严重，判处有期徒刑五年六个月，并处罚金二十万元。
"""


async def ingest_text(dataset_id: str, filename: str, text: str):
    ds = find(datasets_db.data, id=dataset_id)
    if not ds:
        print(f"[skip] 数据集 {dataset_id} 不存在")
        return
    doc = {"id": uid("doc"), "dataset_id": dataset_id, "filename": filename,
           "size": len(text.encode("utf-8")), "status": "parsing", "chunk_count": 0,
           "created_at": now()}
    documents_db.data.insert(0, doc)
    chunks = chunk_text(text, ds["chunk_config"]["max_length"], ds["chunk_config"]["overlap"])
    print(f"[ingest] {filename}: {len(chunks)} 个分段，嵌入中…")
    vectors = await embed_texts(EMBED_MODEL, chunks)
    entries = [{"chunk_id": uid("ch"), "doc_id": doc["id"], "index": i + 1, "content": c}
               for i, c in enumerate(chunks)]
    VectorStore(dataset_id).add(EMBED_MODEL, entries, vectors)
    chunks_db.data[doc["id"]] = [{**e, "enabled": True} for e in entries]
    doc.update(status="completed", chunk_count=len(chunks))
    ds["doc_count"] += 1
    for db in (documents_db, chunks_db, datasets_db):
        db.save()
    print(f"[done] {filename} → {len(chunks)} 段已入库（{dataset_id}）")


async def main():
    if len(sys.argv) >= 3:
        # 导入本地文件：python -m app.seed_corpus <path> <dataset_id>
        from pathlib import Path
        from app.rag.pipeline import parse_file
        text = parse_file(Path(sys.argv[1]))
        await ingest_text(sys.argv[2], Path(sys.argv[1]).name, text)
        return
    await ingest_text("d_seed_law", "常用法律条文汇编（赌博/伤害相关）.md", LAW_TEXT)
    await ingest_text("d_seed_case", "赌博类案例汇编.md", CASES_TEXT)


if __name__ == "__main__":
    asyncio.run(main())
