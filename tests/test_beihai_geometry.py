"""Real PD60 regressions for origin translation, compressed legs and abstention."""
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from analyze_plt_bundle import read_export_text
from beihai_geometry import load_model,load_page,beihai_candidates,native_axis_covers,unresolved_diagnosis

ROOT=WORKSPACE/'北海项目'


class BeihaiGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'IDF/PD60/50-SIO2-66906-201.idf'
        cls.model=load_model(cls.path)
        source=next((ROOT/'PLT文件转换/PD60').rglob('50-SIO2-66906-201_Sht_1.plt'))
        cls.pages={source.stem:load_page(source)}

    def test_origin_comes_from_record_not_fixed_project_constant(self):
        source=read_export_text(self.path)
        lines=source.splitlines()
        index=next(i for i,s in enumerate(lines) if s.split() and s.split()[0]=='300')
        fields=lines[index].split();self.assertEqual(fields[1],'48')
        lines[index]=lines[index].replace('48','49',1)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'shifted.idf';p.write_text('\n'.join(lines),encoding='utf-8')
            changed=load_model(p)
        self.assertEqual(changed['origin_mm'],(49000,28000,0))
        a=self.model['components'][0]['ports'][0];b=changed['components'][0]['ports'][0]
        self.assertAlmostEqual(b[0]-a[0],1000)
        self.assertEqual(a[1:],b[1:])

    def test_weld_neck_flange_uses_native_terminal(self):
        candidates=beihai_candidates({'coordinate_mm':(52520.99,22283,3430.15)},self.model,self.pages)
        self.assertAlmostEqual(candidates[0]['x_mm'],358.1,places=1)
        self.assertAlmostEqual(candidates[0]['y_mm'],181.5,places=1)

    def test_compressed_tee_leg_is_fifteen_mm_not_nine(self):
        candidates=beihai_candidates({'coordinate_mm':(52520.99,33309.6,3430.15)},self.model,self.pages)
        self.assertAlmostEqual(candidates[0]['x_mm'],192,places=1)
        self.assertAlmostEqual(candidates[0]['y_mm'],277.4,places=1)
        self.assertTrue(any(e['method']=='beihai-tee-connected-native-leg' for e in candidates[0]['evidence']))

    def test_missing_hit_is_not_replaced_with_guessed_coordinate(self):
        model=load_model(ROOT/'IDF/PD60/80-WW-66301-201.idf')
        source=next((ROOT/'PLT文件转换/PD60').rglob('80-WW-66301-201_Sht_1.plt'))
        pages={source.stem:load_page(source)}
        candidates=beihai_candidates({'coordinate_mm':(52900.99,33894.9,3444.45)},model,pages)
        self.assertEqual(candidates,[])

    def test_filled_butt_weld_and_flow_bridge(self):
        model=load_model(ROOT/'IDF/PD60/15-CO2-66902-203.idf')
        source=next((ROOT/'PLT文件转换/PD60').rglob('15-CO2-66902-203_Sht_1.plt'));page=load_page(source)
        candidates=beihai_candidates({'coordinate_mm':(52361,27768,3392.15)},model,{source.stem:page})
        self.assertEqual((candidates[0]['x_mm'],candidates[0]['y_mm']),(214.5,387.7))
        self.assertTrue(native_axis_covers(page,(214.5,64.4),(214.5,387.7)))
        without_flow=dict(page,flow_axes=[])
        self.assertFalse(native_axis_covers(without_flow,(214.5,64.4),(214.5,387.7)))

    def test_compound_reference_does_not_attach_to_previous_weld(self):
        model=load_model(ROOT/'IDF/PD60/25-PA-60002-106.idf')
        fitting=next(c for c in model['components'] if c['ref']=='22989/3717')
        self.assertEqual(fitting['code'],95)
        source=next((ROOT/'PLT文件转换/PD60').rglob('25-PA-60002-106_Sht_1.plt'));pages={source.stem:load_page(source)}
        ends=[beihai_candidates({'coordinate_mm':q},model,pages)[0] for q in fitting['ports']]
        self.assertEqual([(e['x_mm'],e['y_mm']) for e in ends],[(88.9,55.1),(87.7,53)])

    def test_idf_126_keeps_its_own_reference_and_reports_backfold(self):
        model=load_model(ROOT/'IDF/PD60/40-POW-69701-106.idf')
        self.assertEqual(next(c for c in model['components'] if c['ref']=='31181/442')['code'],35)
        self.assertEqual(next(c for c in model['components'] if c['ref']=='31181/441')['code'],126)
        diagnosis=unresolved_diagnosis({'coordinate_mm':(49111,20600,688)},model)
        self.assertIn('32.00mm',diagnosis['reason'])
        source=next((ROOT/'PLT文件转换/PD60').rglob('40-POW-69701-106_Sht_1.plt'))
        candidates=beihai_candidates({'coordinate_mm':(49143,20600,688)},model,{source.stem:load_page(source)})
        self.assertEqual((candidates[0]['x_mm'],candidates[0]['y_mm']),(82.3,58.7))

    def test_missing_elbow_hit_recovers_only_connected_native_weld(self):
        model=load_model(ROOT/'IDF/PD60/50-PW-66301-202.idf')
        source=next((ROOT/'PLT文件转换/PD60').rglob('50-PW-66301-202_Sht_1.plt'));pages={source.stem:load_page(source)}
        candidates=beihai_candidates({'coordinate_mm':(52268,31140.9,149.99)},model,pages)
        self.assertEqual((candidates[0]['x_mm'],candidates[0]['y_mm']),(338.2,106.8))
        self.assertEqual(candidates[0]['evidence'][0]['method'],'beihai-unlisted-elbow-connected-thick-paths')


if __name__=='__main__':unittest.main()
