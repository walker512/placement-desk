import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
from placement_desk import core,context,visualize
ROOT=Path(__file__).resolve().parents[1]
def inputs():return (ROOT/'examples/context-deployment.json').read_bytes(),(ROOT/'examples/context-assumptions.json').read_bytes()
def changed(raw,side,mutate):
 a=json.loads(raw);b=json.loads(side);mutate(a,b);raw=core.canonical(a);b['input_sha256']=hashlib.sha256(raw).hexdigest();return raw,core.canonical(b)
class Markup(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.tags=[];self.attrs=[]
 def handle_starttag(self,t,attrs):
  self.tags.append(t);self.attrs.extend(attrs)
  for k,v in attrs:
   if k=='id':self.ids.append(v)
class VisualTests(unittest.TestCase):
 def test_existing_outputs_exact(self):
  raw,side=inputs();old,r=context.generated(raw,side);new,r2=visualize.generated(raw,side);self.assertEqual(r,r2)
  for n,v in old.items():self.assertEqual(new[n],v)
  self.assertEqual(set(new),context.NAMES|{'index.html'})
 def test_diagram_per_case_unique_ids_and_no_external_resources(self):
  files,r=visualize.generated(*inputs());page=files['index.html'].decode();p=Markup();p.feed(page)
  count=sum(len(plan['cases']) for plan in r['plans']);self.assertEqual(p.tags.count('svg'),count);self.assertEqual(p.tags.count('details'),count);self.assertEqual(len(p.ids),len(set(p.ids)));self.assertNotIn('script',p.tags)
  self.assertFalse(any(k.startswith('on') or k in ('src','srcset') for k,v in p.attrs));self.assertTrue(all(v.startswith('#') for k,v in p.attrs if k=='href'))
 def test_every_flow_and_unknown_cost_visible(self):
  files,r=visualize.generated(*inputs());page=files['index.html'].decode();self.assertIn('UNKNOWN (not zero)',page)
  for p in r['plans']:
   for c in p['cases']:
    for f in c['flows'] or []:
     self.assertIn(f['id'],page);self.assertIn(f['boundary_status'],page)
 def test_no_flows_not_no_traffic(self):
  raw,side=changed(*inputs(),lambda a,b:b.update(flows=[]));page=visualize.generated(raw,side)[0]['index.html'];self.assertIn(b'No declared flows. This does not prove no traffic exists.',page)
 def test_unknown_case_no_false_assignment(self):
  raw,side=changed(*inputs(),lambda a,b:a.update(candidate_limit=1));page=visualize.generated(raw,side)[0]['index.html'];self.assertIn(b'unknown_search_limit',page);self.assertIn(b'assigned replicas: NOT EVALUATED',page);self.assertIn(b'No placement witness.',page)
 def test_removed_nodes_and_case_semantics(self):
  files,r=visualize.generated(*inputs());page=files['index.html'];self.assertIn(b'REMOVED',page);self.assertIn(b'Nodes remain billed even when removed.',page);self.assertIn(b'independently repacks every replica',page)
 def test_self_loop_and_parallel_pair_aggregation(self):
  _,r=context.analyze(*inputs());p=r['plans'][0];c=next(c for c in p['cases'] if c['flows']);f=c['flows'][0];node=f['from']['node'];site=f['from']['site'];nodes=[{'id':node,'zone':'z'}];mapping={node:{'site':site}};sites={site:{'id':site,'kind':'local','region':None}}
  f=dict(f,to=f['from']);g=dict(f,id='parallel');page=visualize.diagram(nodes,[dict(workload='worker',replica=0,node=node)],[],[f,g],mapping,sites,'p0')
  self.assertEqual(page.count('marker-end='),1);self.assertIn('parallel',page)
 def test_untrusted_assumptions_are_text(self):
  raw,side=changed(*inputs(),lambda a,b:b.update(assumptions='<script>alert(1)</script><img src=x>'))
  page=visualize.generated(raw,side)[0]['index.html'];self.assertNotIn(b'<script>',page);self.assertIn(b'&lt;script&gt;',page);self.assertNotIn(b'<img',page)
 def test_size_preflight_before_output(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out'
   with patch.object(visualize,'render',return_value=b'x'*(core.OUTPUT_LIMIT+1)):
    with self.assertRaises(core.Invalid):visualize.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
   self.assertFalse(out.exists())
 def test_roundtrip_every_member_tampering(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out';r=visualize.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out);self.assertEqual(visualize.verify(out),r)
   for n in visualize.NAMES:
    p=out/n;old=p.read_bytes();p.write_bytes(old+b'X')
    with self.assertRaises(core.Invalid):visualize.verify(out)
    p.write_bytes(old)
 def test_existing_output_and_extra_member(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out';out.mkdir();(out/'keep').write_bytes(b'KEEP')
   with self.assertRaises(FileExistsError):visualize.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
   self.assertEqual((out/'keep').read_bytes(),b'KEEP')
   with self.assertRaises(core.Invalid):visualize.verify(out)
 @unittest.skipUnless(os.name=='posix','POSIX modes only')
 def test_creation_private_and_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out';old=os.umask(0o022)
   try:visualize.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
   finally:os.umask(old)
   self.assertEqual(out.stat().st_mode&0o777,0o700)
   for p in out.iterdir():self.assertEqual(p.stat().st_mode&0o777,0o600)
   link=Path(t)/'link';link.symlink_to(out,target_is_directory=True)
   with self.assertRaises(core.Invalid):visualize.verify(link)
 def test_real_cli_and_fixed_errors(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out'
   for args in [('analyze',str(ROOT/'examples/context-deployment.json'),str(ROOT/'examples/context-assumptions.json'),'--out',str(out)),('verify',str(out))]:
    p=subprocess.run([sys.executable,'-m','placement_desk.visualize',*args],capture_output=True);self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(json.loads(p.stdout)['consistent'])
   (out/'index.html').write_text('PRIVATE')
   p=subprocess.run([sys.executable,'-m','placement_desk.visualize','verify',str(out)],capture_output=True);self.assertEqual(p.returncode,2);self.assertNotIn(b'Traceback',p.stderr);self.assertNotIn(b'PRIVATE',p.stderr)
 def test_partial_failure_is_not_accepted(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'out';original=os.open;n=0
   def fail(path,*args,**kw):
    nonlocal n
    if Path(path).parent==out:
     n+=1
     if n==2:raise OSError('failure')
    return original(path,*args,**kw)
   with patch.object(visualize.os,'open',fail):
    with self.assertRaises(OSError):visualize.build(ROOT/'examples/context-deployment.json',ROOT/'examples/context-assumptions.json',out)
   with self.assertRaises(core.Invalid):visualize.verify(out)
