"""Independently reload the selected CSV and verify every 1-second Q2 sample."""
import argparse
import csv
import json
from pathlib import Path
from strict_feasibility import validate, dump
from config import RESULTS

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--schedule',type=Path,default=RESULTS/'q3_relay_schedule.csv')
    parser.add_argument('--max-relays',type=int,default=None)
    parser.add_argument('--spacing',type=float,default=10)
    args=parser.parse_args()
    limit=args.max_relays
    if limit is None:
        summary=json.loads((RESULTS/'q3_schedule_summary.json').read_text(encoding='utf-8'))
        limit=int(summary.get('n_relays_used',2))
    with args.schedule.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    result,_,_=validate(rows,args.spacing,limit)
    result['resource_scenario']='official 2-relay fleet' if limit<=2 else 'augmented 3-relay fleet'
    dump('q3_validation.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
if __name__=='__main__':main()
