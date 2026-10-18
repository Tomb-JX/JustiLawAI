"""Export the executable engine/wire contract plus proposed shared normalization IR."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from element_contract import contract_snapshot, digest, engine_contract, reference_schema
from field_rules import field_catalog
from normalization import backend_fingerprint

VERSION = 'postprocess-contract-1'


def intermediate_schemas():
    ref = {'type':'object', 'properties':{
        'coordinate_system':{'const':'original-python-char'}, 'text_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},
        'start':{'type':'integer','minimum':0},'end':{'type':'integer','minimum':1},'quote':{'type':'string','minLength':1}},
        'required':['coordinate_system','text_sha256','start','end','quote'],'additionalProperties':False}
    nullable = {'type':['string','null']}
    common = {'raw':{'type':'string'},'source_ref':ref,'normalizer':{'type':'string'},'backend':{'type':'string'},
              'resolution':{'enum':['resolved','unresolved']},'reason':nullable}
    temporal = {'type':'object','properties':{**common,'kind':{'enum':['unknown','calendar_range','duration']},
        'precision':{'enum':[None,'day','month','year','range']},'calendar':{'const':'gregorian'},'start_date':nullable,'end_date':nullable,
        'anchor_ref':{'anyOf':[ref,{'type':'null'}]},'definition':{'type':'string'},
        'duration':{'type':'object','additionalProperties':{'type':'number','minimum':0}}},
        'required':list(common)+['kind','precision','calendar','start_date','end_date','anchor_ref'],'additionalProperties':False}
    quantity = {'type':'object','properties':{**common,'unit':{'enum':['CNY','count']},
        'kind':{'enum':['unknown','exact','interval','lower_bound','upper_bound','approximate']},
        'lower':nullable,'upper':nullable,'lower_inclusive':{'type':'boolean'},'upper_inclusive':{'type':'boolean'},
        'operator':{'enum':[None,'=','>=','>','<=','<','~']},'center':{'type':'string'},
        'backend_hint':{'type':'array','items':{'type':'string'}}},
        'required':list(common)+['unit','kind','lower','upper','lower_inclusive','upper_inclusive','operator'],
        'additionalProperties':False}
    return {'SourceSpan':ref,'TemporalValue':temporal,'QuantityValue':quantity}


def make_bundle(engine):
    result = {'version':VERSION,'engine_contract':contract_snapshot(engine),'field_catalog':field_catalog(engine),
              'prompt':engine.teacher_system_prompt(),'output_schema':reference_schema(engine),
              'intermediate_schemas':intermediate_schemas(),'normalizer_backend':backend_fingerprint(),
              'normalization_policy':{'status':'adopted','default':'lossless-only',
                    'explicit_compatibility_policies':['schema-1.1.0-month-first','schema-1.1.0-close-endpoints','schema-1.1.0-30day-month'],
                    'approximation_default':'no_numeric_projection','aliases_default':'engine-exact-values-only'},
              'binding_policy':{'status':'adopted',
                    'types':['shared_fact','target_specific','needs_review'],
                    'source':'binding_rules.py','version':'binding-rules-v1',
                    'accept_in_resolve':['lexical_candidate','target_specific']},
              'proof_boundary':'schema/span/candidate validation does not establish semantic accuracy',
              'release_approved':False}
    return {**result,'hash':digest(result)}


def main():
    from s1 import data_root
    __import__('sys').stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if not a.out.resolve().is_relative_to((data_root()/'s1_runs').resolve()) or a.out.exists():
        p.error('只写新的 $DATA/s1_runs 子目录')
    bundle=make_bundle(engine_contract())
    a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'contract.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n','utf-8')
    for name,schema in bundle['intermediate_schemas'].items():
        (a.out/(name+'.schema.json')).write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'version':VERSION,'hash':bundle['hash'],'engine_schema':bundle['engine_contract']['engine_schema_version'],
                      'semantic_adoption':bundle['normalization_policy']['status']}))


if __name__=='__main__':
    main()
