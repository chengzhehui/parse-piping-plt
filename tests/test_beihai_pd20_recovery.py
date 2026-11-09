"""Real PD20 endpoint and shallow-arc evidence, including abstention checks."""
from pathlib import Path
import math
import copy
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from beihai_geometry import load_model,load_page,beihai_candidates,explicit_pipe_weld_candidates
from beihai_elbow_geometry import curved_elbow_candidates,boundary_elbow_candidates
from beihai_flange_geometry import flange_pipe_candidates
from audit_pdms_export import read_csv,coordinate
from beihai_management import load_management_tables,resolve_management


class PD20RecoveryTests(unittest.TestCase):
    fixtures={};rows=None

    @classmethod
    def fixture(cls,line,number):
        if cls.rows is None:cls.rows=read_csv(WORKSPACE/'北海项目/焊口表.csv')[0]
        if line not in cls.fixtures:
            root=WORKSPACE/'北海项目/PLT文件转换/PD20/PLT'
            cls.fixtures[line]=(load_model(root/(line+'.idf')),
                                {p.stem:load_page(p) for p in root.glob(line+'_Sht_*.plt')})
        model,pages=cls.fixtures[line]
        row=next(r for r in cls.rows if r['管线号']==line and r['焊点编号']==str(number))
        return model,pages,{'coordinate_mm':coordinate(row['焊点位置'])}

    def test_short_arc_ports_and_original_strict_port_are_preserved(self):
        for line,number,expected in [('100-PLM-21805-204',6,(188.6,162.6)),
                                     ('100-PLM-21805-204',7,(192.2,177.2)),
                                     ('150-CHR-23396-106-C1',3,(298.5,372.9)),
                                     ('80-CHR-21102-106-C1',2,(73.8,91.6))]:
            model,pages,query=self.fixture(line,number)
            result=curved_elbow_candidates(query,model,pages)
            self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[expected])

    def test_direct_free_endpoint_uses_real_native_pipe_end(self):
        model,pages,query=self.fixture('100-CHR-24102-106-C1',28)
        result=beihai_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(113.1,142.2)])
        changed=dict(model,components=[*model['components'],{'code':105,'ref':'test-added-flange','ports':[query['coordinate_mm']]}])
        self.assertFalse(beihai_candidates(query,changed,pages))

    def test_explicit_free_end_needs_120_weld_glyph_and_flow_axis(self):
        model,pages,query=self.fixture('15-IA-23381-202',1)
        result=explicit_pipe_weld_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(233.7,387.7)])
        removed=dict(model,components=[c for c in model['components'] if c['code']!=120])
        self.assertFalse(explicit_pipe_weld_candidates(query,removed,pages))
        self.assertFalse(explicit_pipe_weld_candidates(query,model,{s:dict(p,dots=[]) for s,p in pages.items()}))
        self.assertFalse(explicit_pipe_weld_candidates(query,model,{s:dict(p,flow_axes=[]) for s,p in pages.items()}))
        stem=result[0]['page_stem'];page=pages[stem]
        obstruction={'ref':'new-valve','name':'VALVE','x_mm':233.7,'y_mm':300.0}
        blocked={**pages,stem:dict(page,hits=[*page['hits'],obstruction])}
        self.assertFalse(explicit_pipe_weld_candidates(query,model,blocked))

    def test_flow_arrow_tip_is_not_mistaken_for_free_pipe_end(self):
        model,pages,query=self.fixture('50-N2-81202-106',1)
        result=beihai_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(109.1,315.0)])
        no_flow={s:dict(p,flow_axes=[]) for s,p in pages.items()}
        self.assertFalse(beihai_candidates(query,model,no_flow))

    def test_dashed_flange_port_needs_independent_other_pipe_control(self):
        model,pages,query=self.fixture('25-DI-21201-202',14)
        result=flange_pipe_candidates(query,model,pages,beihai_candidates)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(372.7,242.3)])
        ref=result[0]['evidence'][0]['ref']
        no_controls={s:dict(p,hits=[h for h in p['hits'] if h['ref']==ref]) for s,p in pages.items()}
        self.assertFalse(flange_pipe_candidates(query,model,no_controls,beihai_candidates))

    def test_boundary_elbow_needs_other_sheet_and_actual_open_leg(self):
        model,pages,query=self.fixture('100-EMUL-23004-204',9)
        result=boundary_elbow_candidates(query,model,pages,beihai_candidates)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(268.3,42.8)])
        stem=result[0]['page_stem'];page=pages[stem]
        self.assertFalse(boundary_elbow_candidates(query,model,{stem:page},beihai_candidates))
        extension={'a':(268.3,42.8),'b':(260.0,44.0),'offset':-1,'stroke_count':4}
        connected={**pages,stem:dict(page,heavy_segments=[*page['heavy_segments'],extension])}
        self.assertFalse(boundary_elbow_candidates(query,model,connected,beihai_candidates))

    def test_support_duplicate_keeps_existing_valid_source_uci(self):
        model,pages,_=self.fixture('25-PA-44102-202',1)
        tables=load_management_tables(WORKSPACE/'北海项目',['support'])
        tables['support']['rows']=[r for r in tables['support']['rows'] if r['管线号']=='25-PA-44102-202' and r['支架编号']=='SP4']
        mapped,missing,audit,_,counts=resolve_management(tables,'25-PA-44102-202',pages,model,'PD20')
        self.assertFalse(missing);self.assertEqual(len(mapped),1)
        proof=mapped[0]['duplicate_support_evidence']
        self.assertEqual(proof['active_source_refs'],['22988/35434'])
        self.assertEqual(proof['inactive_duplicate_refs'],['22988/35422'])
        self.assertEqual(set(mapped[0]['source_rows']),{1319,1320})
        self.assertEqual({r[6] for r in audit},{1319,1320})
        changed=copy.deepcopy(tables);changed['support']['rows'][0]['材料代码']='OTHER'
        self.assertFalse(resolve_management(changed,'25-PA-44102-202',pages,model,'PD20')[0])
        changed=copy.deepcopy(tables);changed['support']['rows'][0]['支架坐标']='20708,15950,4750'
        self.assertFalse(resolve_management(changed,'25-PA-44102-202',pages,model,'PD20')[0])
        changed=copy.deepcopy(tables);changed['support']['rows']=changed['support']['rows'][:1]
        self.assertFalse(resolve_management(changed,'25-PA-44102-202',pages,model,'PD20')[0])
        moved=copy.deepcopy(model)
        component=next(c for c in moved['components'] if c['ref']=='22988/35434')
        component['ports']=[(p[0]+10,p[1],p[2]) for p in component['ports']]
        mapped,_,_,review,_=resolve_management(tables,'25-PA-44102-202',pages,moved,'PD20')
        self.assertEqual(len(mapped),1)
        self.assertTrue(any('坐标与IDF端点相差' in r[6] for r in review))


if __name__=='__main__':unittest.main()
