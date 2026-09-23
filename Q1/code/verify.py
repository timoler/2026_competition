"""Independent arithmetic verification using exported legs and original inputs."""
import csv,json,math,sys
from pathlib import Path
import openpyxl
P=Path(__file__).resolve().parents[1]; R=P/'results'
S=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2] / 'data/raw/D题'
B=S/'数据/无人机应急物资运输基础数据'
def read(n):return list(csv.DictReader((R/n).open(encoding='utf-8-sig')))
w=openpyxl.load_workbook(B/'运输无人机数据.xlsx',data_only=True)
g={r[0]:r for r in list(w.active.values)[2:5]}
w=openpyxl.load_workbook(B/'物资需求与配送时限.xlsx',data_only=True)
b={r[0]:r for r in list(w['逐箱货箱清单'].values)[1:]}
legs={(x['start'],x['end']):x for x in read('q1_legs.csv')}
checked=0
plan_files=sorted(R.glob('q1_batches_reserve_*.csv'))+sorted(R.glob('q1_batches_priority_*.csv'))
for f in plan_files:
    reserve=float(f.name.rsplit('_',1)[1].replace('.csv',''))/100 if 'reserve_' in f.name else 0.2
    assignments=[]
    for x in read(f.name):
        m=g[x['model']];cargo=[b[i] for i in x['box_ids'].split(';')];assignments.extend(r[0] for r in cargo)
        mass=sum(z[3] for z in cargo);vol=sum(z[4] for z in cargo)
        assert all(z[1]==x['site'] for z in cargo)
        assert mass<=m[3] and vol<=m[4]+1e-12
        energy=0.;fly=0.
        for a,c,q in [('O01',x['site'],mass),(x['site'],'O01',0)]:
            l=legs[a,c];dist=float(l['distance_m']);h=float(l['up_m']);down=float(l['down_m'])
            erange=m[6]+(m[7]-m[6])*math.sqrt((q/m[3])**3)
            energy+=dist*m[8]/erange+9.80665*(m[2]+q)*h/m[16]/3600000
            fly+=h/m[14]+dist/m[5]+down/m[15]
        assert math.isclose(energy,float(x['energy_kwh']),abs_tol=1e-9)
        assert energy<=(1-reserve)*m[8]+1e-9
        assert math.isclose(fly+m[10]+len(cargo)*m[11]+m[12]+len(cargo)*m[13],float(x['operation_s']),abs_tol=1e-7)
        checked+=1
    assert len(assignments)==80 and set(assignments)==set(b)
# Analytic baseline flight-count lower bound from maximum feasible payload and volume.
cap={(x['site'],x['model']):float(x['max_payload_kg']) for x in read('q1_max_payload_sensitivity.csv') if x['reserve']=='0.2' and x['max_payload_kg']}
lower={}
for s in sorted({x[1] for x in b.values()}):
    mass=sum(x[3] for x in b.values() if x[1]==s);vol=sum(x[4] for x in b.values() if x[1]==s)
    lower[s]=max(math.ceil(mass/max(cap[s,k] for k in g)-1e-10),math.ceil(vol/max(x[4] for x in g.values())-1e-10))
base=read('q1_batches_default.csv')
assert sum(lower.values())==len(base)==18
result=dict(checked_flights=checked,plans=len(plan_files),baseline_count_lower_bound=sum(lower.values()),baseline_count=len(base),site_lower_bounds=lower,checks=['80 boxes exactly once per plan','destination, mass, volume','independent energy and time recomputation','return energy reserve','18-flight analytic lower bound met'],limits=['Uses exported geometry; geometric model assumptions are not independently proven by this check.','Energy formula completion is a modeling assumption.'])
(R/'q1_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
