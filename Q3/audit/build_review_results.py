"""Generate reconciliation, protected-file evidence and Chinese review from actual artifacts."""
import csv,hashlib,json,math,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; AUDIT=ROOT/'Q3/audit'; R=ROOT/'Q3/results'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig') as f: return list(csv.DictReader(f))
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    before=read(AUDIT/'before.json'); report=read(R/'e4_final_validation.json')
    fixed=read(R/'q3_official_plan.json')['relay_sorties']
    old_relay=rows(R/'history_pre_audit/q3_relay_schedule.csv')
    fixed_decisions=all(all(str(new[k])==old[k] if k in ('sortie_id','relay_id','energy_component_id')
                           else float(new[k])==float(old[k]) for k in new) for old,new in zip(old_relay,fixed)) and len(fixed)==len(old_relay)
    old_transport=list(csv.DictReader(subprocess.check_output(['git','show','HEAD:Q3/results/q3_transport_schedule.csv'],cwd=ROOT).decode('utf-8-sig').splitlines()))
    new_transport=rows(R/'q3_transport_schedule.csv')
    time_fields=('preparation_start_s','takeoff_s','return_s')
    transport_decisions=all(all(a[k]==b[k] for k in a if k not in time_fields)
                            and all(abs(float(a[k])-float(b[k]))<=.000000500001 for k in time_fields)
                            for a,b in zip(old_transport,new_transport)) and len(old_transport)==len(new_transport)
    actual={p.relative_to(ROOT).as_posix():digest(p) for p in (ROOT/'Q4').rglob('*') if p.is_file()}
    previous={k:v for k,v in before['files'].items() if k.startswith('Q4/')}
    q4diff=subprocess.check_output(['git','diff','--numstat','--','Q4'],cwd=ROOT,text=True)
    protected={}
    for name in ('README.md','Q3/METHOD_STRICT.md','Q3/TWO_RELAY_EXPERIMENT_REPORT.md','Q3/E4_E5_TWO_RELAY_REPORT.md','Q3/E4_FINAL_VALIDATION_REPORT.md'):
        old=subprocess.check_output(['git','show','HEAD:'+name],cwd=ROOT)
        old=next(blob for blob in (old,old.replace(b'\n',b'\r\n'))
                 if hashlib.sha256(blob).hexdigest()==before['files'][name])
        new=(ROOT/name).read_bytes()
        # Every complete baseline line discussing Q4 must remain byte-for-byte.
        lines=[s for s in old.splitlines(keepends=True) if b'Q4' in s or '第四问'.encode() in s]
        protected[name]=all(s in new for s in lines)
    q2unchanged={k: digest(ROOT/k)==v for k,v in before['files'].items() if k.startswith('Q2/code/') or k.startswith('Q2/results/')}
    evidence=dict(q4_file_count=len(actual),q4_hashes_before=previous,q4_hashes_after=actual,
        all_q4_files_identical=previous==actual,git_diff_numstat_q4=q4diff,
        q4_status=subprocess.check_output(['git','status','--short','--','Q4'],cwd=ROOT,text=True),
        protected_document_lines_unchanged=protected,q2_code_and_results_unchanged=all(q2unchanged.values()))
    evidence.update(q3_fixed_relay_decisions_unchanged=fixed_decisions,
                    q3_transport_only_removed_time_rounding=transport_decisions)
    dump(AUDIT/'protection_check.json',evidence)
    assert previous==actual and not q4diff and all(protected.values()) and all(q2unchanged.values()) and fixed_decisions and transport_decisions,evidence
    base=R/'history_pre_audit'; old_csv=math.fsum(float(r['energy_kwh']) for r in rows(base/'q3_relay_schedule.csv'))
    old_e4=read(base/'e4_final_validation.json')['relay_total_energy_kwh']
    plan=read(R/'q3_official_plan.json')['relay_sorties']; energies=report['relay_sorties']
    links=rows(R/'q3_communication_links.csv')
    old_end=max(float(r['time_s']) for r in links if r['provider']=='S03')+1
    duration_delta=old_end-plan[2]['service_end_s']
    window_delta=duration_delta*1.1/3600
    reproduced_old_e4=math.fsum(round(e['legacy_unrounded_energy_kwh']+(window_delta if i==2 else 0),6) for i,e in enumerate(energies))
    removed_climb=math.fsum(e['legacy_unrounded_energy_kwh']-e['energy_kwh']+1.1*30/3600 for e in energies)
    reconciliation=dict(before_csv_total_kwh=old_csv,before_e4_total_kwh=old_e4,before_difference_kwh=old_e4-old_csv,
        formal_west_end_s=plan[2]['service_end_s'],legacy_validator_derived_end_s=old_end,
        extra_service_s=duration_delta,extra_service_energy_kwh=window_delta,
        old_validator_reproduced_kwh=reproduced_old_e4,legacy_fixed_window_unrounded_kwh=report['legacy_fixed_window_unrounded_kwh'],
        duplicate_return_climb_removed_kwh=removed_climb,link_build_added_kwh=3*1.1*30/3600,
        corrected_total_kwh=report['energy_kwh'],sorties=energies)
    dump(AUDIT/'energy_reconciliation.json',reconciliation)
    assert abs(reproduced_old_e4-old_e4)<1e-12
    q1=rows(ROOT/'Q1/results/q1_batches_default.csv'); q2=report['transport']['metrics']
    cmds=read(AUDIT/'commands.json'); reproduction=read(AUDIT/'reproduction.json')
    assert reproduction['all_equal']
    status=subprocess.check_output(['git','-c','core.quotepath=false','status','--short','--untracked-files=all'],cwd=ROOT,text=True)
    changed=[s[3:] for s in status.splitlines() if not s[3:].startswith('Q4/')]
    purposes={
        'Q1/code/verify.py':'补齐默认方案、分阶段时间、SOC、提交表数值、汇总与失败退出码；不改模型',
        'Q1/results/q1_verification.json':'本次166条记录和新增核对项的实际结果',
        'Q1/README.md':'同步本次复核状态，保留模型结论边界',
        'Q2/README.md':'说明本次独立重验及通信未纳入Q2；模型和结果逐字节不变',
        'README.md':'仅替换第三问边界条目，所有Q4内容保留',
        'Q3/code/finalize_e4_q3.py':'新临时目录启动验证、哈希绑定、真实状态汇总、FAIL/ERROR非零退出、统一派生正式结果',
        'Q3/code/validate_two_relay_experiment.py':'正式固定输入、独立运输算术/DEM/轨迹、分阶段中继能源和时序、全网格通信重算',
        'Q3/code/build_official_transport.py':'按既有两个平移量恢复Q3运输全精度时间，不搜索、不回写Q2',
        'Q3/code/test_finalize_e4_q3.py':'临时目录错误注入与非对称往返能源算例',
        'Q3/code/validation_io.py':'轻量I/O与输入哈希；科学依赖加载异常也能使finalize撤销旧成功状态',
        'Q3/results/q3_official_plan.json':'从基准CSV冻结中继决策及运输调整，切断结果与验证循环依赖',
    }
    inventory=[]
    for name in changed:
        purpose=purposes.get(name)
        if purpose is None:
            if '/history_pre_audit/' in name: purpose='保存基准历史资料；非当前正式证据'
            elif name.startswith('Q3/figures/') and name.endswith('.png'): purpose='移至history_pre_audit原样保留（不是删除历史证据）'
            elif name.startswith('Q3/code/'): purpose='正式别名入口统一调用新finalize，避免旧调度或旧PASS覆盖'
            elif name.startswith('Q3/results/'): purpose='从同一次真实独立验证生成正式明细、汇总或日志；旧敏感性表移入历史'
            elif name.startswith('Q3/audit/'): purpose='审查输入状态、命令日志、负向测试、复现、差异与保护证据'
            elif name.startswith('Q3/'): purpose='同步真实FAIL与能源/采样边界，旧实验显式标历史，Q4既存语句原样保留'
            else: purpose='本次审查记录'
        inventory.append(dict(file=name,purpose=purpose))
    dump(AUDIT/'changed_files.json',inventory)
    lines=['# Q1–Q3 本地审查与实际复现报告','',
        '日期：2026-09-24。审查版本为 main@afba25c976360f32f4a49d7e8cb0af64b63f0e79，正好等于指定基准；没有基准之外的初始已跟踪修改。原有未跟踪Q4/FIX_checkpoint_before.md完整保留。本次工作分支work/q1-q3-validation，未提交、推送或合并。实际仓库在E:/GitHub_Project/2026_competition；环境初始目录2026_comp是原始附件目录。',
        '', '## 本次状态与核心指标','',
        f'- Q1：PASS；18架次，B/C各9，80箱；总能耗{math.fsum(float(r["energy_kwh"]) for r in q1):.12f} kWh；累计作业{math.fsum(float(r["operation_s"]) for r in q1):.9f} s；最低返航SOC {min(float(r["soc_pct"]) for r in q1):.9f}%。9份方案表166条记录实际重验；模型和正式组批不变。',
        '- Q2：PASS（声明模型假设下）；80箱，31个硬时限全满足，26架次/55航段，运输能耗71.440968978416 kWh，完工6973.648576673 s，最低SOC 20.948947326%。独立重算航段载荷、能源、SOC、电池充电、时序和资源冲突，并核对DEM及轨迹边界。未运行优化和改进回放。通信、回传不是Q2模型约束，Q2本次不宣称已验证这些约束。',
        f'- Q3：**FAIL**；2架物理中继、3架次、3组组件不变。运输约束通过，运输能耗{q2["total_energy_kwh"]:.12f} kWh，完工{q2["makespan_s"]:.9f} s；中继能源{report["energy_kwh"]:.12f} kWh，各架次SOC与余量通过，但中继时序和细时间网格失败。',
        '', '[全部逐架次能源、SOC、实际样本数与失败明细](../results/q3_current_report.md)。1秒覆盖是固定名义服务窗口下的离散覆盖，不代表物理时序可执行。',
        '', '## 能耗差异的代码与数据依据','',
        f'修复前正式CSV合计{old_csv:.9f} kWh，旧e4 JSON为{old_e4:.9f} kWh。旧finalize固定S03窗口[6478.3,6902.0)，旧验证器evaluate却把西侧结束时刻改成残余需求最后样本+1，即{old_end:.12f}秒，多计{duration_delta:.12f}秒服务。1.10 kW×该时长/3600={window_delta:.12f} kWh，各架次先舍入6位后正好复现旧差0.000120 kWh。主要原因是不同窗口，不是单纯浮点误差或DEM版本。',
        f'固定窗口按旧公式不提前舍入总量为{report["legacy_fixed_window_unrounded_kwh"]:.12f} kWh。进一步逐阶段核查发现relay.relay_sortie复制去程时长为返程，并把中心到悬停海拔的爬升能耗重复用于返程；三个悬停点均等于各自巡航海拔，返程应先水平飞行再下降，不应再次计中心起飞爬升。去除重复爬升{removed_climb:.12f} kWh，加入三次各30秒建链悬停/通信共0.027500000000 kWh，得唯一正式值{report["energy_kwh"]:.12f} kWh。',
        '建链时无线电开启是显式保守假设；下降附加能耗维持附件0口径。能源是固定窗口下逐个架次的计算合计，不证明组合时序可行。原输入位置、服务窗口、归属与计划时刻均未改变。公式见METHOD_STRICT.md，逐阶段数值及新旧对账见energy_reconciliation.json。',
        '', '## 明确失败与边界','',
        '- S01/S02/S03分阶段计算返航为8506.220613995 / 5190.368457385 / 7795.123233770秒，原计划8440.2 / 5145.8 / 7724.5秒。R02第二次准备5445.8秒，前一架次返航+300秒周转后应至少5490.368457385秒，差44.568457385秒。',
        '- 1秒、LOS15/10/5米各36351样本、0 uncovered、100%；0.5秒72690样本/1 uncovered/99.998624295%；0.25秒145366样本/3 uncovered/99.997936244%。细网格失败来自T004在744.25/744.5/744.75秒尚无可用链路，早于南侧中继745秒名义服务起点。中断段1段，分别0.5/0.75“样本秒”，不是严格连续中断长度。',
        '- 三处中继到基站的双向回传在各LOS间距均通过。LOS值表示地形采样间距，不是净空；净空0米。服务窗口与采样端点规则见自动报告。',
        '- 全部运输巡航的最小DEM净空50米，已从240个有向几何重算；节点作业高度按附件海拔定义，起降采样相对DEM最小约−1.02554米，属于节点指定海拔与DEM像元差异，不得把它当作地面一致性认证或实飞保证。',
        '- 原节点/DEM、Q2充电并行与运输补充能源模型的假设边界仍存在；投影像元遍历是数值实现，不是任意地区的形式化证明。连续时间覆盖未获证明，本次反而检出细网格失败。',
        '- 修正固定方案可行性需要重排中继/服务或相关运输时序；本次按固定方案审查范围保留失败方案与证据，没有为追求PASS另搜新解，不声称已满足全部约束。历史三架和静态两架仅作明确标记对照。',
        '', '## 实际命令与退出码','', '| 标签 | 实际命令 | 退出码 |', '|---|---|---:|']
    lines += [f"| {c['label']} | `{subprocess.list2cmdline(c['command'])}` | {c['exit_code']} |" for c in cmds]
    lines += ['', '日志位于logs/，结构化记录见commands.json。finalize和直接独立验证均退出1，表示真实方案FAIL；11项失败路径/算术回归测试退出0。此前开发阶段一次ERROR来自原运输CSV六位小数舍入造成资源微重叠，已由全精度重建消除；原始异常日志仍保留，未冒充验证通过。',
        '', '## 复现与保护证据','',
        '- run_review.py从原Q2时间重新生成运输CSV，字节一致；再次直接运行独立验证器，所有数值/检查和CSV输出一致，仅排除运行时间/临时路径等provenance字段。见reproduction.json。原始DEM与Q3缓存逐像元子集一致，见terrain_source_check.json。',
        f'- Q4共{len(actual)}个文件（含用户未跟踪文件）前后SHA-256完全相同；git diff --numstat -- Q4为空；共享README及Q3既存文档中所有涉及Q4的原行逐字节保留。Q2代码和结果亦逐字节不变。证据见before.json、protection_check.json。',
        '- 未运行Q4入口、仓库总入口、任何新优化搜索或历史三架实验；未推送或合并。Q4已有结论未确认，本次不予认证。',
        '', '## 修改文件逐项清单','', '| 文件 | 目的 |', '|---|---|']
    lines += [f"| `{r['file']}` | {r['purpose']} |" for r in inventory]
    (AUDIT/'REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Protection, energy reconciliation and review generated')
if __name__=='__main__': main()
