from pathlib import Path
import ast,csv,hashlib,json,math,subprocess,sys
root=Path.cwd(); audit=root/'Q3/audit'; results=root/'Q3/results'
sys.path.insert(0,str(root/'Q3/code'))
from validation_io import identity
r=json.loads((results/'e4_final_validation.json').read_text(encoding='utf-8'))
checks={'current_input_hashes_match':r['provenance']['input_sha256']==identity(results/'q3_official_plan.json',results/'q3_transport_schedule.csv')}
for name in ['q3_final_validation.json','q3_validation.json','q3_schedule_summary.json']:
 checks[name+'_matches']=json.loads((results/name).read_text(encoding='utf-8'))==r
with (results/'q3_relay_schedule.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
checks['csv_energy_sum_matches']=math.fsum(float(row['energy_kwh']) for row in rows)==r['energy_kwh']
checks['csv_status_matches']=all(row['validation_status']==r['status'] for row in rows)
checks['schedule_copies_identical']=(results/'q3_relay_schedule.csv').read_bytes()==(results/'q3_final_schedule.csv').read_bytes()
for p in (root/'Q3/code').glob('*.py'): ast.parse(p.read_text(encoding='utf-8-sig'))
checks['q3_python_syntax']=True
run=subprocess.run(['git','diff','--check'],capture_output=True,cwd=root)
(audit/'logs/git_diff_check.log').write_bytes(run.stdout+run.stderr)
checks['git_diff_check_exit_code']=run.returncode
checks['all_consistent']=all(v for k,v in checks.items() if k!='git_diff_check_exit_code') and run.returncode==0
(audit/'final_consistency.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
assert checks['all_consistent'],checks
print(json.dumps(checks,indent=2))
