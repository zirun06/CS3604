"""Ctrip-only lossless repeated-text factoring and explicit startup-record index."""
from collections import Counter, defaultdict
import json
import re
import yaml

MARKER='{{CTRIP_SHARED_'
ROW=re.compile(r'^\s*- ([^\n:]+): (\{[^\n]+\})[ \t]*$',re.MULTILINE)

def transform(node, action):
    if isinstance(node,dict):return {key:transform(value,action) for key,value in node.items()}
    if isinstance(node,list):return [transform(value,action) for value in node]
    return action(node) if isinstance(node,str) else node

def prepare_context(source):
    root=yaml.safe_load(source);counts=Counter();records=defaultdict(list);seen=defaultdict(set)
    def count(value):
        if MARKER in value:raise ValueError('Ctrip text uses a reserved shared-text marker')
        counts.update(line for line in value.split('\n') if len(line)>=160);return value
    transform(root,count)
    blocks={f'{MARKER}{i:04d}}}}}':line for i,line in enumerate((line for line,c in counts.items() if c>1),1)}
    refs={line:key for key,line in blocks.items()}
    tree=transform(root,lambda value:'\n'.join(refs.get(line,line) for line in value.split('\n')))
    def visit(node):
        if isinstance(node,dict):
            for key,value in node.items():
                if key=='Given' and isinstance(value,str):
                    for category,raw in ROW.findall(value):
                        try:record=json.loads(raw)
                        except ValueError:continue
                        identity=json.dumps(record,sort_keys=True,ensure_ascii=False)
                        if identity not in seen[category]:seen[category].add(identity);records[category].append(record)
                else:visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(root)
    packet={'format':'Shared tokens expand literally to shared_text_blocks, including all original constraints. Every requirement and scenario remains mandatory.',
            'shared_text_blocks':blocks,'requirements':tree}
    condensed=yaml.safe_dump(packet,allow_unicode=True,sort_keys=False,width=100000)
    return {'requirements_yaml':condensed,'declared_ctrip_world':{'seed_records':dict(records),
        'interpretation':'Merge overlapping views by real business identity. Booking and flight-status datasets are distinct even for equal flight numbers. Seed declared accounts, published data and immutable legacy records; do not preseed scenario-created orders or personal records. Simulated code delivery still requires a sent code bound to the current cookie/target/purpose.'},
        'metrics':{'original_characters':len(source),'generation_characters':len(condensed),'shared_blocks':len(blocks)}}

def expand_context(packet):
    return transform(packet['requirements'],lambda value:'\n'.join(packet['shared_text_blocks'].get(line,line) for line in value.split('\n')))
