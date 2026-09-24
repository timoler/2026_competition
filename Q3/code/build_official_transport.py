"""Rebuild the existing Q3 transport decisions with full-precision Q2 times.
Does not optimize or modify Q2. Removes sub-microsecond rounding overlaps.
"""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    out=ROOT/'Q3/results'
    plan=json.loads((out/'q3_official_plan.json').read_text(encoding='utf-8'))
    with (ROOT/'Q2/results/q2_trips.csv').open(encoding='utf-8-sig') as f: trips=list(csv.DictReader(f))
    fields=['trip_id','type_id','drone_id','battery_id','route','box_ids_json','preparation_start_s','takeoff_s','return_s','total_energy_kwh','return_soc']
    rows=[]
    for t in trips:
        row={k:t[k] for k in fields}; change=plan['transport_adjustments'].get(t['trip_id'],{})
        for k in ('preparation_start_s','takeoff_s','return_s'): row[k]=float(t[k])+change.get('shift_s',0.)
        row['drone_id']=change.get('drone_id',t['drone_id']); rows.append(row)
    with (out/'q3_transport_schedule.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n'); w.writeheader(); w.writerows(rows)
if __name__=='__main__': main()
