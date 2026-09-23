"""Strict 1-second Q3 search and independent schedule verification.

Fixed Q2 inputs; one O01-hover-O01 sortie per relay. Exhaustive pairs on
original candidates plus coordinate refinement. Three relays are an explicitly
augmented-resource scenario. No global infeasibility claim for continuous space.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np
CODE=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE))
from relay import RelayProblem
from check_core import independent_los_occluded, independent_link_budget, link_ok, _dist3
from config import RESULTS, Q2_RESULTS

def dump(name,obj):
    (RESULTS/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def table(name,rows,fields=None):
    with (RESULTS/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def hashes():
    return {str(p.relative_to(Q2_RESULTS.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Q2_RESULTS.parent.rglob('*')) if p.is_file() and '__pycache__' not in str(p)}

class Engine:
    def __init__(self,spacing=10):
        self.rp=RelayProblem();self.spacing=spacing
        self.b=independent_link_budget(self.rp.sc)
        self.k=self.rp.sc['official_relay'];self.meta=[];pts=[]
        for tid,tr in self.rp.tj.trips().items():
            t=float(tr['takeoff_s'])
            while t<float(tr['return_s']):
                s=self.rp.tj.position(tid,t)
                if s['phase']!='finished':
                    self.meta.append((tid,t,tr['drone_id']));pts.append((s['x'],s['y'],s['altitude_m']))
                t+=1
        self.pts=np.array(pts);self.times=np.array([r[1] for r in self.meta])
        direct=self.links(self.rp.g01,self.pts,self.b[2])
        self.di=np.where(~direct)[0];self.dp=self.pts[self.di];self.dt=self.times[self.di]
        self.unique,self.inv=np.unique(self.dp,axis=0,return_inverse=True)
        self.cache={}
        print('engine',spacing,'total',len(pts),'demand',len(self.di),'unique',len(self.unique),flush=True)
    def links(self,p,Q,th):
        d=np.linalg.norm(Q-np.array(p),axis=1)/1000
        fs=20*np.log10(np.maximum(d,1e-9))+self.b[0]
        ans=fs+self.b[1]<=th
        need=np.where((fs<=th)&~ans)[0]
        # Scalar canonical LOS, called only where terrain can change link status.
        for j in need:
            q=Q[j]
            ans[j]=not independent_los_occluded(self.rp.terr,*p,*q,spacing_m=self.spacing)
        return ans
    def candidate(self,p):
        p=tuple(round(float(v),6) for v in p)
        if p in self.cache:return self.cache[p]
        zero=np.zeros(len(self.di),bool)
        try:
            agl=p[2]-self.rp.terr.elevation(*p[:2])
            if not 0<=agl<=300.00001 or not self.links(p,np.array([self.rp.g01]),self.b[4])[0]:
                return zero,None
            flight=self.rp.relay_sortie(p,0)
            earliest=self.k['prep_s']+flight['flight_out_s']+self.k['link_build_s']
            cov=self.links(p,self.unique,self.b[3])[self.inv]&(self.dt>=earliest)
            idx=np.where(cov)[0]
            if not len(idx):return zero,None
            start=max(earliest,math.floor(float(self.dt[idx].min())*10)/10)
            end=math.ceil((float(self.dt[idx].max())+1)*10)/10
            # A single full coverage window must fit one energy component.
            energy=self.rp.relay_sortie(p,end-start)['energy_kwh']
            if energy>2.56:return zero,None
            lon,lat=self.rp.terr.inverse.transform(*p[:2])
            row=dict(hover_x_m=p[0],hover_y_m=p[1],hover_altitude_m=p[2],hover_lon=lon,hover_lat=lat,agl_m=agl,
                prep_start_s=round(start-self.k['link_build_s']-flight['flight_out_s']-self.k['prep_s'],6),
                takeoff_s=round(start-self.k['link_build_s']-flight['flight_out_s'],6),service_start_s=start,service_end_s=end,
                return_s=end+flight['flight_back_s'],flight_out_s=flight['flight_out_s'],flight_back_s=flight['flight_back_s'],
                service_duration_s=end-start,energy_kwh=energy,return_soc=1-energy/self.k['energy_kwh'])
            self.cache[p]=(cov,row);return cov,row
        except ValueError:return zero,None
    def schedule(self,points):
        rows=[]
        for i,p in enumerate(points):
            _,r=self.candidate(p)
            if r is None:continue
            rows.append(dict(sortie_id=f'S{i+1:02}',relay_id=f'R{i+1:02}',energy_component_id=f'ERC-{i+1:02}',**r))
        return rows

def validate(rows,spacing=10,max_relays=2):
    e=Engine(spacing);rp=e.rp;k=e.k;checks=[]
    def check(name,ok,detail=''):checks.append(dict(check=name,pass_=bool(ok),detail=detail))
    check('q2_trajectories_match',len(rp.tj.trips())==26)
    check('relay_count',len(set(r['relay_id'] for r in rows))<=max_relays)
    check('energy_components',len(set(r['energy_component_id'] for r in rows))==len(rows)<=k['energy_components']['count'])
    cover=np.ones(len(e.pts),bool);cover[e.di]=False
    modes=np.where(cover,'direct','outage').astype(object);assigned=np.full(len(cover),'',object)
    previous={}
    for r in sorted(rows,key=lambda r:float(r['prep_start_s'])):
        p=tuple(float(r[x]) for x in ['hover_x_m','hover_y_m','hover_altitude_m'])
        a,b=float(r['service_start_s']),float(r['service_end_s'])
        f=rp.relay_sortie(p,b-a);back=bool(e.links(p,np.array([rp.g01]),e.b[4])[0])
        check('relay_backhaul_'+r['relay_id'],back)
        check('relay_agl_'+r['relay_id'],0<=p[2]-rp.terr.elevation(*p[:2])<=300.00001)
        check('relay_energy_'+r['relay_id'],f['energy_kwh']<=2.56 and abs(f['energy_kwh']-float(r['energy_kwh']))<2e-6)
        check('relay_soc_'+r['relay_id'],abs(float(r['return_soc'])-(1-f['energy_kwh']/k['energy_kwh']))<1e-6)
        check('relay_sequence_'+r['relay_id'],float(r['prep_start_s'])>=-1e-6 and a<b and abs(float(r['takeoff_s'])-float(r['prep_start_s'])-k['prep_s'])<1e-5 and abs(a-float(r['takeoff_s'])-f['flight_out_s']-k['link_build_s'])<1e-5 and abs(float(r['return_s'])-b-f['flight_back_s'])<1e-5)
        check('relay_conflict_'+r['relay_id'],float(r['prep_start_s'])>=previous.get(r['relay_id'],-1e9))
        previous[r['relay_id']]=float(r['return_s'])+k['turnaround_s']
        ix=e.di[(e.dt>=a)&(e.dt<b)]
        if back:
            ok=e.links(p,e.pts[ix],e.b[3]);ix=ix[ok];assigned[ix[~cover[ix]]]=r['relay_id'];modes[ix]='relay';cover[ix]=True
    bad=np.where(~cover)[0];intervals=[]
    for ix in bad:
        tid,t,_=e.meta[ix]
        if intervals and intervals[-1]['trip_id']==tid and abs(intervals[-1]['last_sample_s']+1-t)<1e-6:
            intervals[-1]['last_sample_s']=t;intervals[-1]['uncovered_samples']+=1;intervals[-1]['end_exclusive_s']=t+1
        else:intervals.append(dict(trip_id=tid,start_s=t,last_sample_s=t,end_exclusive_s=t+1,uncovered_samples=1))
    check('continuous_connectivity',len(bad)==0)
    checks=[{'check':c['check'],'pass':c['pass_'],'detail':c['detail']} for c in checks]
    result=dict(status='PASS' if all(c['pass'] for c in checks) else 'FAIL',strict_feasible=all(c['pass'] for c in checks),
        time_step_s=1,los_spacing_m=spacing,total_samples=len(cover),uncovered_samples=len(bad),outage_sample_seconds=len(bad),
        coverage=float(cover.mean()),fine_coverage=float(cover.mean()),max_relays=max_relays,checks=checks,
        energy_kwh=sum(float(r['energy_kwh']) for r in rows),q2_sha256=hashes(),
        qualification='1-second per-trip grid, not a proof between time samples; summed drone-sample seconds, not wall-clock union')
    links=[dict(time_s=t,trip_id=tid,drone_id=drone,mode=modes[i],relay_id=assigned[i]) for i,(tid,t,drone) in enumerate(e.meta)]
    return result,intervals,links

def best_pair(cov):
    packed=np.packbits(cov,axis=1);lut=np.array([bin(i).count('1') for i in range(256)],dtype=np.uint8)
    best=(-1,0,0)
    for i in range(len(cov)):
        counts=lut[np.bitwise_or(packed[i],packed[i:])].sum(axis=1)
        j=int(np.argmax(counts));v=int(counts[j])
        if v>best[0]:best=(v,i,i+j)
    return best

def refine(e,points):
    points=list(points)
    for step in (150,50,15,5):
        for i in range(len(points)):
            other=np.zeros(len(e.di),bool)
            for j,p in enumerate(points):
                if i!=j:other|=e.candidate(p)[0]
            base=points[i];best=base;score=int((other|e.candidate(base)[0]).sum())
            for dx in (-step,0,step):
                for dy in (-step,0,step):
                    for agl in (300,275,250):
                        x,y=base[0]+dx,base[1]+dy
                        try:z=e.rp.terr.elevation(x,y)+agl
                        except ValueError:continue
                        p=(x,y,z);c,r=e.candidate(p);n=int((other|c).sum())
                        if r is not None and n>score:score=n;best=p
            points[i]=best
        n=int(np.logical_or.reduce([e.candidate(p)[0] for p in points]).sum())
        print('refine',len(points),'step',step,'uncovered',len(e.di)-n,flush=True)
        if n==len(e.di):break
    return points

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--validate',type=Path);parser.add_argument('--max-relays',type=int,default=2);parser.add_argument('--spacing',type=float,default=10)
    args=parser.parse_args()
    if args.validate:
        with args.validate.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        v,_,_=validate(rows,args.spacing,args.max_relays);print(json.dumps(v,ensure_ascii=False,indent=2));return
    before=hashes();e=Engine(10);rp=e.rp
    # Existing candidate lattice; recompute every retained candidate at 1s/10m.
    candidates=rp.candidates();cov=[];points=[];start=time.time()
    checkpoint=RESULTS/'q3_strict_search_cache.npz'
    fingerprint=hashlib.sha256(json.dumps({'q2':before,'scenario':rp.sc,'los_spacing_m':10},sort_keys=True).encode()+b''.join((CODE/f).read_bytes() for f in ['strict_feasibility.py','check_core.py','terrain.py','relay.py','communication.py','trajectory.py'])+(RESULTS/'q3_terrain_cache.npz').read_bytes()).hexdigest()
    saved=np.load(checkpoint) if checkpoint.exists() else None
    if saved is not None and 'fingerprint' in saved and str(saved['fingerprint'])==fingerprint:
        points=saved['points'].tolist();cov=list(saved['cov'])
    else:
        for i,p in enumerate(candidates):
            c,r=e.candidate(p)
            if r is not None:points.append(p);cov.append(c)
            if i%50==0:print('candidates',i,'/',len(candidates),'seconds',round(time.time()-start),flush=True)
        np.savez_compressed(checkpoint,points=points,cov=cov,fingerprint=fingerprint)
    cov=np.asarray(cov);print('pair search',len(points),flush=True)
    n,i,j=best_pair(cov);pair=refine(e,[points[i],points[j]])
    union=np.logical_or.reduce([e.candidate(p)[0] for p in pair]);scores=(cov&~union).sum(axis=1)
    triple=refine(e,pair+[points[int(np.argmax(scores))]])
    cases={}
    for count,ps in [(2,pair),(3,triple)]:
        rows=e.schedule(ps);table(f'q3_schedule_{count}relay.csv',rows)
        with (RESULTS/f'q3_schedule_{count}relay.csv').open(encoding='utf-8-sig') as f:
            reloaded=list(csv.DictReader(f))
        v,intervals,_=validate(reloaded,10,count)
        v.update(search_method='exhaustive original-lattice static pairs; coordinate refinement; third point best residual cover',
            search_scope='one stationary sortie per relay; original 300m lattice and local x/y/AGL refinement; does not prove continuous-space or multi-sortie infeasibility',
            original_candidate_count=len(candidates),evaluated_feasible_candidates=len(points),
            original_lattice_pair_uncovered=len(e.di)-n,best_found_uncovered_samples=v['uncovered_samples'],
            global_infeasibility_proven=False,scenario='official 2-relay fleet' if count==2 else 'augmented fleet: permits R03; still at most 6 energy components',schedule=rows)
        dump(f'q3_feasibility_{count}relay.json',v);cases[count]=(rows,v)
        print('RESULT',count,v['status'],v['uncovered_samples'],flush=True)
    chosen=2 if cases[2][1]['strict_feasible'] else 3
    rows=cases[chosen][0];table('q3_final_schedule.csv',rows)
    with (RESULTS/'q3_final_schedule.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    sens=[]
    for spacing in (15,10,5):
        v,intervals,links=validate(rows,spacing,chosen)
        sens.append({k:v[k] for k in ['los_spacing_m','total_samples','uncovered_samples','coverage','status','energy_kwh']})
        if spacing==10:
            dump('q3_final_validation.json',v);table('q3_final_blackout_intervals.csv',intervals,['trip_id','start_s','last_sample_s','end_exclusive_s','uncovered_samples']);final=v;final_links=links
    table('q3_los_resolution_sensitivity.csv',sens)
    final['robust_across_tested_los']=all(r['status']=='PASS' for r in sens);dump('q3_final_validation.json',final)
    if final['strict_feasible']:
        table('q3_relay_schedule.csv',rows);dump('q3_validation.json',final);table('q3_communication_links.csv',final_links)
        dump('q3_schedule_summary.json',dict(n_relays_used=chosen,fine_total=final['total_samples'],fine_uncovered=final['uncovered_samples'],fine_coverage=final['coverage'],time_step_s=1,los_spacing_m=10,strict_feasible=True,energy_kwh=final['energy_kwh'],robust_across_tested_los=final['robust_across_tested_los'],resource_scenario=cases[chosen][1]['scenario']))
    else:
        with (RESULTS/'q3_relay_schedule.csv').open(encoding='utf-8-sig') as f:old=list(csv.DictReader(f))
        v,_,_=validate(old);dump('q3_validation.json',v)
        summary=json.loads((RESULTS/'q3_schedule_summary.json').read_text(encoding='utf-8'))
        summary.update(fine_total=v['total_samples'],fine_uncovered=v['uncovered_samples'],fine_coverage=v['coverage'],time_step_s=1,los_spacing_m=10,strict_feasible=False);dump('q3_schedule_summary.json',summary)
    import summary
    summary.main()
    assert before==hashes(),'Q2 changed'
    print('FINAL',json.dumps(final,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
