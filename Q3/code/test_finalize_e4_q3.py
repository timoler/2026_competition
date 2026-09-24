"""Failure-path tests in temporary outputs; never mutate formal files."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import finalize_e4_q3 as final
import validate_two_relay_experiment as validator

class FinalizeFailures(unittest.TestCase):
    def test_real_missing_input_without_site_packages(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            (out/'q3_final_validation.json').write_text('{"status":"PASS"}',encoding='utf-8')
            run=subprocess.run([sys.executable,'-S',str(final.CODE/'finalize_e4_q3.py'),
                '--plan',str(out/'missing.json'),'--output',str(out)],capture_output=True)
            self.assertEqual(run.returncode,2,run.stderr)
            self.assertEqual(json.loads((out/'q3_final_validation.json').read_text(encoding='utf-8'))['status'],'ERROR')
    def test_missing_output_invalidates_old_pass(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            (out/'q3_final_validation.json').write_text('{"status":"PASS"}',encoding='utf-8')
            with patch('sys.argv',['finalize','--output',d]), patch.object(final.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'no output')):
                self.assertEqual(final.main(),2)
            r=json.loads((out/'q3_final_validation.json').read_text(encoding='utf-8'))
            self.assertEqual(r['status'],'ERROR'); self.assertIsNone(r['coverage'])
    def test_subprocess_exception_invalidates_old_success_table(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); (out/'q3_relay_schedule.csv').write_text('validation_status\nPASS\n',encoding='utf-8')
            with patch('sys.argv',['finalize','--output',d]),patch.object(final.subprocess,'run',side_effect=OSError('injected launch failure')):
                self.assertEqual(final.main(),2)
            self.assertFalse((out/'q3_relay_schedule.csv').exists())
            self.assertTrue((out/'previous_unvalidated/q3_relay_schedule.csv').exists())
    def fixture(self):
        r=json.loads((final.RESULTS/'e4_final_validation.json').read_text(encoding='utf-8'))
        # Fixture identity is refreshed only inside memory for failure injection.
        r['provenance']['input_sha256']=final.identity(final.RESULTS/'q3_official_plan.json',final.RESULTS/'q3_transport_schedule.csv')
        return r
    def verify(self,r,code=1):
        return final.verify_report(r,final.RESULTS/'q3_official_plan.json',final.RESULTS/'q3_transport_schedule.csv',code)
    def test_actual_fail_stays_fail(self):
        self.assertFalse(self.verify(self.fixture()))
    def test_fail_cannot_be_promoted_to_pass(self):
        r=self.fixture(); r.update(status='PASS',overall_pass=True,strict_feasible=True)
        with self.assertRaisesRegex(ValueError,'aggregate'): self.verify(r,0)
    def test_stale_identity_rejected(self):
        r=self.fixture(); r['provenance']['input_sha256']={}
        with self.assertRaisesRegex(ValueError,'Stale'): self.verify(r)
    def test_missing_checks_rejected(self):
        r=self.fixture(); r['checks']=[]
        with self.assertRaisesRegex(ValueError,'Missing'): self.verify(r)
    def test_missing_sensitivity_rejected(self):
        r=self.fixture(); r['temporal_sensitivity']=[]
        with self.assertRaisesRegex(ValueError,'sensitivity'): self.verify(r)
    def test_exit_code_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,'exit'): self.verify(self.fixture(),0)
    def test_coverage_forgery_rejected(self):
        r=self.fixture(); r['temporal_sensitivity'][0]['coverage']=1
        with self.assertRaisesRegex(ValueError,'Coverage'): self.verify(r)
    def test_directional_flight_and_link_build_energy(self):
        class Flat:
            nodata=-9999
            def elevations(self,x,y): return np.zeros(len(x))
            def elevation(self,x,y): return 0.
        class Exact:
            def maximum(self,a,b): return 0.,1
        sc=validator.load_scenario(); k=sc['official_relay']
        row=dict(sortie_id='test',relay_id='R01',hover_x_m=1500.,hover_y_m=0.,hover_altitude_m=100.,service_start_s=1000.,service_end_s=1100.)
        with patch.object(validator,'exact_terrain',return_value=Exact()):
            e=validator.energy_and_phases(row,sc,Flat(),dict(x_m=0.,y_m=0.,work_m=0.))
        expected=k['takeoff_mass_kg']*sc['model']['gravity_mps2']*100/k['ascent_efficiency']/3.6e6+2*k['cruise_power_kw']*100/3600+(k['hover_power_kw']+k['comm_power_kw'])*130/3600
        self.assertAlmostEqual(e['energy_kwh'],expected,places=14)
        self.assertAlmostEqual(e['flight_out_s'],125.)
        self.assertAlmostEqual(e['flight_back_s'],100+100/3)
        self.assertEqual(next(p for p in e['phases'] if p['phase']=='back_ascent')['energy_kwh'],0.)

if __name__=='__main__': unittest.main(verbosity=2)
