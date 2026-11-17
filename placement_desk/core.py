"""Declared finite placement feasibility; no scheduler or deployment execution."""
import hashlib,io,json,os,re,stat
from pathlib import Path
INPUT_LIMIT=1024*1024
OUTPUT_LIMIT=8*1024*1024
class Invalid(ValueError):pass

def read(path,limit=INPUT_LIMIT):
    try:
        if not stat.S_ISREG(Path(path).lstat().st_mode):raise Invalid('Regular non-symlink file required.')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise Invalid('File type or size limit exceeded.')
            with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(limit+1)
        finally:
            if fd is not None:os.close(fd)
        if len(raw)>limit:raise Invalid('File size limit exceeded.')
        raw.decode('utf8');return raw
    except (OSError,UnicodeError):raise Invalid('Cannot safely read bounded UTF-8 file.') from None

def parse(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise Invalid('Duplicate JSON keys.')
            k.encode('utf8');result[k]=v
        return result
    def bad(x):raise Invalid('Non-finite number.')
    try:
        if len(raw)>INPUT_LIMIT:raise Invalid('Input exceeds 1 MiB.')
        result=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=bad)
        queue=[(result,0)]
        while queue:
            value,depth=queue.pop()
            if isinstance(value,(list,dict)):
                if depth>=16:raise Invalid('JSON depth exceeded.')
                queue.extend((v,depth+1) for v in (value.values() if isinstance(value,dict) else value))
            elif isinstance(value,str):value.encode('utf8')
            elif isinstance(value,float):raise Invalid('Only integer ticks are supported.')
        return result
    except (ValueError,UnicodeError,RecursionError):raise Invalid('Invalid bounded JSON.') from None

def fields(item,names):
    if not isinstance(item,dict) or set(item)!=set(names):raise Invalid('Unexpected or missing fields.')
def integer(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:raise Invalid('Integer outside declared bounds.')
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,47}',value):raise Invalid('Invalid identifier.')
RESOURCES=('cpu_millis','ram_mib','gpu_units')
def resources(item):
    fields(item,RESOURCES)
    integer(item['cpu_millis'],1,10**9);integer(item['ram_mib'],1,10**9);integer(item['gpu_units'],0,64)
def load(raw):
    d=parse(raw);fields(d,['schema','candidate_limit','failure_modes','workloads','plans'])
    integer(d['schema'],1,1);integer(d['candidate_limit'],1,20000)
    if not isinstance(d['failure_modes'],list) or not all(type(x) is str and x in ('node','zone') for x in d['failure_modes']) or len(set(d['failure_modes']))!=len(d['failure_modes']):raise Invalid('Failure modes must be unique node/zone entries.')
    if not isinstance(d['workloads'],list) or not 1<=len(d['workloads'])<=12:raise Invalid('Expected 1..12 workloads.')
    ids=set();total=0
    for w in d['workloads']:
        fields(w,['id','replicas','resources','accelerator','spread']);identifier(w['id']);resources(w['resources'])
        if w['id'] in ids:raise Invalid('Duplicate workload.')
        ids.add(w['id']);integer(w['replicas'],1,12);total+=w['replicas']
        if total>12:raise Invalid('At most 12 total replicas.')
        if w['accelerator'] is not None:identifier(w['accelerator'])
        if (w['resources']['gpu_units']>0)!=(w['accelerator'] is not None):raise Invalid('GPU workloads need an explicit accelerator label; CPU workloads use null.')
        if type(w['spread']) is not str or w['spread'] not in ('none','node','zone'):raise Invalid('Unknown spread mode.')
    if not isinstance(d['plans'],list) or not 1<=len(d['plans'])<=3:raise Invalid('Expected 1..3 plans.')
    names=set()
    for p in d['plans']:
        fields(p,['id','nodes']);identifier(p['id'])
        if p['id'] in names:raise Invalid('Duplicate plan.')
        names.add(p['id'])
        if not isinstance(p['nodes'],list) or not 1<=len(p['nodes'])<=8:raise Invalid('Expected 1..8 nodes per plan.')
        seen=set()
        for n in p['nodes']:
            fields(n,['id','zone','capacity','accelerator']);identifier(n['id']);identifier(n['zone']);resources(n['capacity'])
            if n['id'] in seen:raise Invalid('Duplicate node.')
            seen.add(n['id'])
            if n['accelerator'] is not None:identifier(n['accelerator'])
            if (n['capacity']['gpu_units']>0)!=(n['accelerator'] is not None):raise Invalid('GPU nodes need an explicit accelerator label; CPU nodes use null.')
    return d

def canonical(value):return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode('utf8')
def solve(workloads,nodes,limit):
    """Deterministic exhaustive DFS until feasible, exhausted or budget-limited."""
    nodes=sorted(nodes,key=lambda n:n['id'])
    ordered=sorted(workloads,key=lambda w:(sum(w['accelerator'] is None or w['accelerator']==n['accelerator'] for n in nodes),-w['resources']['gpu_units'],-w['resources']['ram_mib'],-w['resources']['cpu_millis'],w['id']))
    replicas=[(w,i) for w in ordered for i in range(w['replicas'])]
    used={n['id']:{r:0 for r in RESOURCES} for n in nodes};placed=[];attempts=0;exhausted=False
    def visit(index):
        nonlocal attempts,exhausted
        if index==len(replicas):return True
        w,replica=replicas[index]
        for n in nodes:
            if attempts>=limit:exhausted=True;return False
            attempts+=1
            if w['accelerator'] is not None and w['accelerator']!=n['accelerator']:continue
            if any(used[n['id']][r]+w['resources'][r]>n['capacity'][r] for r in RESOURCES):continue
            if w['spread']!='none' and any(a['workload']==w['id'] and (a['node']==n['id'] if w['spread']=='node' else a['zone']==n['zone']) for a in placed):continue
            for r in RESOURCES:used[n['id']][r]+=w['resources'][r]
            placed.append({'workload':w['id'],'replica':replica,'node':n['id'],'zone':n['zone']})
            if visit(index+1):return True
            placed.pop()
            for r in RESOURCES:used[n['id']][r]-=w['resources'][r]
            if exhausted:return False
        return False
    found=visit(0)
    status='model_feasible' if found else 'unknown_search_limit' if exhausted else 'model_infeasible'
    return {'status':status,'candidate_checks':attempts,'candidate_limit':limit,'placement':list(placed) if found else [],'remaining_capacity':{n['id']:{r:n['capacity'][r]-used[n['id']][r] for r in RESOURCES} for n in nodes} if found else None}

def validate_placement(workloads,nodes,placement):
    """Independent witness checker, not a second search implementation."""
    if not isinstance(placement,list):raise Invalid('Invalid placement witness.')
    tasks={w['id']:w for w in workloads};hosts={n['id']:n for n in nodes}
    expected={(w['id'],i) for w in workloads for i in range(w['replicas'])};seen=set()
    usage={n['id']:{r:0 for r in RESOURCES} for n in nodes};domains={w['id']:set() for w in workloads}
    for a in placement:
        fields(a,['workload','replica','node','zone'])
        if type(a['workload']) is not str or type(a['node']) is not str or type(a['replica']) is not int:raise Invalid('Invalid witness field type.')
        key=(a['workload'],a['replica'])
        if key not in expected or key in seen or a['node'] not in hosts:raise Invalid('Unknown, repeated or invalid replica placement.')
        seen.add(key);w=tasks[a['workload']];n=hosts[a['node']]
        if a['zone']!=n['zone'] or (w['accelerator'] is not None and w['accelerator']!=n['accelerator']):raise Invalid('Witness label mismatch.')
        if w['spread']!='none':
            domain=n['id'] if w['spread']=='node' else n['zone']
            if domain in domains[w['id']]:raise Invalid('Witness violates spread.')
            domains[w['id']].add(domain)
        for r in RESOURCES:
            usage[n['id']][r]+=w['resources'][r]
            if usage[n['id']][r]>n['capacity'][r]:raise Invalid('Witness exceeds capacity.')
    if seen!=expected:raise Invalid('Witness misses replicas.')
    return True

def analyze(raw):
    d=load(raw);plans=[]
    for p in sorted(d['plans'],key=lambda p:p['id']):
        nodes=p['nodes'];cases=[('healthy',None,[])]
        if 'node' in d['failure_modes']:cases.extend(('node',n['id'],[n['id']]) for n in sorted(nodes,key=lambda n:n['id']))
        if 'zone' in d['failure_modes']:cases.extend(('zone',z,sorted(n['id'] for n in nodes if n['zone']==z)) for z in sorted({n['zone'] for n in nodes}))
        results=[]
        for mode,subject,removed in cases:
            surviving=[n for n in nodes if n['id'] not in removed]
            result=solve(d['workloads'],surviving,d['candidate_limit'])
            if result['status']=='model_feasible':validate_placement(d['workloads'],surviving,result['placement'])
            results.append({'mode':mode,'subject':subject,'removed_nodes':removed,**result})
        statuses={r['status'] for r in results}
        gate='model_infeasible' if 'model_infeasible' in statuses else 'unknown_search_limit' if 'unknown_search_limit' in statuses else 'model_feasible'
        plans.append({'id':p['id'],'all_requested_cases':gate,'cases':results})
    return {'schema':1,'semantics':'independent-full-repacking-v1','input_sha256':hashlib.sha256(raw).hexdigest(),'failure_modes':sorted(d['failure_modes']),'workload_replicas':sum(w['replicas'] for w in d['workloads']),'plans':plans,'scope':'Declared indivisible-resource placement only; no deployment, performance prediction, failover guarantee or hardware validation.'}

def review(report):
    lines=['# Placement Desk','',''+report['scope'],'','Every failure case permits restarting and repacking ALL replicas, not just failed ones. This is not a non-disruptive failover plan.','', '| Plan | Case | Removed nodes | Result | Candidate checks |','|---|---|---|---|---:|']
    for p in report['plans']:
        for c in p['cases']:lines.append(f"| {p['id']} | {c['mode']}:{c['subject'] or '-'} | {', '.join(c['removed_nodes']) or '-'} | {c['status']} | {c['candidate_checks']} |")
    lines+=['','Feasible placements and residual capacities are in report.json. Unknown means the deterministic candidate-check budget stopped search, not that placement is impossible. Infeasible is only within the declared finite model. No prices or hardware throughput are inferred.','']
    return '\n'.join(lines).encode('utf8')
def build(source,out):
    raw=read(source);report=analyze(raw);files={'report.json':canonical(report),'review.md':review(report)}
    if any(len(v)>OUTPUT_LIMIT for v in files.values()):raise Invalid('Generated report limit exceeded.')
    files['input.json']=raw;root=Path(out);root.mkdir(exist_ok=False)
    for name,data in files.items():(root/name).write_bytes(data)
    return report

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!={'input.json','report.json','review.md'}:raise Invalid('Unexpected bundle structure.')
    report=analyze(read(root/'input.json'))
    if read(root/'report.json',OUTPUT_LIMIT)!=canonical(report) or read(root/'review.md',OUTPUT_LIMIT)!=review(report):raise Invalid('Bundle differs from recomputation.')
    return report
