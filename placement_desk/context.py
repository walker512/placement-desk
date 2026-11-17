"""Declared cost and directed-flow review of a deterministic placement witness."""
import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from . import core

LIMIT = 10**15
GIB = 1073741824
NAMES = {'input.json', 'context.json', 'placement.json', 'context-report.json', 'architecture.txt'}

def rational(value, positive=False):
    core.fields(value, ['numerator', 'denominator'])
    core.integer(value['numerator'], 1 if positive else 0, LIMIT)
    core.integer(value['denominator'], 1, LIMIT)
    return Fraction(value['numerator'], value['denominator'])

def amount(value):
    return None if value is None else {'numerator': value.numerator, 'denominator': value.denominator}

def items(value, maximum):
    if not isinstance(value, list) or len(value)>maximum:
        raise core.Invalid('Invalid bounded list.')
    return value

def pairs(value, known=None):
    if value is None: return None
    seen=set()
    for pair in items(value, 64):
        if not isinstance(pair,list) or len(pair)!=2: raise core.Invalid('Expected directed pair.')
        for name in pair:
            core.identifier(name)
            if known is not None and name not in known: raise core.Invalid('Unknown site in boundary.')
        if tuple(pair) in seen: raise core.Invalid('Repeated pair.')
        seen.add(tuple(pair))
    return seen

def load(raw, context_raw):
    deployment=core.load(raw)
    d=core.parse(context_raw)
    core.fields(d,['schema','input_sha256','currency','duration_hours','assumptions','sites','nodes','egress_rates','flows'])
    core.integer(d['schema'],1,1)
    if d['input_sha256']!=hashlib.sha256(raw).hexdigest(): raise core.Invalid('Exact input binding differs.')
    core.identifier(d['currency']);rational(d['duration_hours'],True)
    if not isinstance(d['assumptions'],str) or not 1<=len(d['assumptions'])<=4000: raise core.Invalid('State the human assumptions and price basis.')
    sites={}
    for s in items(d['sites'],24):
        core.fields(s,['id','kind','region']);core.identifier(s['id'])
        if s['id'] in sites or type(s['kind']) is not str or s['kind'] not in ('local','cloud'): raise core.Invalid('Invalid site.')
        if s['region'] is not None:core.identifier(s['region'])
        sites[s['id']]=s
    expected={(p['id'],n['id']) for p in deployment['plans'] for n in p['nodes']};seen=set()
    for n in items(d['nodes'],24):
        core.fields(n,['plan','node','site','hourly_rate'])
        for k in ('plan','node','site'):core.identifier(n[k])
        key=(n['plan'],n['node'])
        if key not in expected or key in seen or n['site'] not in sites:raise core.Invalid('Node mapping must exactly cover inventory.')
        seen.add(key)
        if n['hourly_rate'] is not None:rational(n['hourly_rate'])
    if seen!=expected:raise core.Invalid('Missing node mapping.')
    seen=set()
    for r in items(d['egress_rates'],64):
        core.fields(r,['from_site','to_site','per_gib'])
        for k in ('from_site','to_site'):core.identifier(r[k])
        key=(r['from_site'],r['to_site'])
        if key in seen or key[0]==key[1] or any(s not in sites for s in key):raise core.Invalid('Invalid directional rate.')
        seen.add(key)
        if r['per_gib'] is not None:rational(r['per_gib'])
    tasks={w['id']:w['replicas'] for w in deployment['workloads']};seen=set()
    for f in items(d['flows'],24):
        core.fields(f,['id','from','to','bytes','allowed_site_pairs','allowed_region_pairs']);core.identifier(f['id'])
        if f['id'] in seen:raise core.Invalid('Repeated flow.')
        seen.add(f['id'])
        for k in ('from','to'):
            e=f[k];core.fields(e,['workload','replica']);core.identifier(e['workload']);core.integer(e['replica'],0,11)
            if e['workload'] not in tasks or e['replica']>=tasks[e['workload']]:raise core.Invalid('Invalid replica endpoint.')
        if f['bytes'] is not None:core.integer(f['bytes'],0,LIMIT)
        pairs(f['allowed_site_pairs'],sites);pairs(f['allowed_region_pairs'])
    return deployment,d

def boundary(allowed, actual):
    if allowed is None:return 'unknown_not_declared'
    if not allowed:return 'outside_declared_pairs'
    if None in actual:return 'unknown_region'
    return 'allowed_declared_pair' if actual in pairs(allowed) else 'outside_declared_pairs'

def subtotal(components):
    known=sum((Fraction(c['amount']['numerator'],c['amount']['denominator']) for c in components if c['amount'] is not None),Fraction(0))
    unknown=[c['id'] for c in components if c['amount'] is None]
    return {'known_subtotal':amount(known),'unknown_items':unknown,'modeled_amount':None if unknown else amount(known)}

def analyze(raw,context_raw):
    deployment,d=load(raw,context_raw);placement=core.analyze(raw)
    sites={s['id']:s for s in d['sites']};nodes={(n['plan'],n['node']):n for n in d['nodes']}
    rates={(r['from_site'],r['to_site']):r['per_gib'] for r in d['egress_rates']}
    duration=rational(d['duration_hours']);plans=[]
    for p in placement['plans']:
        fixed=[{'id':n['node'],'amount':None if n['hourly_rate'] is None else amount(rational(n['hourly_rate'])*duration)} for n in sorted(d['nodes'],key=lambda x:x['node']) if n['plan']==p['id']]
        cases=[]
        for case in p['cases']:
            result={'mode':case['mode'],'subject':case['subject'],'placement_status':case['status'],'flows':None,'cross_site_cost':None,'modeled_cost':None,'boundary_status':'not_evaluated_no_placement'}
            if case['status']=='model_feasible':
                witness={(a['workload'],a['replica']):a for a in case['placement']};flows=[];costs=[]
                for f in sorted(d['flows'],key=lambda x:x['id']):
                    endpoints=[]
                    for k in ('from','to'):
                        w=witness[(f[k]['workload'],f[k]['replica'])];node=nodes[(p['id'],w['node'])];site=sites[node['site']]
                        endpoints.append({'workload':w['workload'],'replica':w['replica'],'node':w['node'],'zone':w['zone'],'site':site['id'],'kind':site['kind'],'region':site['region']})
                    site_pair=tuple(e['site'] for e in endpoints);region_pair=tuple(e['region'] for e in endpoints)
                    sb=boundary(f['allowed_site_pairs'],site_pair);rb=boundary(f['allowed_region_pairs'],region_pair)
                    overall='outside_declared_pairs' if 'outside_declared_pairs' in (sb,rb) else 'unknown' if any(x.startswith('unknown') for x in (sb,rb)) else 'allowed_declared_pairs'
                    rate=rates.get(site_pair);cross=site_pair[0]!=site_pair[1]
                    # Zero declared bytes costs zero even when the cross-site rate is unknown.
                    cost=Fraction(0) if not cross or f['bytes']==0 else None if f['bytes'] is None or rate is None else Fraction(f['bytes'],GIB)*rational(rate)
                    cost_status='excluded_same_site' if not cross else 'declared_zero_bytes' if f['bytes']==0 else 'unknown' if cost is None else 'calculated_declared_rate'
                    flows.append({'id':f['id'],'from':endpoints[0],'to':endpoints[1],'declared_bytes':f['bytes'],'site_boundary':sb,'region_boundary':rb,'boundary_status':overall,'cross_site_amount':amount(cost),'cost_status':cost_status})
                    costs.append({'id':f['id'],'amount':amount(cost)})
                statuses={f['boundary_status'] for f in flows}
                overall='not_evaluated_no_declared_flows' if not flows else 'outside_declared_pairs' if 'outside_declared_pairs' in statuses else 'unknown' if 'unknown' in statuses else 'allowed_declared_pairs'
                result.update(flows=flows,cross_site_cost=subtotal(costs),modeled_cost=subtotal([{'id':'node:'+x['id'],'amount':x['amount']} for x in fixed]+[{'id':'flow:'+x['id'],'amount':x['amount']} for x in costs]),boundary_status=overall)
            cases.append(result)
        plans.append({'id':p['id'],'inventory_node_cost':subtotal(fixed),'inventory_node_components':fixed,'cases':cases})
    return placement,{'schema':1,'input_sha256':hashlib.sha256(raw).hexdigest(),'context_sha256':hashlib.sha256(context_raw).hexdigest(),'currency':d['currency'],'duration_hours':d['duration_hours'],'assumptions':d['assumptions'],'plans':plans,'scope':'Declared full-inventory reservation plus declared cross-site flow charges only. Each case independently spans the entire duration. Not complete total cost, optimal routing, compliance or deployment advice.'}

def architecture(report):
    q=lambda v:json.dumps(v,ensure_ascii=False)
    lines=['PLACEMENT DESK: DECLARED CONTEXT REVIEW',report['scope'],'','All inventory nodes remain billed in failure cases. Never sum mutually exclusive cases into a bill.','A boundary failure describes this deterministic witness, not proof that no allowed placement exists.','Amounts are exact rational currency units. Unknown is not zero. Same-site network is excluded, not guaranteed free.','No runtime latency, connectivity, throughput, migration/recovery, electricity, tax, storage, discount or minimum-billing model.','Declared flow bytes are per whole duration per case; no workload-level splitting or replication inference.','Input SHA256: '+report['input_sha256'],'Context SHA256: '+report['context_sha256'],'Human price/measurement assumptions: '+q(report['assumptions']),'Currency: '+q(report['currency']),'Duration hours: '+q(report['duration_hours'])]
    for p in report['plans']:
        lines+=['','PLAN '+p['id'],'Full inventory cost: '+q(p['inventory_node_cost'])]
        for c in p['cases']:
            lines+=['  CASE '+c['mode']+':'+str(c['subject'])+' / '+c['placement_status'],'  Boundary of this witness: '+c['boundary_status']]
            if c['flows'] is None:lines.append('  No placement witness: no flow, locality or combined cost conclusion.');continue
            for f in c['flows']:
                def label(e):return f"{e['workload']}[{e['replica']}] @ {e['node']} / {e['site']} ({e['kind']}, region={e['region']})"
                lines += ['    '+f['id']+': '+label(f['from'])+' -> '+label(f['to']), '      bytes='+str(f['declared_bytes'])+' site='+f['site_boundary']+' region='+f['region_boundary']+' cost='+q(f['cross_site_amount'])+' ('+f['cost_status']+')']
            lines.append('  Modeled charges only: '+q(c['modeled_cost']))
    lines+=['','HUMAN CONFIRMATION REQUIRED: validate price date/source and billing conditions; capacity measurements; actual routing and data classification; current allowed destinations; same-site fees and unmodeled charges; recovery and latency on real systems.','Hashes detect inconsistency, not author identity or coordinated source replacement. No network requests or deployments.','']
    return '\n'.join(lines).encode('utf8')

def generated(raw,side):
    placement,report=analyze(raw,side)
    files={'input.json':raw,'context.json':side,'placement.json':core.canonical(placement),'context-report.json':core.canonical(report),'architecture.txt':architecture(report)}
    if any(len(v)>core.OUTPUT_LIMIT for v in files.values()):raise core.Invalid('Generated output limit exceeded.')
    return files,report

def build(source,sidecar,out):
    files,report=generated(core.read(source),core.read(sidecar));root=Path(out);root.mkdir(exist_ok=False)
    for name,content in files.items():(root/name).write_bytes(content)
    return report

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!=NAMES:raise core.Invalid('Unexpected context bundle.')
    files,report=generated(core.read(root/'input.json'),core.read(root/'context.json'))
    if any(core.read(root/name,core.OUTPUT_LIMIT)!=content for name,content in files.items()):raise core.Invalid('Recomputed context differs.')
    return report

def main():
    parser=argparse.ArgumentParser(description='Review declared costs and data paths on actual placement witnesses, without deployment.')
    sub=parser.add_subparsers(dest='command',required=True)
    a=sub.add_parser('analyze');a.add_argument('input');a.add_argument('context');a.add_argument('--out',required=True)
    v=sub.add_parser('verify');v.add_argument('bundle')
    args=parser.parse_args()
    try:
        report=build(args.input,args.context,args.out) if args.command=='analyze' else verify(args.bundle)
        print(json.dumps({'consistent':True,'plans':[p['id'] for p in report['plans']],'scope':report['scope']}));return 0
    except (core.Invalid,OSError,ValueError,RecursionError,TypeError):
        print('Invalid bounded declaration, input binding, bundle or filesystem. Contents are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
