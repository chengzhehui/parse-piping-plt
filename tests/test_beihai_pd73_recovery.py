"""PD73 native port evidence must survive source glyph removal checks."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from beihai_geometry import load_model,load_page,pipe_endpoint_candidates,resolve_pipe_interiors,beihai_candidates
from beihai_elbow_geometry import curved_elbow_candidates
from beihai_unit_profile import unit_config
from audit_pdms_export import read_csv
from render_complete_pdms import resolve_pipeline


class PD73RecoveryTests(unittest.TestCase):
    fixtures={}

    @classmethod
    def fixture(cls,line):
        if line not in cls.fixtures:
            root=WORKSPACE/'北海项目/PLT文件转换/PD73'
            model=load_model(root/'IDF'/(line+'.idf'),unit_config('PD73')['idf_coordinate_offset_mm'])
            pages={p.stem:load_page(p) for p in (root/'PLT').glob(line+'_Sht_*.plt')}
            cls.fixtures[line]=(model,pages)
        return cls.fixtures[line]

    def test_elbow_other_port_can_be_verified_sheet_boundary(self):
        model,pages=self.fixture('250-CHR-80402-106-C1')
        query={'coordinate_mm':[-1303.58,-31617.24,8482]}
        result=curved_elbow_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(118.1,264.9)])
        self.assertFalse(curved_elbow_candidates(query,model,{s:dict(p,dots=[]) for s,p in pages.items()}))

    def test_stretched_elbow_has_actual_curve_and_weld(self):
        model,pages=self.fixture('50-PA-80103-106');query={'coordinate_mm':[-2040.73,-26540.73,8693.5]}
        result=curved_elbow_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(219.8,367.8)])
        broken={s:dict(p,heavy_segments=[]) for s,p in pages.items()}
        self.assertFalse(curved_elbow_candidates(query,model,broken))

    def test_pipe_face_ambiguity_resolves_only_on_native_axis(self):
        line='250-CHS-80403-106-C1';model,pages=self.fixture(line)
        rows=[r for r in read_csv(WORKSPACE/'北海项目/焊口表.csv')[0] if r['管线号']==line and r['焊点编号']=='4']
        mapped,missing=resolve_pipeline(rows,model,pages,False,beihai_candidates)
        resolve_pipe_interiors(mapped,missing,model,pages)
        self.assertFalse(missing);self.assertEqual(len(mapped),1)
        terminals=mapped[0]['mapping_evidence']['terminals']
        self.assertEqual((terminals[0]['x_mm'],terminals[0]['y_mm']),(123.1,275.8))

    def test_skewed_free_end_needs_degree_one_and_unobstructed_native_stroke(self):
        model,pages=self.fixture('80-CWR-80105-106');q=[6078.68,-26735.75,3113.3]
        result=pipe_endpoint_candidates({'coordinate_mm':q},model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(294.2,387.9)])
        self.assertFalse(pipe_endpoint_candidates({'coordinate_mm':q},dict(model,components=[*model['components'],{'code':105,'ports':[q]}]),pages))
        stem=result[0]['page_stem'];page=pages[stem]
        blocked={**pages,stem:dict(page,hits=[*page['hits'],{'ref':'new-valve','name':'VALVE','x_mm':292.6,'y_mm':381.1}])}
        self.assertFalse(pipe_endpoint_candidates({'coordinate_mm':q},model,blocked))


if __name__=='__main__':unittest.main()
