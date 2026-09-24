"""Independent fixed-plan validation. Never extends windows or reads finalize PASS.
Exit 0: checks pass; 1: constraint failure; 2: missing input/exception.
"""
from __future__ import annotations
import argparse,csv,hashlib,importlib.metadata,json,math,platform,shutil,subprocess,sys,tempfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
CODE=Path(__file__).resolve().parent
REPO=CODE.parents[1]
sys.path.insert(0,str(CODE))
from config import RESULTS,Q2_RESULTS,load_scenario
from terrain import Terrain
from check_core import independent_link_budget,independent_los_occluded
from trajectory import TransportTrajectory
from transport_core import Model,Trajectory
from solve import recompute,export
from independent_audit import independent_schedule,trajectories
from prepare_data import Terrain as ExactTerrain
from validation_io import read_csv,dump,table,identity

def exact_terrain(terrain):
    """Use the Q2 native-cell traversal on the same versioned geographic crop."""
    result=ExactTerrain.__new__(ExactTerrain)
    for name in ('z','dx','west','dy','north','nodata','inverse'):
        setattr(result,name,getattr(terrain,name))
    result.native_utm=True
    return result

def provenance(plan,transport):
    return dict(input_sha256=identity(plan,transport),command=[sys.executable,*sys.argv],
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        python=platform.python_version(),packages={n:importlib.metadata.version(n) for n in ('numpy','scipy','pyproj','mpmath')},
        parameters=dict(time_steps_s=[1,.5,.25],los_spacings_m=[15,10,5],los_clearance_m=0,
            baseline_display_time_tolerance_s=.050001,position_tolerance_m=.00001,
            interval='takeoff inclusive, return exclusive; service left closed/right open',
            coverage_condition='nominal fixed service windows; physical timing is checked separately and can FAIL'),
        started_utc=datetime.now(timezone.utc).isoformat())
def energy_and_phases(r,sc,terr,o):
    """Directional flight, 30 s link-building hover/radio, service; no early rounding.
    Terrain maximum uses native-cell traversal; descent energy is zero.
    Return climb starts at hover altitude, not at O01 altitude.
    """
    k=sc['official_relay']; x,y,z=(float(r[n]) for n in ('hover_x_m','hover_y_m','hover_altitude_m'))
    d=math.hypot(x-o['x_m'],y-o['y_m']); u=np.linspace(0,1,max(2,int(d/15)+1))
    elev=terr.elevations(o['x_m']+(x-o['x_m'])*u,o['y_m']+(y-o['y_m'])*u)
    if not np.all(np.isfinite(elev)) or np.any(elev==terr.nodata): raise ValueError('Invalid terrain')
    peak,cells=exact_terrain(terr).maximum((o['x_m'],o['y_m']),(x,y))
    h=max(peak+50,z); up=h-o['work_m']; down=h-z; cruise=d/k['cruise_mps']
    factor=k['takeoff_mass_kg']*sc['model']['gravity_mps2']/k['ascent_efficiency']/3.6e6
    phases=[]
    for direction,a,b in [('out',up,down),('back',down,up)]:
        phases.extend([dict(phase=direction+'_ascent',duration_s=a/k['ascent_mps'],energy_kwh=factor*a),
            dict(phase=direction+'_cruise',duration_s=cruise,energy_kwh=k['cruise_power_kw']*cruise/3600),
            dict(phase=direction+'_descent',duration_s=b/k['descent_mps'],energy_kwh=0.)])
    for name,t in [('link_build',k['link_build_s']),('service',r['service_end_s']-r['service_start_s'])]:
        phases.append(dict(phase=name,duration_s=t,energy_kwh=(k['hover_power_kw']+k['comm_power_kw'])*t/3600))
    service_energy=phases[-1]['energy_kwh']
    phases=phases[:3]+phases[6:]+phases[3:6]
    e=math.fsum(p['energy_kwh'] for p in phases)
    out=math.fsum(p['duration_s'] for p in phases if p['phase'].startswith('out_'))
    back=math.fsum(p['duration_s'] for p in phases if p['phase'].startswith('back_'))
    return dict(sortie_id=r['sortie_id'],relay_id=r['relay_id'],phases=phases,distance_m=d,
        terrain_peak_m=peak,terrain_cells=cells,legacy_sampled_peak_m=float(elev.max()),cruise_altitude_m=h,flight_out_s=out,flight_back_s=back,
        energy_kwh=e,return_soc=1-e/k['energy_kwh'],reserve_margin_kwh=(1-k['reserve'])*k['energy_kwh']-e,
        calculated_return_s=r['service_end_s']+back,agl_m=z-terr.elevation(x,y),
        legacy_unrounded_energy_kwh=2*(factor*up+k['cruise_power_kw']*cruise/3600)+service_energy)
def interruptions(rows,step):
    intervals=[]
    for r in sorted(rows,key=lambda r:(r['trip_id'],r['time_s'])):
        if intervals and intervals[-1]['trip_id']==r['trip_id'] and abs(intervals[-1]['last_sample_s']+step-r['time_s'])<1e-6:
            intervals[-1]['last_sample_s']=r['time_s']; intervals[-1]['uncovered_samples']+=1
        else: intervals.append(dict(trip_id=r['trip_id'],start_s=r['time_s'],last_sample_s=r['time_s'],uncovered_samples=1))
    for r in intervals:
        r['end_exclusive_s']=r['last_sample_s']+step; r['sample_seconds']=r['uncovered_samples']*step
    return intervals

def run(plan_path,transport_path,out):
    out.mkdir(parents=True,exist_ok=True); prov=provenance(plan_path,transport_path)
    sc=load_scenario(); k=sc['official_relay']; plan=json.loads(plan_path.read_text(encoding='utf-8'))['relay_sorties']
    transport=read_csv(transport_path); checks=[]
    def check(name,ok,detail=None): checks.append(dict(check=name,pass_=bool(ok),detail=detail))
    check('fixed_physical_sorties',Counter(r['relay_id'] for r in plan)==Counter({'R01':1,'R02':2}))
    check('unique_sorties',len({r['sortie_id'] for r in plan})==len(plan))
    check('three_distinct_components',len({r['energy_component_id'] for r in plan})==len(plan)==3 and len(plan)<=k['energy_components']['count'])
    terr=Terrain.load_npz(RESULTS/'q3_terrain_cache.npz')
    with tempfile.TemporaryDirectory(prefix='q3-transport-') as tmp:
        root=Path(tmp); model=Model(Q2_RESULTS/'q2_inputs.json',Q2_RESULTS/'q2_scenario.json')
        terrain_errors=[]
        exact=exact_terrain(terr)
        for key,g in model.data['geometry'].items():
            a,b=(model.nodes[n] for n in key.split('|'))
            peak,count=exact.maximum((a['x_m'],a['y_m']),(b['x_m'],b['y_m']))
            if abs(peak-g['terrain_max_m'])>1e-8 or count!=g['cell_count']:
                terrain_errors.append(dict(path=key,peak_m=peak,cells=count))
        check('transport_native_DEM_geometry',not terrain_errors,dict(paths=len(model.data['geometry']),errors=terrain_errors))
        entries=[dict(trip_id=r['trip_id'],drone_id=r['drone_id'],battery_id=r['battery_id'],box_ids=json.loads(r['box_ids_json']),
            route=r['route'].split('-')[1:-1],preparation_start_s=float(r['preparation_start_s'])) for r in transport]
        trips=recompute(model,entries) # explicit schedule only, never search
        export(model,trips,root,{'validation_only':True})
        shutil.copyfile(root/'q2_segments.csv',out/'q3_transport_timeline.csv')
        arithmetic=independent_schedule(root); trajectory_checks=trajectories(root,Trajectory)
        check('transport_independent_arithmetic',True,arithmetic)
        check('transport_trajectory_boundaries',True,trajectory_checks)
        rebuilt={r['trip_id']:r for r in read_csv(root/'q2_trips.csv')}
        for r in transport:
            t=rebuilt[r['trip_id']]
            check('transport_export_'+r['trip_id'],all(r[n]==t[n] for n in ('type_id','drone_id','battery_id','route','box_ids_json')) and
                all(abs(float(r[n])-float(t[n]))<=1e-6 for n in ('takeoff_s','return_s','total_energy_kwh','return_soc')))
        tj=TransportTrajectory(root); origin=tj.nodes()['O01']
        g01=(origin['x_m'],origin['y_m'],origin['ground_m']+sc['official_communication']['g01']['antenna_height_m'])
        energies=[energy_and_phases(r,sc,terr,origin) for r in plan]; by_drone=defaultdict(list)
        for r,e in zip(plan,energies):
            sid=r['sortie_id']; check(sid+'_energy_reserve',e['reserve_margin_kwh']>=-1e-9,e)
            check(sid+'_agl',-1e-5<=e['agl_m']<=k['max_hover_agl_m']+1e-5,e['agl_m'])
            check(sid+'_nonnegative_order',0<=r['prep_start_s']<=r['takeoff_s']<=r['service_start_s']<r['service_end_s']<r['return_s'])
            check(sid+'_departure',abs(r['takeoff_s']-r['prep_start_s']-k['prep_s'])<1e-6)
            # Half the original 0.1 s display unit, not a feasibility relaxation.
            check(sid+'_arrival',abs(r['service_start_s']-r['takeoff_s']-e['flight_out_s']-k['link_build_s'])<=.050001,
                dict(calculated=r['takeoff_s']+e['flight_out_s']+k['link_build_s'],scheduled=r['service_start_s']))
            check(sid+'_return_time',abs(r['return_s']-e['calculated_return_s'])<=.050001,
                dict(calculated=e['calculated_return_s'],scheduled=r['return_s']))
            by_drone[r['relay_id']].append((r,e))
        for rid,seq in by_drone.items():
            seq.sort(key=lambda x:x[0]['prep_start_s'])
            for (a,ae),(b,be) in zip(seq,seq[1:]):
                available=ae['calculated_return_s']+k['turnaround_s']
                check(rid+'_physical_turnaround',b['prep_start_s']>=available-1e-6,
                    dict(previous=a['sortie_id'],next=b['sortie_id'],next_prep_s=b['prep_start_s'],physically_available_s=available,gap_s=b['prep_start_s']-available))
        fsp,lobs,direct,access,backhaul=independent_link_budget(sc)
        def link(p,q,threshold,spacing):
            fs=20*math.log10(max(math.dist(p,q)/1000,1e-9))+fsp
            if fs+lobs<=threshold: return True
            if fs>threshold: return False
            return not independent_los_occluded(terr,*p,*q,spacing_m=spacing,clearance=sc['model']['los_clearance_m'])
        positions=[tuple(r[n] for n in ('hover_x_m','hover_y_m','hover_altitude_m')) for r in plan]
        def samples(step):
            records=[]
            for tid,t in rebuilt.items():
                start,end=float(t['takeoff_s']),float(t['return_s'])
                for i in range(math.ceil((end-start)/step)):
                    time=start+i*step
                    if time>=end: continue
                    s=tj.position(tid,time)
                    if s['phase']=='finished': raise ValueError('Premature finished trajectory')
                    records.append((time,tid,t['drone_id'],(s['x'],s['y'],s['altitude_m']),s['flight_phase']))
            return records
        def evaluate(records,spacing,step):
            bh=[link(p,g01,backhaul,spacing) for p in positions]; uncovered=[]; links=[]
            for time,tid,drone,p,phase in records:
                provider='G01' if link(g01,p,direct,spacing) else None
                if provider is None:
                    for i,r in enumerate(plan):
                        if r['service_start_s']<=time<r['service_end_s'] and bh[i] and link(positions[i],p,access,spacing):
                            provider=r['sortie_id']; break
                links.append(dict(time_s=time,trip_id=tid,transport_uav=drone,provider=provider or 'UNCOVERED'))
                if provider is None: uncovered.append(dict(time_s=time,trip_id=tid,transport_uav=drone,x=p[0],y=p[1],z=p[2],flight_phase=phase))
            intervals=interruptions(uncovered,step)
            result=dict(time_step_s=step,los_spacing_m=spacing,total_samples=len(records),uncovered_samples=len(uncovered),
                coverage=1-len(uncovered)/len(records) if records else None,outage_sample_seconds=len(uncovered)*step,
                interruption_count=len(intervals),longest_outage_sample_seconds=max((r['sample_seconds'] for r in intervals),default=0),
                backhaul=dict(zip((r['sortie_id'] for r in plan),bh)),status='PASS' if records and not uncovered and all(bh) else 'FAIL')
            return result,uncovered,intervals,links
        base=samples(1.)
        agls=[p[2]-terr.elevation(p[0],p[1]) for _,_,_,p,_ in base]
        cruise_agls=[agl for agl,record in zip(agls,base) if record[-1]=='cruise']
        check('transport_cruise_clearance',min(cruise_agls)>=50-1e-5,
            dict(samples=len(cruise_agls),minimum_agl_m=min(cruise_agls),all_phases_min_agl_m=min(agls),
                note='Node working altitudes use attachment elevations; ground endpoints are not cruise clearance tests.'))
        los=[]; uf=['time_s','trip_id','transport_uav','x','y','z','flight_phase']
        for spacing in (15.,10.,5.):
            result,unc,intervals,links=evaluate(base,spacing,1.); los.append(result)
            print('LOS',spacing,json.dumps(result),flush=True)
            if spacing==10:
                primary=result
                table(out/'e4_blackout_samples.csv',unc,uf)
                table(out/'e4_blackout_intervals.csv',intervals,['trip_id','start_s','last_sample_s','uncovered_samples','end_exclusive_s','sample_seconds'])
                table(out/'q3_communication_links.csv',links,['time_s','trip_id','transport_uav','provider'])
        temporal=[]
        for step in (.5,.25):
            result,unc,intervals,_=evaluate(samples(step),10.,step); temporal.append(result)
            table(out/f'e4_blackout_samples_{step:g}s.csv',unc,uf)
            print('TIME',step,json.dumps(result),flush=True)
        for result in los+temporal:
            check(f"communication_{result['time_step_s']}s_{result['los_spacing_m']}m",result['status']=='PASS',result)
        metrics=arithmetic['metrics']; passed=all(c['pass_'] for c in checks)
        result=dict(status='PASS' if passed else 'FAIL',overall_pass=passed,strict_feasible=passed,checks=checks,
            physical_relay_count=len(by_drone),relay_sortie_count=len(plan),relay_component_count=len({r['energy_component_id'] for r in plan}),
            energy_kwh=math.fsum(e['energy_kwh'] for e in energies),relay_total_energy_kwh=math.fsum(e['energy_kwh'] for e in energies),
            legacy_fixed_window_unrounded_kwh=math.fsum(e['legacy_unrounded_energy_kwh'] for e in energies),
            relay_sorties=energies,transport=arithmetic,communication=primary,los_sensitivity=los,temporal_sensitivity=temporal,
            transport_total_energy_kwh=metrics['total_energy_kwh'],transport_makespan=metrics['makespan_s'],
            scheduled_joint_makespan=max(metrics['makespan_s'],max(r['return_s'] for r in plan)),
            calculated_joint_makespan=max(metrics['makespan_s'],max(e['calculated_return_s'] for e in energies)),
            coverage=primary['coverage'],uncovered_samples=primary['uncovered_samples'],total_samples=primary['total_samples'],
            qualification='Discrete per-trip t=takeoff+k*step < return; left closed/right open; not continuous-time proof.',
            energy_convention='Directional round trip + link-building hover/radio + service hover/radio; descent zero; no early rounding.',provenance=prov)
    if identity(plan_path,transport_path)!=prov['input_sha256']: raise RuntimeError('Inputs changed during validation')
    result['provenance']['finished_utc']=datetime.now(timezone.utc).isoformat()
    dump(out/'e4_final_validation.json',result)
    dump(out/'e4_relay_validation.json',dict(sorties=energies,checks=[c for c in checks if c['check'].startswith(('S0','R0','fixed','unique','three'))]))
    dump(out/'e4_transport_validation.json',dict(arithmetic=arithmetic,trajectory=trajectory_checks,checks=[c for c in checks if c['check'].startswith('transport')]))
    dump(out/'e4_communication_validation.json',primary)
    fields=['time_step_s','los_spacing_m','total_samples','uncovered_samples','coverage','outage_sample_seconds','interruption_count','longest_outage_sample_seconds','backhaul','status']
    table(out/'e4_los_sensitivity.csv',los,fields); table(out/'e4_temporal_sensitivity.csv',temporal,fields)
    print(json.dumps({k:result[k] for k in ('status','energy_kwh','total_samples','uncovered_samples','coverage')},indent=2))
    return 0 if passed else 1

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,default=RESULTS/'q3_official_plan.json')
    p.add_argument('--transport',type=Path,default=RESULTS/'q3_transport_schedule.csv')
    p.add_argument('--output',type=Path,default=RESULTS)
    a=p.parse_args()
    try: return run(a.plan.resolve(),a.transport.resolve(),a.output.resolve())
    except Exception as exc:
        a.output.mkdir(parents=True,exist_ok=True)
        dump(a.output/'e4_final_validation.json',dict(status='ERROR',overall_pass=False,error=f'{type(exc).__name__}: {exc}',command=[sys.executable,*sys.argv]))
        import traceback; traceback.print_exc(); return 2
if __name__=='__main__': sys.exit(main())
