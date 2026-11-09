"""Parallel preflight must retain serial evidence and propagate input failures."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import os
import sys
import unittest

REPO=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(REPO/'profiles/beihai/parser'),str(REPO/'tools')]
from preflight_beihai_annotations import pipeline_preflight
from beihai_unit_profile import unit_config,configured_paths
from audit_pdms_export import read_csv
from beihai_management import load_management_tables
from project_paths import WORKSPACE


class ParallelPreflightTests(unittest.TestCase):
    def test_serial_and_process_evidence_match(self):
        for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
        config=unit_config('PD73');paths=configured_paths(config,'PD73')
        rows=read_csv(WORKSPACE/'北海项目/焊口表.csv')[0]
        tables=load_management_tables(WORKSPACE/'北海项目',['support']);jobs=[]
        for line in ('50-PA-80103-106','80-CWR-80105-106'):
            jobs.append({'unit':'PD73','line':line,'config':config,'paths_config':paths,
                         'paths':sorted(paths['input_dir'].rglob(line+'_Sht_*.plt')),
                         'rows':[r for r in rows if r['管线号']==line],
                         'tables':{k:dict(t,rows=[r for r in t['rows'] if r['管线号']==line]) for k,t in tables.items()}})
        serial=[pipeline_preflight(job) for job in jobs]
        with ProcessPoolExecutor(max_workers=2) as pool:
            parallel=list(pool.map(pipeline_preflight,jobs))
        self.assertEqual(serial,parallel)
        self.assertTrue(all(result['mapped'] for result in parallel))

    def test_worker_input_error_is_not_a_successful_empty_pipeline(self):
        config=unit_config('PD73');paths=configured_paths(config,'PD73')
        job={'unit':'PD73','line':'nonexistent','config':config,'paths_config':paths,'paths':[],'rows':[],'tables':{}}
        with ProcessPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(FileNotFoundError):pool.submit(pipeline_preflight,job).result(timeout=30)


if __name__=='__main__':unittest.main()
