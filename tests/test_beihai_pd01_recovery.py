"""Verified native evidence must recover cuts while rejecting missing fittings."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from beihai_geometry import load_model,load_page,native_axis_covers,plain_pipe_terminal,resolve_pipe_interiors,beihai_candidates
from beihai_elbow_geometry import curved_elbow_candidates
from render_complete_pdms import resolve_pipeline
from audit_pdms_export import read_csv


class PD01RecoveryTests(unittest.TestCase):
    fixtures={}

    @classmethod
    def fixture(cls,line):
        if line not in cls.fixtures:
            folder=WORKSPACE/'北海项目'
            model=load_model(folder/'IDF/PD01'/(line+'.idf'))
            pages={p.stem:load_page(p) for p in (folder/'PLT文件转换/PD01').rglob(line+'_Sht_*.plt')}
            cls.fixtures[line]=(model,pages)
        return cls.fixtures[line]

    def test_crossing_knockout_requires_actual_crossing_stroke(self):
        _,pages=self.fixture('80-WW-01005-201');page=pages['80-WW-01005-201_Sht_3'];proof=[]
        self.assertTrue(native_axis_covers(page,(133.3,225.7),(197.3,188.8),proof))
        self.assertEqual(len(proof),1)
        crossing=proof[0]['crossing_offset']
        broken=dict(page,heavy_segments=[s for s in page['heavy_segments'] if s['offset']!=crossing])
        self.assertFalse(native_axis_covers(broken,(133.3,225.7),(197.3,188.8)))

    def test_added_valve_is_not_a_drawing_only_gap(self):
        _,pages=self.fixture('100-DI-01001-202')
        self.assertFalse(native_axis_covers(pages['100-DI-01001-202_Sht_2'],(286.8,252.),(335.4,280.)))

    def test_curved_elbow_requires_native_welded_ports(self):
        model,pages=self.fixture('250-CHR-01001-106-C1');query={'coordinate_mm':[135575.,178950.,26467.5]}
        result=curved_elbow_candidates(query,model,pages)
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['x_mm'],result[0]['y_mm']),(336.8,221.3))
        self.assertFalse(curved_elbow_candidates(query,model,{s:dict(p,dots=[]) for s,p in pages.items()}))

    def test_unplotted_supports_allow_only_collinear_pipe_chains(self):
        line='150-LSTM-01001-106-H2';model,pages=self.fixture(line)
        rows=[r for r in read_csv(WORKSPACE/'北海项目/焊口表.csv')[0] if r['管线号']==line and r['焊点编号']=='18']
        mapped,missing=resolve_pipeline(rows,model,pages,False,beihai_candidates)
        resolve_pipe_interiors(mapped,missing,model,pages)
        self.assertFalse(missing);self.assertEqual(len(mapped),1)
        self.assertAlmostEqual(mapped[0]['x_mm'],307.5165333333,places=5)
        self.assertTrue(all(t.get('pipe_chain_refs') for t in mapped[0]['mapping_evidence']['terminals']))

    def test_open_end_rejects_new_fitting_or_non_boundary(self):
        model,pages=self.fixture('50-IWW-01001-203')
        component=next(c for c in model['components'] if c['ref']=='LSTU_22985/3091');a,b=component['ports']
        result=plain_pipe_terminal(b,a,component,model,pages)
        self.assertEqual([(c['x_mm'],c['y_mm']) for c in result],[(346.9,150.6)])
        stem=result[0]['page_stem'];page=pages[stem]
        obstruction={'ref':'unmodelled-valve','name':'VALVE 1','x_mm':325.,'y_mm':163.25}
        changed={**pages,stem:dict(page,hits=[*page['hits'],obstruction])}
        self.assertFalse(plain_pipe_terminal(b,a,component,model,changed))
        changed_model=dict(model,components=[*model['components'],{'code':105,'ports':[b]}])
        self.assertFalse(plain_pipe_terminal(b,a,component,changed_model,pages))


if __name__=='__main__':unittest.main()
