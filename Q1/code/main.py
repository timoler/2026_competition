"""Q1 reproducible exact grouped-count DP; numpy, Pillow, openpyxl, pyproj required.
Usage: python solve_q1.py '/path/to/D题'
Horizontal coordinates use WGS84 / UTM Zone 49N (EPSG:32649), shared with Q2/Q3.
Energy decompositions remain declared modeling assumptions.
"""
from pathlib import Path
import sys, math, csv, json, hashlib, itertools
from functools import lru_cache
import numpy as np
from PIL import Image
import openpyxl
from pyproj import Transformer

SRC = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2] / 'data/raw/D题'
OUT = Path(__file__).resolve().parents[1] / 'results'
OUT.mkdir(exist_ok=True)
BASE = SRC/'数据/无人机应急物资运输基础数据'
def rows(name, sheet=0):
    w=openpyxl.load_workbook(BASE/name,data_only=True)
    return list((w.worksheets[sheet] if isinstance(sheet,int) else w[sheet]).values)
def save(name, data):
    if not data: return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]),lineterminator='\n');w.writeheader();w.writerows(data)

nr=rows('调度中心与服务区.xlsx')
nodes={r[0]:dict(lon=r[2],lat=r[3],z=r[4]) for r in [nr[2]]+nr[6:] if r[0]}
assert len(nodes)==16
mr=rows('运输无人机数据.xlsx')
keys=['id','name','mass','Q','V','speed','L0','LF','battery','reserve_pct','prep','load','handover','perbox','up','down','eta','downeta']
models={r[0]:dict(zip(keys,r)) for r in mr[2:5]}
boxes=[dict(zip(['id','site','kind','mass','volume','first','deadline','expected','priority'],r)) for r in rows('物资需求与配送时限.xlsx',1)[1:] if r[0]]
assert len(boxes)==80 and len({b['id'] for b in boxes})==80

# Horizontal coordinates: WGS84 / UTM Zone 49N (EPSG:32649), same convention as Q2/Q3.
utm = Transformer.from_crs(4326, 32649, always_xy=True)
for key, n in nodes.items():
    n['x_m'], n['y_m'] = utm.transform(n['lon'], n['lat'])
    n['work_z'] = n['z'] + (0 if key == 'O01' else 30)
im=Image.open(next(SRC.rglob('*.tif')));dem=np.asarray(im);tag=im.tag_v2
sx,sy,_=tag[33550]; _,_,_,lon0,lat0,_=tag[33922]
assert tag[34735][-1]==4326 and 1025 in tag[34735]
# GeoKey 1025=2 is RasterPixelIsPoint: tiepoint is center, outer corner shifted 1/2 pixel.
geokeys={tag[34735][i]:tag[34735][i+3] for i in range(4,len(tag[34735]),4)}
assert geokeys[1025]==2
def grid(n): return ((n['lon']-lon0)/sx+.5,(lat0-n['lat'])/sy+.5)
def crossed_cells(p,q):
    x,y=p;dx=q[0]-x;dy=q[1]-y; ts=[0.,1.]
    for start,d in [(x,dx),(y,dy)]:
        if abs(d)>1e-14:
            lo,hi=sorted([start,start+d])
            ts.extend((k-start)/d for k in range(math.ceil(lo),math.floor(hi)+1) if 0<(k-start)/d<1)
    ts=sorted(set(ts));cells=set()
    for t in ts+[(u+v)/2 for u,v in zip(ts,ts[1:])]:
        xx=x+t*dx; yy=y+t*dy
        cc={math.floor(xx)};rr={math.floor(yy)}
        if abs(xx-round(xx))<1e-9: cc.update([round(xx)-1,round(xx)])
        if abs(yy-round(yy))<1e-9: rr.update([round(yy)-1,round(yy)])
        cells.update((r,c) for r in rr for c in cc)
    for r,c in cells: assert 0<=r<dem.shape[0] and 0<=c<dem.shape[1]
    return cells
legs={}
for i,j in itertools.permutations(nodes,2):
    ni,nj=nodes[i],nodes[j]; cells=crossed_cells(grid(ni),grid(nj)); zs=[float(dem[r,c]) for r,c in cells]
    assert min(zs)>-1000 and all(math.isfinite(z) for z in zs)
    H=max(zs)+50
    legs[i,j]=dict(start=i,end=j,distance_m=math.hypot(nj['x_m']-ni['x_m'],nj['y_m']-ni['y_m']),terrain_max_m=max(zs),cruise_m=H,up_m=H-ni['work_z'],down_m=H-nj['work_z'],cells=len(cells))
    assert legs[i,j]['up_m']>=0 and legs[i,j]['down_m']>=0
save('q1_legs.csv',list(legs.values()))
save('q1_nodes.csv',[dict(id=k,**v) for k,v in nodes.items()])
def leg_perf(i,j,k,q):
    g=models[k];l=legs[i,j]
    assert -1e-9<=q<=g['Q']+1e-9
    L=g['L0']-(g['L0']-g['LF'])*(q/g['Q'])**1.5
    eh=g['battery']*l['distance_m']/L
    eu=(g['mass']+q)*9.80665*l['up_m']/(g['eta']*3.6e6)
    t=l['up_m']/g['up']+l['distance_m']/g['speed']+l['down_m']/g['down']
    return t,eh+eu
def trip(site,k,q,count):
    g=models[k]; t1,e1=leg_perf('O01',site,k,q);t2,e2=leg_perf(site,'O01',k,0)
    prep=g['prep']+g['load']*count;handover=g['handover']+g['perbox']*count
    return dict(flight_s=t1+t2,preparation_s=prep,handover_s=handover,operation_s=t1+t2+prep+handover,energy_kwh=e1+e2,soc_pct=100*(1-(e1+e2)/g['battery']))
def capacity(site,k,r):
    g=models[k];limit=(1-r)*g['battery']
    if trip(site,k,0,0)['energy_kwh']>limit: return None
    if trip(site,k,g['Q'],0)['energy_kwh']<=limit: return float(g['Q'])
    lo,hi=0.,float(g['Q'])
    for _ in range(65):
        mid=(lo+hi)/2
        if trip(site,k,mid,0)['energy_kwh']<=limit:lo=mid
        else:hi=mid
    return lo
sites=sorted(set(b['site'] for b in boxes))
caps=[]
for r in [.1,.15,.2,.25,.3]:
    for site,k in itertools.product(sites,models):
        c=capacity(site,k,r);caps.append(dict(reserve=r,site=site,model=k,max_payload_kg=c,reachable=c is not None))
save('q1_max_payload_sensitivity.csv',caps)

def solve_site(site,r,order):
    bs=[b for b in boxes if b['site']==site];groups={}
    for b in bs:groups.setdefault((b['mass'],b['volume']),[]).append(b)
    types=list(groups);target=tuple(len(groups[t]) for t in types);patterns=[]
    for counts in itertools.product(*(range(n+1) for n in target)):
        if not any(counts):continue
        mass=sum(c*t[0] for c,t in zip(counts,types));vol=sum(c*t[1] for c,t in zip(counts,types))
        for k,g in models.items():
            if mass>g['Q']+1e-9 or vol>g['V']+1e-12:continue
            p=trip(site,k,mass,sum(counts))
            if p['energy_kwh']>(1-r)*g['battery']+1e-10:continue
            patterns.append((counts,k,mass,vol,p))
    @lru_cache(None)
    def dp(state):
        if not any(state):return (0,0.,0.),None
        first=next(i for i,v in enumerate(state) if v)
        best=None;chosen=None
        for ix,(counts,k,m,v,p) in enumerate(patterns):
            if not counts[first] or any(c>s for c,s in zip(counts,state)):continue
            sub=tuple(s-c for c,s in zip(counts,state));base,_=dp(sub)
            if base is None:continue
            value=(base[0]+1,base[1]+p['energy_kwh'],base[2]+p['operation_s'])
            key=tuple(value[i] for i in order)
            if best is None or key<tuple(best[i] for i in order):best,chosen=value,ix
        return best,chosen
    score,_=dp(target)
    if score is None:return None,[]
    state=target;used=[0]*len(types);result=[]
    while any(state):
        _,ix=dp(state);counts,k,m,v,p=patterns[ix];ids=[]
        for a,c in enumerate(counts):
            ids += [b['id'] for b in groups[types[a]][used[a]:used[a]+c]];used[a]+=c
        result.append(dict(site=site,model=k,box_ids=';'.join(ids),mass_kg=m,volume_m3=v,**p))
        state=tuple(s-c for s,c in zip(state,counts))
    return score,result

summary=[];baseline=[]
for r,order,label in [(r,(2,0,1),'时间_架次_能耗') for r in [.1,.15,.2,.25,.3]]+[(.2,(0,1,2),'架次_能耗_时间'),(.2,(0,2,1),'架次_时间_能耗'),(.2,(1,0,2),'能耗_架次_时间')]:
    result=[];bad=[]
    for site in sites:
        score,res=solve_site(site,r,order)
        if score is None:bad.append(site)
        result.extend(res)
    for idx,row in enumerate(result,1):row['trip_id']=f'Q1-{idx:03d}'
    if not bad:
        assigned=[i for x in result for i in x['box_ids'].split(';')]
        assert sorted(assigned)==sorted(b['id'] for b in boxes)
        lookup={b['id']:b for b in boxes}
        for row in result:
            cargo=[lookup[i] for i in row['box_ids'].split(';')];g=models[row['model']]
            assert all(b['site']==row['site'] for b in cargo)
            assert sum(b['mass'] for b in cargo)<=g['Q']+1e-9
            assert sum(b['volume'] for b in cargo)<=g['V']+1e-12
            assert row['soc_pct']>=100*r-1e-7
        if label=='时间_架次_能耗':
            save(f'q1_batches_reserve_{int(r*100)}.csv',result)
        else:
            save(f'q1_batches_priority_{label}.csv',result)
    summary.append(dict(reserve=r,priority=label,feasible=not bad,infeasible_sites=';'.join(bad),trips=len(result) if not bad else None,energy_kwh=sum(x['energy_kwh'] for x in result) if not bad else None,operation_s=sum(x['operation_s'] for x in result) if not bad else None,flight_s=sum(x['flight_s'] for x in result) if not bad else None))
    if r==.2 and label=='时间_架次_能耗':baseline=result
save('q1_model_comparison.csv',summary)
save('q1_batches_default.csv',baseline)
save('q1_submission_rows.csv',[{'架次编号':x['trip_id'],'服务区编号':x['site'],'机型编号':x['model'],'货箱编号列表':x['box_ids'],'总质量（kg）':x['mass_kg'],'总体积（m³）':x['volume_m3'],'往返时间（s）':x['operation_s'],'架次能耗（kWh）':x['energy_kwh'],'返航SOC（%）':x['soc_pct']} for x in baseline])
manifest=[dict(file=str(f.relative_to(SRC)),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(SRC.rglob('*')) if f.is_file()]
(OUT/'q1_source_hashes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('Baseline models:',{k:sum(x['model']==k for x in baseline) for k in models})
