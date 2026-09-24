"""Lightweight validation I/O and input identity; no scientific runtime imports.
Allows finalize to invalidate old status even when the validator cannot import.
"""
import csv,hashlib,json
from pathlib import Path
from config import RESULTS,Q2_RESULTS,CODE,REPO

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig') as f: return list(csv.DictReader(f))
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def table(path,rows,fields):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
def identity(plan,transport):
    paths=[plan,transport,RESULTS/'q3_terrain_cache.npz',CODE/'scenario.json']
    paths+=sorted((REPO/'Q2/code').glob('*.py'))+sorted(CODE.glob('*.py'))
    paths+=[Q2_RESULTS/n for n in ('q2_inputs.json','q2_scenario.json','q2_trips.csv')]
    return {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
