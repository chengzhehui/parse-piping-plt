"""Page process isolation and deterministic layout versus a serial job."""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from beihai_page_jobs import render_page_job

ROOT=WORKSPACE/'北海项目'


class PageProcessTests(unittest.TestCase):
    def test_parallel_page_job_matches_serial_layout(self):
        path=next((ROOT/'PLT文件转换/PD60').rglob('15-CO2-66902-203_Sht_1.plt'))
        config={'drawing_bounds_mm':[27,27,402,409],'font_height_mm':6.,'weld_diameter_mm':12.,'compact_frames':True}
        target={'key':'test:valve:V1','kind':'valve','pipeline':'15-CO2-66902-203','number':'V1','x_mm':214.5,'y_mm':58.4}
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);serial={'plt_path':str(path),'targets':[target],'config':config,'stage':str(base/'serial')}
            first=render_page_job(serial)
            with ProcessPoolExecutor(max_workers=2) as pool:
                future=pool.submit(render_page_job,dict(serial,stage=str(base/'parallel')))
                second=pool.submit(render_page_job,dict(serial,stage=str(base/'parallel2')))
                result=future.result(timeout=90);other=second.result(timeout=90)
            self.assertNotEqual(result['pid'],os.getpid());self.assertNotEqual(result['pid'],other['pid'])
            self.assertTrue(first['pdf_verified'] and result['pdf_verified'] and other['pdf_verified'])
            layouts=[json.loads((base/name/path.stem/(path.stem+'_layout.json')).read_text(encoding='utf-8'))['placements'] for name in ('serial','parallel','parallel2')]
            self.assertEqual(layouts[0],layouts[1]);self.assertEqual(layouts[1],layouts[2])


if __name__=='__main__':unittest.main()
