"""Original synthetic cases and an independent Cartesian-product oracle."""
import copy,itertools,json,os,random,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from placement_desk.core import *
ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=(ROOT/'examples/deployment.json').read_bytes()
def res(cpu=2,ram=2,gpu=0):return dict(cpu_millis=cpu,ram_mib=ram,gpu_units=gpu)
def host(id,zone='z',cpu=4,ram=4,gpu=0,label=None):return dict(id=id,zone=zone,capacity=res(cpu,ram,gpu),accelerator=label)
def work(id='w',replicas=1,cpu=2,ram=2,gpu=0,label=None,spread='none'):return dict(id=id,replicas=replicas,resources=res(cpu,ram,gpu),accelerator=label,spread=spread)
def doc(ws,ns,modes=None,limit=20000):return dict(schema=1,candidate_limit=limit,failure_modes=modes or [],workloads=ws,plans=[dict(id='plan',nodes=ns)])
def oracle(ws,ns):
    tasks=[w for w in ws for _ in range(w['replicas'])]
    for assignment in itertools.product(range(len(ns)),repeat=len(tasks)):
        good=True
        for i,n in enumerate(ns):
            assigned=[w for w,j in zip(tasks,assignment) if j==i]
            for resource in RESOURCES:
                if sum(w['resources'][resource] for w in assigned)>n['capacity'][resource]:good=False
            if any(w['accelerator'] is not None and w['accelerator']!=n['accelerator'] for w in assigned):good=False
        for w in ws:
            hosts=[ns[j] for t,j in zip(tasks,assignment) if t['id']==w['id']]
            if w['spread']=='node' and len({n['id'] for n in hosts})!=len(hosts):good=False
            if w['spread']=='zone' and len({n['zone'] for n in hosts})!=len(hosts):good=False
        if good:return True
    return False
class Tests(unittest.TestCase):
    def test_example_failure_domain_difference(self):
        r=analyze(EXAMPLE);plans={p['id']:p for p in r['plans']}
        self.assertEqual(plans['two-zones']['all_requested_cases'],'model_infeasible')
        self.assertEqual(plans['three-zones']['all_requested_cases'],'model_feasible')
        self.assertEqual(len(plans['two-zones']['cases']),5);self.assertEqual(len(plans['three-zones']['cases']),7)
        self.assertEqual(plans['two-zones']['cases'][0]['status'],'model_feasible')
    def test_fragmentation_not_total_resource_fit(self):
        r=solve([work(cpu=3,ram=3)],[host('a',cpu=4,ram=1),host('b',cpu=1,ram=4)],100)
        self.assertEqual(r['status'],'model_infeasible')
    def test_gpu_label_and_integer_units(self):
        ws=[work(gpu=2,label='type-a')]
        self.assertEqual(solve(ws,[host('a',gpu=2,label='type-b')],100)['status'],'model_infeasible')
        self.assertEqual(solve(ws,[host('a',gpu=1,label='type-a'),host('b',gpu=1,label='type-a')],100)['status'],'model_infeasible')
        self.assertEqual(solve(ws,[host('a',gpu=2,label='type-a')],100)['status'],'model_feasible')
    def test_cpu_workload_can_use_gpu_host_without_consuming_gpu(self):
        r=solve([work()],[host('a',gpu=1,label='type-a')],100)
        self.assertEqual(r['remaining_capacity']['a']['gpu_units'],1)
    def test_node_vs_zone_spread(self):
        ns=[host('a'),host('b')]
        self.assertEqual(solve([work(replicas=2,spread='node')],ns,100)['status'],'model_feasible')
        self.assertEqual(solve([work(replicas=2,spread='zone')],ns,100)['status'],'model_infeasible')
    def test_spread_is_per_workload(self):
        r=solve([work('a',spread='zone'),work('b',spread='zone')],[host('n')],100)
        self.assertEqual(r['status'],'model_feasible')
    def test_zone_removes_all_its_nodes(self):
        d=doc([work()],[host('a','z'),host('b','z'),host('c','other')],['zone'])
        r=analyze(canonical(d));cases=r['plans'][0]['cases'];self.assertEqual(next(c for c in cases if c['subject']=='z')['removed_nodes'],['a','b'])
    def test_no_nodes_survive_is_infeasible_not_unknown(self):
        d=doc([work()],[host('a')],['node']);c=analyze(canonical(d))['plans'][0]['cases'][1]
        self.assertEqual(c['status'],'model_infeasible');self.assertEqual(c['candidate_checks'],0)
    def test_search_limit_unknown_not_infeasible(self):
        r=solve([work(replicas=2)],[host('a')],1)
        self.assertEqual(r['status'],'unknown_search_limit');self.assertEqual(r['placement'],[]);self.assertIsNone(r['remaining_capacity'])
    def test_exact_limit_success_and_exhaustion(self):
        self.assertEqual(solve([work()],[host('a')],1)['status'],'model_feasible')
        self.assertEqual(solve([work(cpu=5)],[host('a')],1)['status'],'model_infeasible')
        self.assertEqual(solve([work(cpu=5)],[host('a'),host('b')],1)['status'],'unknown_search_limit')
    def test_known_infeasible_dominates_unknown_aggregate(self):
        d=doc([work(replicas=2)],[host('a')],['node'],limit=1)
        r=analyze(canonical(d));self.assertEqual(r['plans'][0]['cases'][0]['status'],'unknown_search_limit')
        self.assertEqual(r['plans'][0]['all_requested_cases'],'model_infeasible')
    def test_all_replica_repacking_scope(self):
        d=doc([work(replicas=2)],[host('a'),host('b')],['node']);p=analyze(canonical(d))['plans'][0]
        self.assertEqual(p['all_requested_cases'],'model_feasible')
        self.assertEqual({a['node'] for a in p['cases'][1]['placement']},{'b'})
    def test_reordering_does_not_change_results_except_source_hash(self):
        d=load(EXAMPLE);a=analyze(canonical(d));d['plans'].reverse();d['failure_modes'].reverse()
        for p in d['plans']:p['nodes'].reverse()
        b=analyze(canonical(d));a.pop('input_sha256');b.pop('input_sha256');self.assertEqual(a,b)
    def test_250_small_cases_exhaustive_independent_oracle(self):
        rng=random.Random(734)
        for case in range(250):
            ns=[host('n'+str(i),zone='z'+str(rng.randrange(2)),cpu=rng.randint(1,6),ram=rng.randint(1,6),gpu=1,label='g') for i in range(rng.randint(1,3))]
            ws=[work('w'+str(i),replicas=rng.randint(1,2),cpu=rng.randint(1,4),ram=rng.randint(1,4),spread=rng.choice(['none','node','zone']),gpu=rng.randint(0,1)) for i in range(rng.randint(1,2))]
            for w in ws:w['accelerator']='g' if w['resources']['gpu_units'] else None
            expected=oracle(ws,ns);r=solve(ws,ns,20000)
            with self.subTest(case=case):
                self.assertEqual(r['status'],'model_feasible' if expected else 'model_infeasible')
                if expected:self.assertTrue(validate_placement(ws,ns,r['placement']))
    def test_witness_tamper(self):
        ws=[work(replicas=2,spread='node')];ns=[host('a'),host('b')];good=solve(ws,ns,100)['placement']
        for mutate in [lambda x:x.pop(),lambda x:x.append(x[0]),lambda x:x[0].update(replica=True),lambda x:x[0].update(zone='wrong'),lambda x:x[1].update(node=x[0]['node'])]:
            p=copy.deepcopy(good);mutate(p)
            with self.assertRaises(Invalid):validate_placement(ws,ns,p)
    def test_empty_failure_modes_only_healthy(self):
        r=analyze(canonical(doc([work()],[host('a')])));self.assertEqual(len(r['plans'][0]['cases']),1)
    def test_integer_types_and_bounds(self):
        for key,value in [('schema',True),('candidate_limit',False),('candidate_limit',0),('candidate_limit',20001),('candidate_limit',10**500),('candidate_limit',1.0)]:
            d=load(EXAMPLE);d[key]=value
            with self.assertRaises(Invalid):load(canonical(d))
    def test_replica_limits(self):
        for ws in [[work(replicas=True)],[work(replicas=13)],[work('a',replicas=7),work('b',replicas=6)]]:
            with self.assertRaises(Invalid):load(canonical(doc(ws,[host('a')])))
    def test_resource_and_label_validation(self):
        for change in [lambda w:w['resources'].update(cpu_millis=0),lambda w:w['resources'].update(ram_mib=None),lambda w:w['resources'].update(gpu_units=True),lambda w:w.update(accelerator='g'),lambda w:w.update(spread='any'),lambda w:w.update(id='=formula')]:
            w=work();change(w)
            with self.assertRaises(Invalid):load(canonical(doc([w],[host('a')])))
    def test_duplicate_ids(self):
        for d in [doc([work(),work()],[host('a')]),doc([work()],[host('a'),host('a')])]:
            with self.assertRaises(Invalid):load(canonical(d))
        d=load(EXAMPLE);d['plans'].append(d['plans'][0])
        with self.assertRaises(Invalid):load(canonical(d))
    def test_failure_modes_invalid(self):
        for modes in [['node','node'],['random'],[True],{}]:
            d=load(EXAMPLE);d['failure_modes']=modes
            with self.assertRaises(Invalid):load(canonical(d))
    def test_extra_fields_and_node_gpu_labels(self):
        d=load(EXAMPLE);d['plans'][0]['nodes'][0]['extra']='SECRET'
        with self.assertRaises(Invalid):load(canonical(d))
        d=load(EXAMPLE);d['plans'][0]['nodes'][0]['accelerator']=None
        with self.assertRaises(Invalid):load(canonical(d))
    def test_duplicate_deep_nonfinite_unicode(self):
        for raw in [b'{"x":1,"x":2}',b'['*20000+b'0'+b']'*20000,b'{"x":1e999}',b'{"x":NaN}',b'"\\ud800"','{}'.encode('utf-16')]:
            with self.assertRaises(Invalid):load(raw)
    def test_maximum_shapes_budget_bounded_bundle(self):
        d=doc([work('w'+str(i),cpu=1,ram=1,spread='node') for i in range(12)],[host('n'+str(i),'z'+str(i),cpu=100,ram=100) for i in range(8)],['node','zone'])
        d['plans']=[{'id':'p'+str(i),'nodes':copy.deepcopy(d['plans'][0]['nodes'])} for i in range(3)]
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);p=r/'s';p.write_bytes(canonical(d));report=build(p,r/'b');self.assertEqual(len(report['plans']),3);self.assertTrue(all(len(x['cases'])==17 for x in report['plans']));self.assertEqual(verify(r/'b'),report)
    def test_byte_outputs_and_sources(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'s';p.write_bytes(EXAMPLE.replace(b'\n',b'\r\n'))
            with patch.object(Path,'write_text',side_effect=AssertionError('forbidden')):r=build(p,root/'b')
            self.assertEqual((root/'b/input.json').read_bytes(),p.read_bytes());self.assertEqual((root/'b/report.json').read_bytes(),canonical(r));self.assertEqual(verify(root/'b'),r)
    def test_no_overwrite_extra_tamper(self):
        for name in ('input.json','report.json','review.md','extra'):
            with tempfile.TemporaryDirectory() as t:
                out=Path(t)/'b';build(ROOT/'examples/deployment.json',out);p=out/name;p.write_bytes((p.read_bytes() if p.exists() else b'')+b'\n')
                with self.assertRaises(Invalid):verify(out)
                with self.assertRaises(FileExistsError):build(ROOT/'examples/deployment.json',out)
    def test_output_preflight(self):
        with tempfile.TemporaryDirectory() as t,patch('placement_desk.core.OUTPUT_LIMIT',1):
            out=Path(t)/'b'
            with self.assertRaises(Invalid):build(ROOT/'examples/deployment.json',out)
            self.assertFalse(out.exists())
    def test_bounded_regular_read(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'p';p.write_bytes(b'x'*10)
            self.assertEqual(read(p,10),b'x'*10)
            with self.assertRaises(Invalid):read(p,9)
            with self.assertRaises(Invalid):read(root)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'p'
            try:p.symlink_to(ROOT/'examples/deployment.json')
            except OSError:self.skipTest('OS disallows symlink creation')
            with self.assertRaises(Invalid):read(p)
    @unittest.skipUnless(hasattr(os,'mkfifo'),'POSIX FIFO unavailable')
    def test_fifo_cli_no_private_echo(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'SECRET_SENTINEL';os.mkfifo(p)
            r=subprocess.run([sys.executable,'-m','placement_desk','analyze',str(p),'--out',str(Path(t)/'b')],cwd=ROOT,capture_output=True,text=True,timeout=2)
            self.assertEqual(r.returncode,2);self.assertNotIn('SECRET_SENTINEL',r.stderr);self.assertNotIn('Traceback',r.stderr)
    def test_cli_gate_true_false_unknown(self):
        for filename,plan,code in [('deployment.json','three-zones',0),('deployment.json','two-zones',3),('limited-search.json','three-zones',3),('deployment.json','missing',2)]:
            with tempfile.TemporaryDirectory() as t:
                out=Path(t)/'b'
                for args in [['analyze','examples/'+filename,'--out',str(out)],['verify',str(out)]]:
                    r=subprocess.run([sys.executable,'-m','placement_desk',*args,'--require-plan',plan],cwd=ROOT,capture_output=True,text=True);self.assertEqual(r.returncode,code,r.stderr)
if __name__=='__main__':unittest.main()
