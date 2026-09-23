"""Regenerate headline table from canonical 1-second independent validation."""
import csv
from config import RESULTS
from strict_feasibility import validate, table

def main():
    result=[]
    scenarios=[('A_no_relay',0,None),('B_two_relay_best_found',2,'q3_schedule_2relay.csv'),('C_three_relay_augmented',3,'q3_schedule_3relay.csv')]
    for name,n,path in scenarios:
        if path:
            with (RESULTS/path).open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        else:rows=[]
        v,intervals,_=validate(rows,10,n)
        result.append(dict(scenario=name,relays=n,coverage=v['coverage'],outage_s=v['uncovered_samples'],
            longest_outage_s=max([r['uncovered_samples'] for r in intervals] or [0]),
            affected_trips=len(set(r['trip_id'] for r in intervals)),
            relay_flight_s=sum(float(r['flight_out_s'])+float(r['flight_back_s']) for r in rows),
            relay_work_s=sum(float(r['return_s'])-float(r['prep_start_s']) for r in rows),
            relay_energy_kwh=v['energy_kwh'],strict_feasible=v['strict_feasible']))
    table('q3_summary.csv',result)
    return result
if __name__=='__main__':main()
