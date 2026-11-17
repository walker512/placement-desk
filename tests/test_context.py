"""Synthetic context regressions, no external services or real prices."""
import copy, hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from placement_desk import core, context
ROOT=Path(__file__).resolve().parents[1]
class ContextTests(unittest.TestCase):
    def setUp(self):
        self.raw=(ROOT/'examples/context-deployment.json').read_bytes()
        self.side=json.loads((ROOT/'examples/context-assumptions.json').read_text())
    def run_model(self,side=None,raw=None):return context.analyze(raw or self.raw,core.canonical(self.side if side is None else side))[1]
    def case(self,report,plan='hybrid',subject=None):return next(c for p in report['plans'] if p['id']==plan for c in p['cases'] if c['subject']==subject)
    def test_reuses_real_witness_and_flow_changes(self):
        placement,r=context.analyze(self.raw,core.canonical(self.side));self.assertEqual(placement,core.analyze(self.raw))
        h=self.case(r);f=self.case(r,subject='b')
        self.assertEqual(h['flows'][0]['to']['site'],'office');self.assertEqual(f['flows'][0]['to']['site'],'cloud-b')
        self.assertEqual(h['boundary_status'],'allowed_declared_pairs');self.assertEqual(f['boundary_status'],'outside_declared_pairs')
    def test_exact_cost_and_inventory_survives_failure(self):
        r=self.run_model();h=self.case(r);f=self.case(r,subject='b')
        self.assertEqual(h['modeled_cost']['modeled_amount'],{'numerator':9,'denominator':10})
        self.assertEqual(f['modeled_cost']['modeled_amount'],{'numerator':1,'denominator':1})
    def test_unknown_node_not_zero(self):
        cost=self.case(self.run_model(),'local')['modeled_cost'];self.assertIsNone(cost['modeled_amount']);self.assertIn('node:c',cost['unknown_items'])
    def test_unknown_rate_not_zero(self):self.assertIsNone(self.case(self.run_model(),'cloud','b')['cross_site_cost']['modeled_amount'])
    def test_unknown_bytes(self):
        self.side['flows'][0]['bytes']=None;self.assertIsNone(self.case(self.run_model(),subject='b')['modeled_cost']['modeled_amount'])
    def test_zero_bytes_unknown_rate_is_explicit_zero(self):
        self.side['flows'][0]['bytes']=0;c=self.case(self.run_model(),'cloud','b');self.assertEqual(c['flows'][0]['cost_status'],'declared_zero_bytes');self.assertEqual(c['cross_site_cost']['modeled_amount']['numerator'],0)
    def test_unknown_region_and_undeclared_boundary(self):
        self.side['sites'][0]['region']=None;self.assertEqual(self.case(self.run_model())['boundary_status'],'unknown')
        self.side['flows'][0]['allowed_site_pairs']=None;self.assertEqual(self.case(self.run_model())['flows'][0]['site_boundary'],'unknown_not_declared')
    def test_empty_boundary_is_deny_and_no_flows_unassessed(self):
        self.side['flows'][0]['allowed_site_pairs']=[];self.assertEqual(self.case(self.run_model())['boundary_status'],'outside_declared_pairs')
        self.side['flows']=[];self.assertEqual(self.case(self.run_model())['boundary_status'],'not_evaluated_no_declared_flows')
    def test_unknown_and_infeasible_no_flow_claim(self):
        for limit in [1,20000]:
            d=json.loads(self.raw);d['candidate_limit']=limit
            if limit>1:d['plans'][0]['nodes']=d['plans'][0]['nodes'][:1]
            raw=core.canonical(d);self.side['input_sha256']=hashlib.sha256(raw).hexdigest()
            if limit>1:self.side['nodes']=[n for n in self.side['nodes'] if n['plan']!='local' or n['node']=='a']
            r=self.run_model(raw=raw);c=self.case(r,'local');self.assertIsNone(c['flows']);self.assertIsNone(c['modeled_cost']);self.assertIsNone(c['cross_site_cost'])
    def test_binding_exact_bytes(self):
        with self.assertRaises(core.Invalid):self.run_model(raw=self.raw+b' ')
    def test_repeated_node_ids_across_plans_preserved(self):
        self.assertEqual(len(self.run_model()['plans']),3)
        self.side['nodes'].append(copy.deepcopy(self.side['nodes'][0]))
        with self.assertRaises(core.Invalid):self.run_model()
    def test_duplicate_rates_and_pairs(self):
        for key in ['rates','pairs']:
            s=copy.deepcopy(self.side)
            if key=='rates':s['egress_rates'].append(copy.deepcopy(s['egress_rates'][0]))
            else:s['flows'][0]['allowed_site_pairs'].append(['office','office'])
            with self.assertRaises(core.Invalid):self.run_model(s)
    def test_boolean_fraction_float_and_unicode_rejected(self):
        for bad in [True,0,-1,10**15+1,0.1]:
            s=copy.deepcopy(self.side);s['duration_hours']['denominator']=bad
            with self.assertRaises(core.Invalid):self.run_model(s)
        s=copy.deepcopy(self.side);s['flows'][0]['bytes']=True
        with self.assertRaises(core.Invalid):self.run_model(s)
        s=copy.deepcopy(self.side);s['assumptions']='\ud800'
        with self.assertRaises((core.Invalid,UnicodeError)):self.run_model(s)
    def test_unknown_fields_and_missing_node(self):
        for s in [dict(self.side,extra=1),{**self.side,'nodes':self.side['nodes'][:-1]}]:
            with self.assertRaises(core.Invalid):self.run_model(s)
    def test_directional_rates_no_reverse_inference(self):
        f=self.side['flows'][0];f['from'],f['to']=f['to'],f['from'];self.assertIsNone(self.case(self.run_model(),subject='b')['cross_site_cost']['modeled_amount'])
    def test_safe_text_architecture(self):
        self.side['assumptions']='literal\ncommand <script> & 😀';text=context.architecture(self.run_model()).decode();self.assertIn('literal\\ncommand',text);self.assertIn('😀',text)
    def test_bundle_and_tamper_every_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a=p/'input';b=p/'context';a.write_bytes(self.raw);b.write_bytes(core.canonical(self.side));out=p/'out';context.build(a,b,out);context.verify(out)
            for name in context.NAMES:
                original=(out/name).read_bytes();(out/name).write_bytes(original+b' ')
                with self.assertRaises(core.Invalid):context.verify(out)
                (out/name).write_bytes(original)
            (out/'extra').write_text('x')
            with self.assertRaises(core.Invalid):context.verify(out)
    def test_output_preflight_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with patch.object(core,'OUTPUT_LIMIT',1):
                with self.assertRaises(core.Invalid):context.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
            self.assertFalse(out.exists());context.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
            with self.assertRaises(FileExistsError):context.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
    def test_size_special_and_symlink_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);big=p/'big';big.write_bytes(b' '*(core.INPUT_LIMIT+1))
            with self.assertRaises(core.Invalid):core.read(big)
            if hasattr(os,'symlink'):
                sy=p/'sy';sy.symlink_to(big)
                with self.assertRaises(core.Invalid):core.read(sy)
            if hasattr(os,'mkfifo'):
                fifo=p/'fifo';os.mkfifo(fifo)
                with self.assertRaises(core.Invalid):core.read(fifo)
    def test_maximum_valid_rational_products_and_sums(self):
        self.side['duration_hours']={'numerator':10**15,'denominator':1}
        for n in self.side['nodes']:n['hourly_rate']={'numerator':10**15,'denominator':1}
        self.assertEqual(self.case(self.run_model())['modeled_cost']['modeled_amount'],{'numerator':3*10**30,'denominator':1})
        self.side['duration_hours']={'numerator':1,'denominator':10**15}
        for n in self.side['nodes']:n['hourly_rate']={'numerator':1,'denominator':10**15}
        self.assertEqual(self.case(self.run_model())['modeled_cost']['modeled_amount'],{'numerator':3,'denominator':10**30})
    def test_empty_region_boundary_denies_unknown_region(self):
        self.side['sites'][0]['region']=None
        self.side['flows'][0]['allowed_region_pairs']=[]
        self.assertEqual(self.case(self.run_model())['flows'][0]['region_boundary'],'outside_declared_pairs')
    def test_unicode_valid_and_byte_preservation(self):
        self.side['assumptions']='人工声明，非现价 😀'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a=p/'input';b=p/'side';a.write_bytes(self.raw);side=core.canonical(self.side);b.write_bytes(side);out=p/'out';context.build(a,b,out)
            self.assertEqual((out/'input.json').read_bytes(),self.raw);self.assertEqual((out/'context.json').read_bytes(),side);context.verify(out)
    def test_cli_real_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'bundle';env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
            args=[sys.executable,'-m','placement_desk.context']
            a=subprocess.run(args+['analyze',str(ROOT/'examples/context-deployment.json'),str(ROOT/'examples/context-assumptions.json'),'--out',str(out)],cwd=ROOT,env=env,capture_output=True)
            self.assertEqual(a.returncode,0,a.stderr);v=subprocess.run(args+['verify',str(out)],cwd=ROOT,env=env,capture_output=True);self.assertEqual(v.returncode,0,v.stderr)
            (out/'architecture.txt').write_text('tampered');v=subprocess.run(args+['verify',str(out)],cwd=ROOT,env=env,capture_output=True);self.assertEqual(v.returncode,2)
if __name__=='__main__':unittest.main()
