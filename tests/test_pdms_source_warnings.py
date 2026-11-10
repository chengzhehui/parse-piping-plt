"""Source FAIL strokes must be reported without changing native graphics."""
import copy
from pathlib import Path
import sys
import unittest
from openpyxl import Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from analyze_plt_bundle import decode_plt
from beihai_unit_profile import unit_config,configured_paths
from pdms_source_warnings import native_source_warnings
from beihai_review_report import reviewer_workbook


class SourceWarningTests(unittest.TestCase):
    def test_real_fail_banner_and_incomplete_or_normal_graphics(self):
        root=configured_paths(unit_config('PD20'),'PD20')['input_dir']
        source=next(root.rglob('50-AFRA-56504-201_Sht_1.plt'))
        data=decode_plt(source);original=copy.deepcopy(data)
        warnings=native_source_warnings(data)
        self.assertEqual(len(warnings),1)
        self.assertEqual(warnings[0]['source_sha256'],data['sha256'])
        self.assertEqual(data,original)
        missing_stroke=copy.deepcopy(data)
        missing_stroke['records']=[r for r in data['records'] if r['offset']!=94142]
        self.assertEqual(native_source_warnings(missing_stroke),[])
        normal=decode_plt(next(root.rglob('40-POW-89703-202-C1_Sht_1.plt')))
        self.assertEqual(native_source_warnings(normal),[])
        wb=Workbook();wb.remove(wb.active)
        for name in ('未标注编号','标注定位清单','自动匹配需审核'):wb.create_sheet(name).append(['header'])
        public=reviewer_workbook(wb,{'source_drawing_issues':[dict(warnings[0],page_stem=source.stem)]})
        row=list(public['已标注需核对'].values)[1]
        self.assertEqual(row[0],source.stem)
        self.assertEqual(row[5],source.name)
        self.assertIn('FAIL',row[4])


if __name__=='__main__':unittest.main()
