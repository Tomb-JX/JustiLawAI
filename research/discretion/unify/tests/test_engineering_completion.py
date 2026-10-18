"""Behavioral regressions for EP-01–12; synthetic data, no model HTTP calls."""
import copy
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence_types import SourceSpan, CleanSpan
from normalization import normalize_time, normalize_quantity, project_time, project_quantity, derive_age, project_duration_days
from evidence_graph import build_graph, resolve_binding
from field_rules import field_catalog, resolve_enum
from section_refs import fine_references
from observability import diagnose, summarize
from experiment_plan import select_events, evaluate_reference
from outcome_arbitration import validate_choice, normative_diagnostic
from provider_contract import capability, freeze_execution
from budget_scope import BudgetScope
from durable_calls import DurableCalls, append
from audit_run import audit
from locate import OffsetIndex
from run_elements import ENGINE
from test_element_pipeline import absent, FakeProvider, MSG, call_runner
from binding_contract import ground_fields
from run_outcomes import prepare, compile_result
from task_result import failure_record
from diagnose_pipeline import diagnose_batch
from contract_bundle import make_bundle
from outcome_arbitration import attach_commit, VERSION as OUTCOME_VERSION
from element_contract import digest, implementation_snapshot
from cleanse import sentence_table


def ref(raw):
    return SourceSpan.from_text(raw, 0, len(raw))


@pytest.mark.parametrize('raw,start,end,precision', [
    ('二〇二六年十月十八日','2026-10-18','2026-10-18','day'),
    ('二零二六年十月十八日','2026-10-18','2026-10-18','day'),
    ('2026年10月','2026-10-01','2026-10-31','month'),
    ('2026年','2026-01-01','2026-12-31','year'),
    ('2023年5月至7月','2023-05-01','2023-07-31','range'),
])
def test_chinese_time_keeps_precision(raw,start,end,precision):
    v=normalize_time(raw,ref(raw))
    assert v['resolution']=='resolved'
    assert (v['start_date'],v['end_date'],v['precision'])==(start,end,precision)


@pytest.mark.parametrize('raw',['次日','同年六月','去年六月','30日'])
def test_relative_time_never_uses_machine_today(raw):
    assert normalize_time(raw,ref(raw))['reason']=='missing_evidence_anchor'


def test_anchor_precision_and_thread_isolation():
    source='2023年5月18日。2025年6月20日。次日。同年六月。2023年5月。'
    def in_source(raw):
        a=source.index(raw); return SourceSpan.from_text(source,a,a+len(raw))
    def run(raw):
        anchor=normalize_time(raw,in_source(raw))
        return normalize_time('次日',in_source('次日'),anchor=anchor)['start_date']
    with ThreadPoolExecutor(max_workers=2) as ex:
        assert list(ex.map(run,['2023年5月18日','2025年6月20日']*3))==['2023-05-19','2025-06-21']*3
    month=normalize_time('2023年5月',in_source('2023年5月'))
    assert normalize_time('次日',in_source('次日'),anchor=month)['reason']=='anchor_precision_insufficient'
    assert normalize_time('同年六月',in_source('同年六月'),anchor=month)['start_date']=='2023-06-01'
    assert normalize_time('次日',ref('次日'),anchor=month)['reason']=='missing_evidence_anchor'


def test_invalid_time_duration_and_explicit_compatibility():
    raw='2026年2月30日'
    assert normalize_time(raw,ref(raw))['resolution']=='unresolved'
    raw='三个月'; v=normalize_time(raw,ref(raw))
    assert v['kind']=='duration' and v['duration']['month']==3
    assert project_time(v)['value'] is None
    raw='2026年10月'; v=normalize_time(raw,ref(raw))
    assert project_time(v)['value'] is None
    assert project_time(v,policy='schema-1.1.0-month-first')['losses']==['month_to_first_day']


@pytest.mark.parametrize('raw,lo,hi,kind,li,ui', [
    ('贰佰肆拾元','240','240','exact',True,True),
    ('3到5万元','30000','50000','interval',True,True),
    ('0.01元','0.01','0.01','exact',True,True),
    ('万元以上','10000',None,'lower_bound',True,True),
    ('超过1000元','1000',None,'lower_bound',False,True),
    ('不足1000元','0','1000','upper_bound',True,False),
    ('不超过1000元','0','1000','upper_bound',True,True),
])
def test_money_preserves_units_and_comparators(raw,lo,hi,kind,li,ui):
    v=normalize_quantity(raw,ref(raw))
    assert v['resolution']=='resolved' and v['kind']==kind
    assert Decimal(v['lower'])==Decimal(lo)
    assert (Decimal(v['upper']) if v['upper'] is not None else None)==(Decimal(hi) if hi else None)
    assert (v['lower_inclusive'],v['upper_inclusive'])==(li,ui)


@pytest.mark.parametrize('raw',['约5万元','三千余元'])
def test_approximate_money_not_silently_promoted_to_closed_interval(raw):
    v=normalize_quantity(raw,ref(raw))
    assert v['kind']=='approximate' and project_quantity(v)['value'] is None


@pytest.mark.parametrize('raw',['至少3次','3至5人','20余人'])
def test_count_bounds_are_not_exact_counts(raw):
    v=normalize_quantity(raw,ref(raw),unit='count')
    assert v['resolution']=='resolved' and project_quantity(v)['value'] is None


def test_open_endpoint_projection_requires_explicit_policy():
    raw='超过1000元'; v=normalize_quantity(raw,ref(raw))
    assert project_quantity(v)['reason']=='open_endpoint'
    assert project_quantity(v,policy='schema-1.1.0-close-endpoints')['losses']==['open_endpoint_closed']


def test_typed_projection_is_not_double_projectable_and_preserves_unicode():
    text='😀删甲赌资100元。\U00020000'
    idx=OffsetIndex({'orig_len':len(text),'deletes':[[1,1,'noise']]})
    spans=idx.project_span(CleanSpan(0,len(text)-1),text)
    assert ''.join(s.quote for s in spans)==text.replace('删','')
    with pytest.raises(TypeError): idx.project_span(spans[0],text)
    with pytest.raises(ValueError): spans[0].verify('wrong')


def graph_for(text):
    views=[{'id':'S1.1','type':'facts','start':0,'end':len(text),'text':text}]
    return build_graph(text,views,'甲'),views


def test_same_number_different_person_or_value_role_does_not_share_edges():
    text='甲携带赌资500元。乙携带赌资500元。甲决定罚款500元。'
    graph,_=graph_for(text)
    money=[n for n in graph['nodes'] if n['kind']=='money']
    assert len(money)==3
    own=money[0]
    assert resolve_binding(graph,own['id'],target='甲',event_id=own['event_id'],value_role='personal_stake',evidence_spans=[(0,len(text))])==own
    for node in money[1:]:
        with pytest.raises(ValueError):
            resolve_binding(graph,node['id'],target='甲',event_id=own['event_id'],value_role='personal_stake',evidence_spans=[(0,len(text))])


def test_joint_subject_stays_unresolved():
    graph,_=graph_for('甲与乙共同参赌，赌资合计500元。')
    assert all(n['binding']=='unresolved' for n in graph['nodes'])


def test_section_references_allow_basis_and_outcome_overlap_without_rewriting_zones():
    text='根据某法第七十条，决定给予甲罚款500元。可在六十日内申请复议。'
    views=[{'id':'S1','type':'decision','text':text,'start':0,'end':len(text)}]
    before=copy.deepcopy(views)
    refs=fine_references(text,views)['references']
    assert {'legal_basis','operative_outcome'}<=set(refs[0]['kinds'])
    assert 'remedy_notice' in refs[1]['kinds'] and views==before


def test_registry_keeps_K_and_uses_exact_reviewed_aliases_only():
    catalog=field_catalog(ENGINE)
    assert len(catalog['fields'])==36 and len(catalog['key_fields'])==10
    assert resolve_enum('conduct.method','麻将',catalog)['value']=='麻将'
    assert resolve_enum('conduct.method','麻将室',catalog)['status']=='unresolved'
    with pytest.raises(ValueError):
        resolve_enum('conduct.method','麻雀',catalog,alias_pack={'aliases':{}})
    pack={'version':'synthetic-1','approved_by':'synthetic-review','catalog_hash':catalog['hash'],
          'aliases':{'conduct.method':{'麻雀':'麻将'}}}
    assert resolve_enum('conduct.method','麻雀',catalog,alias_pack=pack)['value']=='麻将'


def test_observability_never_counts_transport_failure_as_unmentioned_or_source_absent():
    catalog=field_catalog(ENGINE)
    row={'input':{'facts_text':'甲参与赌博。'},'source_text':'甲参与赌博。','elements':absent()}
    fields=diagnose(row,{},catalog,execution='transport_failed')
    report=summarize([{'source':'synthetic','form':'narrative','fields':fields}],catalog)
    assert all(f['reason']=='transport_failed' for f in fields)
    assert all(f['unmentioned_rate_in_valid'] is None for f in report['dimensions'][0]['fields'].values())
    assert report['field_accuracy'] is None
    with pytest.raises(ValueError):
        diagnose(row,{},catalog,execution='valid',review={'person.age':{'reason':'source_absent'}})


def test_event_plan_excludes_test_and_previous_events_and_does_not_use_outcomes():
    rows=[{'id':str(i),'event_id':str(i//2),'development_split':'test' if i==9 else 'train',
           'source_batch':str(i%2),'form':'narrative','observed_outcome':{'fine':i}} for i in range(8)]
    a=select_events(rows,n=3,exclude_events=['0'])
    assert len(set(a['event_ids']))==3 and '0' not in a['event_ids']
    for row in rows: row['observed_outcome']={'fine':999999}
    assert select_events(rows,n=3,exclude_events=['0'])==a


def test_accuracy_requires_independent_reference_and_counts_failed_predictions():
    with pytest.raises(ValueError,match='independent_reference'):
        evaluate_reference([], [{'id':'T1','elements':absent(),'human_review':False}],ENGINE)
    text='甲参与赌博。'
    truth={'id':'T1','elements':absent(),'human_review':True,'independent_reviewer':'synthetic-reviewer',
           'review_record':'synthetic-test','source_text':text,'text_orig_sha256':hashlib.sha256(text.encode()).hexdigest()}
    report=evaluate_reference([], [truth],ENGINE)
    assert all(m['accuracy']==0 and m['prediction_valid_N']==0 for m in report['fields'].values())


def test_provider_modes_and_prices_frozen_without_credentials(tmp_path):
    p=FakeProvider(); p.timeout=30
    assert capability(p)['native_schema_verified'] is False
    with pytest.raises(ValueError): capability(p,{'endpoint':p.base_url,'model':p.model,'mode':'native_schema','review_record':'x'})
    order={'provider':'A','cap':1}
    freeze_execution(tmp_path,order,{'A':p},{'fake':{'input':1,'output':1}})
    with pytest.raises(ValueError,match='execution_settings_changed'):
        freeze_execution(tmp_path,order,{'A':p},{'fake':{'input':2,'output':1}})
    assert '_key' not in (tmp_path/'execution-manifest.json').read_text('utf-8')


def test_shared_budget_does_not_reset_when_next_stage_starts(tmp_path):
    scope=BudgetScope(tmp_path/'scope',cap=.0011,max_calls=4)
    p=FakeProvider(error='TimeoutError')
    with pytest.raises(RuntimeError):
        call_runner(tmp_path/'first',p,budget_scope=scope).call('A',MSG,context={},validator=lambda x:None)
    p.error=None
    with pytest.raises(RuntimeError,match='shared_budget_stop'):
        call_runner(tmp_path/'second',p,budget_scope=BudgetScope(tmp_path/'scope',cap=.0011,max_calls=4)).call('A',MSG,context={'stage':2},validator=lambda x:None)
    assert p.calls==1 and len(scope.snapshot()['unknown_keys'])==1


def test_shared_budget_serializes_concurrent_reservations(tmp_path):
    scope=BudgetScope(tmp_path,cap=1,max_calls=10)
    def reserve(i):
        try: scope.reserve(str(i),.6,owner='synthetic'); return True
        except RuntimeError: return False
    with ThreadPoolExecutor(max_workers=2) as ex:
        assert sum(ex.map(reserve,range(2)))==1


def test_recovery_audit_handles_raw_before_commit_and_rejects_torn_tail(tmp_path):
    append(tmp_path/'attempts.jsonl',{'event':'submitted','attempt_id':'x','reservation':.2,'provider':'fake'})
    append(tmp_path/'raws.jsonl',{'attempt_id':'x','content':'{}'})
    report=audit(tmp_path)
    assert report['raw_recoverable_without_new_call']==['x'] and report['estimated_charged_or_reserved']==.2
    with (tmp_path/'raws.jsonl').open('a') as f: f.write('{')
    with pytest.raises(json.JSONDecodeError): audit(tmp_path)


def test_outcome_adjudication_preserves_observed_out_of_cap_value_and_own_evidence():
    text='决定给予甲罚款5000元。'
    views=[{'id':'S1','text':text,'start':0,'end':len(text)}]
    choice={'adopt':'A','value':5000,'evidence_ids':['S1'],'reason':'原文记载'}
    result=validate_choice(choice,'fine',5000,500,text,views,target='甲')
    assert result['value']==5000 and result['execution']=='valid'
    assert normative_diagnostic('fine',5000,edition='2012修正')['observed_value']==5000
    choice['value']=500
    with pytest.raises(ValueError,match='adopted_value_mismatch'):
        validate_choice(choice,'fine',5000,500,text,views,target='甲')
    choice.update(adopt='new',value=500)
    with pytest.raises(ValueError,match='own_evidence'):
        validate_choice(choice,'fine',5000,500,text,views,target='甲')
    choice.update(adopt='A',value=5000)
    with pytest.raises(ValueError,match='target'):
        validate_choice(choice,'fine',5000,500,text,views,target='乙')


def test_age_bounds_do_not_turn_identity_age_or_month_into_exact_behavior_age():
    birth=normalize_time('2000年',ref('2000年'))
    behavior=normalize_time('2023年5月18日',ref('2023年5月18日'))
    age=derive_age(birth,behavior)
    assert (age['min'],age['max'],age['exact'])==(22,23,False)
    duration=normalize_time('三个月',ref('三个月'))
    assert project_duration_days(duration)['value'] is None
    assert project_duration_days(duration,policy='schema-1.1.0-30day-month')['losses']==['calendar_month_to_30_days']


def test_candidate_binding_compiler_checks_subject_event_role_and_value():
    text='甲携带赌资500元。乙携带赌资500元。'
    graph,_=graph_for(text)
    node=graph['nodes'][0]
    payload=absent()
    payload['amounts']['personal_stake']={'status':'明确','value':{'min':500,'max':500},
         'evidence':[{'quote':text,'start':0,'end':len(text)}]}
    choices={'amounts.personal_stake':{'candidate_id':node['id'],'event_id':node['event_id']}}
    assert ground_fields(payload,choices,graph,target='甲')['bindings']['amounts.personal_stake']['source_ref']==node['source_ref']
    with pytest.raises(ValueError,match='binding_not_selected'):
        ground_fields(payload,{},graph,target='甲')
    payload['amounts']['personal_stake']['value']={'min':100,'max':100}
    with pytest.raises(ValueError,match='value_mismatch'):
        ground_fields(payload,choices,graph,target='甲')


def test_comma_grouped_amount_not_split_into_wrong_zero():
    graph,_=graph_for('甲携带赌资3,000元。')
    assert graph['nodes'][0]['source_ref']['quote']=='3,000元'
    assert Decimal(graph['nodes'][0]['normalized']['lower'])==3000


def test_mixed_development_splits_for_same_event_rejected():
    with pytest.raises(ValueError,match='event_crosses'):
        select_events([{'id':'1','event_id':'E','development_split':'train'},
                       {'id':'2','event_id':'E','development_split':'test'}],n=1)


def test_invalid_provider_usage_remains_reserved_and_raw_is_recoverable(tmp_path):
    class BadUsage(FakeProvider):
        def chat(self,*args):
            return '{}',{'usage':{'prompt_tokens':-1,'completion_tokens':0}}
    with pytest.raises(ValueError,match='invalid_provider_usage'):
        call_runner(tmp_path,BadUsage()).call('A',MSG,context={},validator=lambda p:None)
    report=audit(tmp_path)
    assert len(report['unknown_attempts'])==1 and len(report['raw_recoverable_without_new_call'])==1


def test_failure_execution_states_do_not_manufacture_unmentioned():
    assert failure_record('T1',ValueError('bad_schema'))['status']=='invalid'
    assert failure_record('T1',RuntimeError('TimeoutError'))['status']=='transport_failed'
    assert 'elements' not in failure_record('T1',RuntimeError('budget_stop'))


def test_outcome_requests_group_fields_and_keep_full_tail(tmp_path):
    import csv
    text='甲参与赌博。'+'无关背景。'*900+'决定给予甲罚款5000元。'
    batch=tmp_path/'records.jsonl'
    append(batch,{'id':'T1','subject_mention':'甲','text_full':text})
    divs=tmp_path/'divergences.csv'
    with divs.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['id','field','s1','anchor']);w.writeheader()
        w.writerow({'id':'T1','field':'fine','s1':'5000','anchor':'500'})
        w.writerow({'id':'T1','field':'outcome.type','s1':'"罚款"','anchor':'"拘留"'})
    rid,record,views,diffs,schema,request=prepare(batch,divs)[0]
    assert '决定给予甲罚款5000元' in request[1]['content'] and len(request)==2
    sid=next(v['id'] for v in views if '5000元' in v['text'])
    payload={field:{'adopt':'A','value':value,'evidence_ids':[sid],'reason':'原文'}
             for field,value in [('fine',5000),('outcome.type','罚款')]}
    assert compile_result(payload,record,views,diffs,schema)['fine']['value']==5000


def test_diagnostics_end_to_end_preserves_source_and_has_all_fields(tmp_path):
    text='甲携带赌资贰佰肆拾元参与赌博。决定罚款500元。'
    facts=text[:text.index('决定')]
    source=tmp_path/'records.jsonl'
    append(source,{'id':'T1','source':'synthetic','form':'narrative','source_text':text,
        'text_orig_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'input':{'target':'甲','views':[{'id':'S1','type':'facts','start':0,'end':len(facts),'text':facts}]}})
    before=source.read_bytes()
    report=diagnose_batch(source,tmp_path/'out')
    assert report['records']==1 and report['field_accuracy'] is None and source.read_bytes()==before
    obs=json.loads((tmp_path/'out/observability.json').read_text('utf-8'))
    assert len(obs['dimensions'][0]['fields'])==36
    graphs=[json.loads(l) for l in (tmp_path/'out/candidate-graphs.jsonl').read_text('utf-8').splitlines()]
    assert all(n['source_ref']['start']<len(facts) for n in graphs[0]['graph']['nodes'])


def test_exported_intermediate_schemas_validate_real_adapter_outputs():
    from jsonschema import Draft202012Validator
    bundle=make_bundle(ENGINE)
    for raw in ['2026年10月','次日','三个月','2026年2月30日']:
        Draft202012Validator(bundle['intermediate_schemas']['TemporalValue']).validate(normalize_time(raw,ref(raw)))
    for raw in ['贰佰肆拾元','3到5万元','超过1000元','约5万元']:
        Draft202012Validator(bundle['intermediate_schemas']['QuantityValue']).validate(normalize_quantity(raw,ref(raw)))
    assert bundle['normalization_policy']['status']=='proposed_pending_engine_adoption'


def test_new_outcome_commit_revalidated_and_context_mismatch_quarantined(tmp_path):
    text='决定给予甲罚款5000元。'
    views=[{'id':f'O{i}','start':a,'end':b,'text':text[a:b]} for i,(a,b) in enumerate(sentence_table(text),1)]
    manifest={'implementation':implementation_snapshot(),'version':OUTCOME_VERSION}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest),'utf-8')
    choice={'adopt':'A','value':5000,'evidence_ids':['O1'],'reason':'源文观察'}
    result={'id':'T1','policy':OUTCOME_VERSION,'plan_hash':digest(manifest),'view_hash':digest(views),
            'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'input_candidates':{'fine':{'a':5000,'b':500}},'decisions':{'fine':choice}}
    path=tmp_path/'record-T1.json'
    path.write_text(json.dumps(result,ensure_ascii=False),'utf-8')
    validated=attach_commit('T1',text,'甲',tmp_path)
    assert validated['status']=='candidate_validated' and validated['decisions']['fine']['value']==5000
    result['source_sha256']='0'*64
    path.write_text(json.dumps(result),'utf-8')
    with pytest.raises(ValueError,match='context_mismatch'):
        attach_commit('T1',text,'甲',tmp_path)


# --- E-05 integration tests ---

def test_e05_money_adapter():
    """E-05 money normalization produces compatible graph node format."""
    from evidence_graph import _e05_money
    text = "甲携带赌资3910元。"
    ref = SourceSpan.from_text(text, 5, 10)
    r = _e05_money("3910元", ref)
    assert r["kind"] == "exact"
    assert r["lower"] == "3910.0"
    assert r["upper"] == "3910.0"
    assert r["unit"] == "CNY"
    assert r["resolution"] == "resolved"
    assert r["e05"] is True


def test_e05_time_adapter():
    """E-05 date normalization produces compatible graph node format."""
    from evidence_graph import _e05_time
    text = "2025年8月15日处罚。"
    ref = SourceSpan.from_text(text, 0, 10)
    r = _e05_time("2025年8月15日", ref)
    assert r["kind"] == "calendar_range"
    assert r["start_date"] == "2025-08-15"
    assert r["precision"] == "day"
    assert r["resolution"] == "resolved"
    assert r["e05"] is True


def test_e05_graph_normalization_integration():
    """build_graph uses E-05 for money/time normalization."""
    text = "甲携带赌资500元，2025年8月被处罚。"
    views = [{"id": "S1.1", "start": 0, "end": len(text), "text": text, "type": "facts"}]
    graph = build_graph(text, views, "甲")
    money_nodes = [n for n in graph["nodes"] if n["kind"] == "money"]
    time_nodes = [n for n in graph["nodes"] if n["kind"] == "time"]
    assert len(money_nodes) >= 1
    assert money_nodes[0]["normalized"]["e05"] is True
    assert money_nodes[0]["normalized"]["unit"] == "CNY"
    if time_nodes:
        assert time_nodes[0]["normalized"]["e05"] is True
