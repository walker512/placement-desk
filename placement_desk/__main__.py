import argparse,json,sys
from .core import Invalid,build,verify

def main():
    p=argparse.ArgumentParser(description='Compare declared placement plans without deploying anything.')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('analyze');a.add_argument('input');a.add_argument('--out',required=True);a.add_argument('--require-plan')
    v=sub.add_parser('verify');v.add_argument('bundle');v.add_argument('--require-plan')
    args=p.parse_args()
    try:
        r=build(args.input,args.out) if args.command=='analyze' else verify(args.bundle)
        plans={x['id']:x['all_requested_cases'] for x in r['plans']}
        if args.require_plan is not None and args.require_plan not in plans:raise Invalid('Unknown required plan.')
        print(json.dumps({'consistent':True,'plans':plans,'scope':r['scope']}))
        return 3 if args.require_plan is not None and plans[args.require_plan]!='model_feasible' else 0
    except (Invalid,OSError,ValueError,RecursionError):
        print('Cannot process bounded input or bundle: invalid fields, inconsistent evidence or filesystem failure. Input contents are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
