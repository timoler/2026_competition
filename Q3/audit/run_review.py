"""Reproduce this local audit without optimization; preserve logs and exit codes."""
import argparse,csv,hashlib,json,os,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
AUDIT=ROOT/'Q3/audit'; RESULTS=ROOT/'Q3/results'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(); p.add_argument('--source-root',type=Path,required=True); p.add_argument('--dem',type=Path,required=True)
    a=p.parse_args(); commands=[]; env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    def run(label,args,expected):
        start=datetime.now(timezone.utc).isoformat()
        r=subprocess.run([sys.executable,'-B',*map(str,args)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log=AUDIT/'logs'/f'{label}.log'; log.write_bytes(r.stdout)
        commands.append(dict(label=label,command=r.args,exit_code=r.returncode,expected_exit=expected,started_utc=start,
            finished_utc=datetime.now(timezone.utc).isoformat(),log=str(log.relative_to(ROOT))))
        (AUDIT/'commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(label,'exit',r.returncode,flush=True)
        if r.returncode!=expected: raise RuntimeError(f'{label}: unexpected exit {r.returncode}; see {log}')
    run('q1',['Q1/code/verify.py',a.source_root],0)
    run('q2',['-c',"import sys; sys.path.insert(0,'Q2/code'); from validate import validate; validate('Q2/results',save=False)"],0)
    run('q2_independent',['Q2/code/independent_audit.py','--dem',a.dem,'--skip-improve-replay'],0)
    transport_before=digest(RESULTS/'q3_transport_schedule.csv')
    run('build_transport',['Q3/code/build_official_transport.py'],0)
    assert digest(RESULTS/'q3_transport_schedule.csv')==transport_before,'Transport reconstruction mismatch'
    run('q3_finalize',['Q3/code/finalize_e4_q3.py'],1)
    run('failure_tests',['Q3/code/test_finalize_e4_q3.py'],0)
    with tempfile.TemporaryDirectory(prefix='q3-reproduce-') as tmp:
        out=Path(tmp)
        run('q3_independent_reproduction',['Q3/code/validate_two_relay_experiment.py','--output',out],1)
        same={}
        for item in out.iterdir():
            current=RESULTS/item.name
            if item.suffix=='.json':
                x=json.loads(item.read_text(encoding='utf-8')); y=json.loads(current.read_text(encoding='utf-8'))
                x.pop('provenance',None); y.pop('provenance',None); same[item.name]=x==y
            else: same[item.name]=item.read_bytes()==current.read_bytes()
        report=dict(transport_regenerated_identically=True,comparison=same,all_equal=all(same.values()),
            note='Fresh direct independent run vs finalize subprocess; only run provenance excluded from JSON comparison.')
        (AUDIT/'reproduction.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        assert all(same.values()),same
    # Bind the cropped Q3 terrain cache to the original DEM attachment.
    sys.path.insert(0,str(ROOT/'Q3/code'))
    from terrain import Terrain
    import numpy as np
    full=Terrain.load_mat(a.dem); crop=Terrain.load_npz(RESULTS/'q3_terrain_cache.npz')
    col=round((crop.west-full.west)/full.dx); row=round((crop.north-full.north)/full.dy)
    ok=crop.dx==full.dx and crop.dy==full.dy and np.array_equal(crop.z,full.z[row:row+crop.nr,col:col+crop.nc])
    source=dict(dem=str(a.dem),dem_sha256=digest(a.dem),cache_sha256=digest(RESULTS/'q3_terrain_cache.npz'),
                cache_exact_native_subset=bool(ok),row_offset=row,column_offset=col)
    (AUDIT/'terrain_source_check.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert ok,source
    print('Reproduction and terrain source check passed',flush=True)
if __name__=='__main__': main()
