"""Publish only fresh independent validation of the immutable official decisions.
Always runs the validator in a fresh temporary directory; never reuses old PASS.
Constraint failure publishes FAIL diagnostics and exits 1; missing/invalid output
or exceptions invalidate formal status, publish ERROR and exit 2.
"""
from __future__ import annotations
import argparse,json,math,shutil,subprocess,sys,tempfile
from pathlib import Path
CODE=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE))
from validation_io import RESULTS,read_csv,dump,table,identity


def verify_report(report,plan,transport,returncode):
    if report.get('status') not in ('PASS','FAIL'): raise ValueError('Validator did not complete checks')
    if report.get('provenance',{}).get('input_sha256')!=identity(plan,transport): raise ValueError('Stale or mismatched validator input identity')
    checks=report.get('checks')
    if not isinstance(checks,list) or not checks or any(type(c.get('pass_')) is not bool for c in checks): raise ValueError('Missing actual checks')
    required={'fixed_physical_sorties','three_distinct_components','transport_independent_arithmetic',
        'transport_trajectory_boundaries','transport_cruise_clearance','transport_native_DEM_geometry','R02_physical_turnaround'}
    required|={f'S0{i}_{name}' for i in (1,2,3) for name in ('energy_reserve','agl','arrival','return_time','departure','nonnegative_order')}
    if not required.issubset({c['check'] for c in checks}): raise ValueError('Incomplete checks')
    los=report['los_sensitivity']; temporal=report['temporal_sensitivity']
    if {r['los_spacing_m'] for r in los}!={5.,10.,15.} or {r['time_step_s'] for r in temporal}!={.5,.25}: raise ValueError('Missing sensitivity runs')
    for r in los+temporal:
        if r['total_samples']<=0 or not 0<=r['uncovered_samples']<=r['total_samples']: raise ValueError('Invalid samples')
        expected=1-r['uncovered_samples']/r['total_samples']
        if abs(r['coverage']-expected)>1e-12: raise ValueError('Coverage mismatch')
        valid=r['uncovered_samples']==0 and all(r['backhaul'].values())
        if (r['status']=='PASS')!=valid: raise ValueError('Contradictory communication status')
    passed=all(c['pass_'] for c in checks) and all(r['status']=='PASS' for r in los+temporal)
    if report['overall_pass']!=passed or report['strict_feasible']!=passed or (report['status']=='PASS')!=passed: raise ValueError('Contradictory aggregate status')
    if returncode!=(0 if passed else 1): raise ValueError('Validator exit/status mismatch')
    energy=math.fsum(r['energy_kwh'] for r in report['relay_sorties'])
    if abs(energy-report['energy_kwh'])>1e-12: raise ValueError('Energy sum mismatch')
    return passed


def publish(report,plan,out,scratch):
    rows=json.loads(plan.read_text(encoding='utf-8'))['relay_sorties']
    energy={r['sortie_id']:r for r in report['relay_sorties']}
    for r in rows:
        e=energy[r['sortie_id']]
        for name in ('energy_kwh','return_soc','reserve_margin_kwh','calculated_return_s'):
            r[name]=e[name]
        r['calculated_flight_out_s']=e['flight_out_s']; r['calculated_flight_back_s']=e['flight_back_s']
        r['validation_status']=report['status']
    for name in ('q3_relay_schedule.csv','q3_final_schedule.csv'): table(out/name,rows,list(rows[0]))
    for name in ('q3_final_validation.json','q3_validation.json','q3_schedule_summary.json'): dump(out/name,report)
    fields=['scenario','relays','relay_sorties','energy_components','coverage','outage_s','longest_outage_s','relay_energy_kwh','strict_feasible','status']
    comm=report['communication']
    table(out/'q3_summary.csv',[dict(scenario='C_two_relay_joint_fixed',relays=report['physical_relay_count'],relay_sorties=report['relay_sortie_count'],
        energy_components=report['relay_component_count'],coverage=comm['coverage'],outage_s=comm['outage_sample_seconds'],
        longest_outage_s=comm['longest_outage_sample_seconds'],relay_energy_kwh=report['energy_kwh'],strict_feasible=report['strict_feasible'],status=report['status'])],fields)
    for source,target in [('e4_los_sensitivity.csv','q3_los_resolution_sensitivity.csv'),
                          ('e4_blackout_intervals.csv','q3_final_blackout_intervals.csv'),
                          ('e4_blackout_intervals.csv','q3_blackout_intervals.csv')]:
        shutil.copyfile(scratch/source,out/target)
    for p in scratch.iterdir():
        if p.is_file(): shutil.copyfile(p,out/p.name)
    lines=['# Q3 本次固定方案验证（自动生成）','',f"总状态：**{report['status']}**。不得将单项采样覆盖通过写成方案可行。",'',
        f"物理中继 {report['physical_relay_count']} 架（R01/R02）；{report['relay_sortie_count']} 架次（R01×1、R02×2）；{report['relay_component_count']} 组能源组件。",'',
        f"中继总能耗 {report['energy_kwh']:.12f} kWh；运输总能耗 {report['transport_total_energy_kwh']:.12f} kWh。",'',
        f"运输完工 {report['transport_makespan']:.9f} s；联合完工（含中继返航）{report['calculated_joint_makespan']:.9f} s。",'',
        '| 架次 | 能耗 kWh | 返航 SOC | 高于20%余量 kWh |','|---|---:|---:|---:|']
    lines += [f"| {e['sortie_id']} / {e['relay_id']} | {e['energy_kwh']:.12f} | {e['return_soc']:.9%} | {e['reserve_margin_kwh']:.12f} |" for e in report['relay_sorties']]
    lines += ['', '| 时间步长 s | LOS 间距 m | 实际样本 | uncovered | 覆盖率 | 中断段 | 最长样本秒 | 状态 |', '|---:|---:|---:|---:|---:|---:|---:|---|']
    lines += [f"| {r['time_step_s']:g} | {r['los_spacing_m']:g} | {r['total_samples']} | {r['uncovered_samples']} | {r['coverage']:.9%} | {r['interruption_count']} | {r['longest_outage_sample_seconds']:g} | {r['status']} |" for r in report['los_sensitivity']+report['temporal_sensitivity']]
    lines += ['', '失败项：', '']+[f"- `{c['check']}`：`{json.dumps(c['detail'],ensure_ascii=False)}`" for c in report['checks'] if not c['pass_']]
    lines += ['', '逐架次 t=takeoff+k×步长，t<return；起点纳入、返回端点排除。服务窗口左闭右开。中断样本秒为 uncovered×步长，不是已严格证明的连续中断时长。',
        '', 'LOS 5/10/15 m 指视线水平投影上的地形采样间距，并非净空；净空为0 m。每次采样同时检查双向接入和双向回传，不允许中继间多跳。',
        '', '能耗唯一口径：往返分别计算爬升/巡航/下降，返程从悬停海拔出发；建链与服务均计悬停和通信功率，下降附加能耗按附件为0。逐阶段不提前舍入。建链期间通信功率按开启计，是明确的保守假设。',
        '', '阶段明细、版本、依赖版本、输入 SHA-256、实际命令见 e4_final_validation.json；运行日志见 q3_validator_run.log。']
    (out/'q3_current_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def invalidate(out,error):
    # Keep prior evidence but remove it from the current formal namespace.
    names=['q3_relay_schedule.csv','q3_final_schedule.csv','q3_los_resolution_sensitivity.csv',
        'q3_final_blackout_intervals.csv','q3_blackout_intervals.csv','q3_communication_links.csv',
        'q3_current_report.md','e4_relay_validation.json','e4_transport_validation.json',
        'e4_communication_validation.json','e4_los_sensitivity.csv','e4_temporal_sensitivity.csv']
    for name in names:
        if (out/name).is_file():
            previous=out/'previous_unvalidated'; previous.mkdir(exist_ok=True)
            shutil.copyfile(out/name,previous/name)
            (out/name).unlink()
    report=dict(status='ERROR',overall_pass=False,strict_feasible=False,error=error,
                total_samples=None,uncovered_samples=None,coverage=None,energy_kwh=None,
                qualification='Validation not completed. No current PASS or numerical claim.')
    for name in ('q3_final_validation.json','q3_validation.json','q3_schedule_summary.json','e4_final_validation.json'):
        dump(out/name,report)
    # Make old human-facing summary unusable as a current success claim.
    table(out/'q3_summary.csv',[dict(status='ERROR',detail=error)],['status','detail'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,default=RESULTS/'q3_official_plan.json')
    p.add_argument('--transport',type=Path,default=RESULTS/'q3_transport_schedule.csv')
    p.add_argument('--output',type=Path,default=RESULTS)
    a=p.parse_args(); out=a.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    try:
        plan=a.plan.resolve(); transport=a.transport.resolve()
        with tempfile.TemporaryDirectory(prefix='q3-validation-') as tmp:
            scratch=Path(tmp)
            cmd=[sys.executable,'-B',str(CODE/'validate_two_relay_experiment.py'),'--plan',str(plan),'--transport',str(transport),'--output',str(scratch)]
            run=subprocess.run(cmd,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/'q3_validator_run.log').write_text(json.dumps(dict(command=cmd,exit_code=run.returncode))+'\n'+run.stdout,encoding='utf-8')
            report=json.loads((scratch/'e4_final_validation.json').read_text(encoding='utf-8'))
            passed=verify_report(report,plan,transport,run.returncode)
            needed=['e4_relay_validation.json','e4_transport_validation.json','e4_communication_validation.json','e4_los_sensitivity.csv',
                'e4_temporal_sensitivity.csv','e4_blackout_intervals.csv','e4_blackout_samples.csv','q3_communication_links.csv',
                'q3_transport_timeline.csv','e4_blackout_samples_0.5s.csv','e4_blackout_samples_0.25s.csv']
            if any(not (scratch/n).is_file() for n in needed): raise FileNotFoundError('Missing validator artifact')
            publish(report,plan,out,scratch)
            print(json.dumps(dict(status=report['status'],energy_kwh=report['energy_kwh'],uncovered_samples=report['uncovered_samples'])))
            return 0 if passed else 1
    except Exception as exc:
        invalidate(out,f'{type(exc).__name__}: {exc}')
        import traceback; traceback.print_exc(); return 2
if __name__=='__main__': sys.exit(main())
