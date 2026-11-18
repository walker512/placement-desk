"""Static, offline architecture diagrams of declared placement witnesses."""
import argparse
import html
import json
import os
from pathlib import Path
import sys
from . import core, context

NAMES = context.NAMES | {'index.html'}
SCOPE = ('Diagram of a deterministic declared placement witness, not a discovered network, '
         'runtime routing, optimal deployment, compliance conclusion or measured performance.')


def esc(value):
    return html.escape(str(value), quote=True)


def short(value):
    text=str(value)
    return esc(text if len(text)<=34 else text[:31]+'…')


def quantity(value):
    if value is None:
        return 'UNKNOWN (not zero)'
    return f"{value['numerator']}/{value['denominator']}"


def diagram(nodes, placements, removed, flows, mappings, sites, prefix):
    ordered=sorted(nodes,key=lambda n:n['id'])
    height=170*len(ordered)+30
    positions={n['id']:(25,20+i*170) for i,n in enumerate(ordered)}
    parts=[f'<svg viewBox="0 0 950 {height}" role="img" aria-label="Declared nodes, replicas and directed flows"><defs><marker id="{prefix}-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#367b70"/></marker></defs>']
    # One path per directed node pair. Full individual flow details remain in the table.
    pairs={}
    for flow in flows or []:
        pairs.setdefault((flow['from']['node'],flow['to']['node']),[]).append(flow['id'])
    for i,((a,b),ids) in enumerate(sorted(pairs.items())):
        y1=positions[a][1]+55;y2=positions[b][1]+55
        x=610+(i%8)*35
        if a==b:
            path=f'M 525 {y1-15} C {x} {y1-65}, {x} {y1+65}, 525 {y1+15}'
        else:
            path=f'M 525 {y1} C {x} {y1}, {x} {y2}, 525 {y2}'
        parts+=[f'<path d="{path}" fill="none" stroke="#367b70" stroke-width="2" marker-end="url(#{prefix}-arrow)"><title>{esc(a)} → {esc(b)}: {esc(", ".join(ids))}</title></path>']
    for node in ordered:
        name=node['id'];x,y=positions[name];site=sites[mappings[name]['site']];lost=name in removed
        replicas=[f"{p['workload']}[{p['replica']}]" for p in placements if p['node']==name]
        border='stroke-dasharray="7 4"' if lost else ''
        fill='#f6e6e4' if lost else '#edf4f2'
        count=str(len(replicas)) if placements else 'NOT EVALUATED'
        parts += [f'<g><rect x="{x}" y="{y}" width="500" height="140" rx="10" fill="{fill}" stroke="#416b65" {border}/>',f'<text x="40" y="{y+25}" font-weight="bold">{short(name)}</text>',f'<text x="40" y="{y+46}" font-size="12">zone: {short(node["zone"])}</text>',f'<text x="40" y="{y+67}" font-size="12">site: {short(site["id"])} ({esc(site["kind"])})</text>',f'<text x="40" y="{y+88}" font-size="12">region: {short(site["region"])}</text>',f'<text x="40" y="{y+113}" font-size="12">{("REMOVED" if lost else "SURVIVING")} · assigned replicas: {count} (exact assignments below)</text>']
        parts += ['</g>']
    return ''.join(parts+['</svg>'])


def render(raw, side, placement, report):
    deployment,d=context.load(raw,side)
    sites={s['id']:s for s in d['sites']}
    plan_inputs={p['id']:p for p in deployment['plans']}
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;"><title>Placement Desk architecture review</title><style>body{font:16px/1.6 system-ui;max-width:1150px;margin:auto;padding:28px;color:#173b36;background:#f7faf8}h1{font-size:40px}section,details{background:white;border:1px solid #bdd0c9;padding:20px;margin:20px 0;border-radius:12px}summary{cursor:pointer;font-weight:700}summary:focus-visible,a:focus-visible{outline:3px solid #176c59}svg{width:100%;max-height:none}table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccd;padding:9px;text-align:left;overflow-wrap:anywhere}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}.warning{border-left:5px solid #ba6936;padding-left:15px}</style><h1>Placement is a witness.<br>Not a deployment promise.</h1><p>',esc(SCOPE),'</p><p class="warning">Each failure case independently repacks every replica. Nodes remain billed even when removed. Never sum mutually exclusive cases into one bill. Unknown is not zero. Boundary failure refers only to this witness, not all possible placements.</p><p>Currency: ',esc(report['currency']),' · Duration hours: ',esc(quantity(report['duration_hours'])),'</p><p>Human assumptions: ',esc(report['assumptions']),'</p><nav aria-label="Plan navigation">']
    for i,p in enumerate(report['plans']):parts += [f'<a href="#plan-{i}">{esc(p["id"])}</a> ']
    parts += ['</nav>']
    for i,(p,pp) in enumerate(zip(report['plans'],placement['plans'])):
        parts += [f'<section id="plan-{i}"><h2>{esc(p["id"])}</h2><p>All requested placement cases: {esc(pp["all_requested_cases"])}</p><p>Full-inventory modeled reservation: {esc(quantity(p["inventory_node_cost"]["modeled_amount"]))}; known subtotal: {esc(quantity(p["inventory_node_cost"]["known_subtotal"]))}</p>']
        mappings={n['node']:n for n in d['nodes'] if n['plan']==p['id']}
        parts+=['<h3>Full declared inventory</h3><p>Long diagram labels are abbreviated; exact identifiers and mappings are listed here.</p><div class="scroll"><table><tr><th>Node</th><th>Zone</th><th>Site / kind</th><th>Region</th></tr>']
        for node in sorted(plan_inputs[p['id']]['nodes'],key=lambda n:n['id']):
            site=sites[mappings[node['id']]['site']]
            parts+=['<tr><th>',esc(node['id']),'</th><td>',esc(node['zone']),'</td><td>',esc(site['id']),' / ',esc(site['kind']),'</td><td>',esc(site['region']),'</td></tr>']
        parts+=['</table></div>']
        for j,(c,pc) in enumerate(zip(p['cases'],pp['cases'])):
            label=c['mode']+':'+str(c['subject'])
            parts += [f'<details {"open" if j==0 else ""}><summary>{esc(label)} · {esc(c["placement_status"])}</summary><p>Removed nodes: {esc(", ".join(pc["removed_nodes"]) or "none")}</p><p>Boundary status: {esc(c["boundary_status"])}</p>']
            if c['flows'] is None:
                parts += ['<p class="warning">No placement witness. No flow, locality or combined-cost conclusion. Unknown search budget is not infeasibility.</p>']
            parts += [diagram(plan_inputs[p['id']]['nodes'],pc['placement'],pc['removed_nodes'],c['flows'],mappings,sites,f'p{i}-c{j}')]
            if c['flows'] is not None:
                parts += ['<h3>Directed flows for this witness</h3><p>Curves aggregate node pairs; the table is the exact direction and boundary record. Same-node curves are self-loops. This is not physical topology or measured connectivity.</p><div class="scroll"><table><tr><th>Flow</th><th>From</th><th>To</th><th>Bytes</th><th>Boundary</th><th>Modeled charge</th></tr>']
                for f in c['flows']:
                    endpoint=lambda e:f"{e['workload']}[{e['replica']}] @ {e['node']} / {e['site']} / region {e['region']}"
                    parts += ['<tr><th>',esc(f['id']),'</th><td>',esc(endpoint(f['from'])),'</td><td>',esc(endpoint(f['to'])),'</td><td>',esc('UNKNOWN' if f['declared_bytes'] is None else f['declared_bytes']),'</td><td>',esc(f['boundary_status']),'<br>site: ',esc(f['site_boundary']),'<br>region: ',esc(f['region_boundary']),'</td><td>',esc(quantity(f['cross_site_amount'])),'<br>',esc(f['cost_status']),'</td></tr>']
                if not c['flows']:parts+=['<tr><td colspan="6">No declared flows. This does not prove no traffic exists.</td></tr>']
                parts += ['</table></div><p>Modeled combined amount: ',esc(quantity(c['modeled_cost']['modeled_amount'])),'; known subtotal: ',esc(quantity(c['modeled_cost']['known_subtotal'])),'; unknown components: ',esc(', '.join(c['modeled_cost']['unknown_items']) or 'none'),'</p>']
            parts += ['<h3>Exact replica assignments and remaining declared resources</h3><pre>',esc(core.canonical({'placement':pc['placement'],'remaining_capacity':pc['remaining_capacity']}).decode()),'</pre></details>']
        parts += ['</section>']
    parts += ['<p>Source hashes: ',esc(report['input_sha256']),' / ',esc(report['context_sha256']),'</p><p>Recomputation verifies consistency, not origin. Confirm actual capacity, prices, billing, routing, data classification, allowed destinations and recovery/latency with humans and real systems. No network requests or deployments.</p></html>']
    return ''.join(parts).encode('utf8')


def generated(raw,side):
    files,report=context.generated(raw,side)
    placement=core.parse(files['placement.json'])
    page=render(raw,side,placement,report)
    if len(page)>core.OUTPUT_LIMIT:raise core.Invalid('Diagram output exceeds bound.')
    files['index.html']=page
    return files,report


def build(source,sidecar,out):
    files,report=generated(core.read(source),core.read(sidecar))
    root=Path(out);root.mkdir(mode=0o700,exist_ok=False)
    for name,data in files.items():
        fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data)
    return report


def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!=NAMES:raise core.Invalid('Unexpected visual bundle.')
    files,report=generated(core.read(root/'input.json'),core.read(root/'context.json'))
    if any(core.read(root/n,core.OUTPUT_LIMIT)!=v for n,v in files.items()):raise core.Invalid('Visual bundle differs from recomputation.')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('analyze');p.add_argument('input');p.add_argument('context');p.add_argument('--out',required=True)
    p=sub.add_parser('verify');p.add_argument('bundle');args=parser.parse_args()
    try:
        r=build(args.input,args.context,args.out) if args.command=='analyze' else verify(args.bundle)
        print(json.dumps({'consistent':True,'plans':[p['id'] for p in r['plans']],'scope':SCOPE}));return 0
    except (core.Invalid,OSError,ValueError,TypeError,RecursionError):
        print('Invalid bounded input, context or visual bundle. Contents are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
