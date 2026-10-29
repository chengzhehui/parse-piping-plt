"""Actual 193 PD60 spool roots must belong to a component and a native stroke."""
from collections import defaultdict
import json
import math
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from beihai_geometry import load_model,load_page
from beihai_spool_geometry import component_midpoint_anchor
from render_complete_pdms import nearest_point

BASE=ARCHIVE
ROOT=WORKSPACE/'北海项目'


class SpoolMidpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        welds=json.loads((BASE/'beihai_audit/preflight_R9_NRSC_outline_endpoint.json').read_text(encoding='utf-8'))['mapped']
        cls.proofs=[];cls.errors=[]
        for line in sorted({t['pipeline'] for t in welds}):
            local=[w for w in welds if w['pipeline']==line];model=load_model(ROOT/'IDF/PD60'/(line+'.idf'))
            pages={p.stem:load_page(p) for p in (ROOT/'PLT文件转换/PD60').rglob(line+'_Sht_*.plt')}
            groups=defaultdict(list)
            for w in local:
                if w['spool_number']:groups[(w['page_stem'],w['spool_number'])].append(w)
            for (stem,number),members in groups.items():
                try:
                    point,member,proof=component_midpoint_anchor(members,pages[stem],model,[w for w in local if w['page_stem']==stem])
                    actual=next(s for s in pages[stem]['data']['segments'] if s['offset']==proof['native_stroke']['offset'])
                    cls.proofs.append((line,number,point,member,proof,actual))
                except Exception as exc:cls.errors.append((line,number,str(exc)))

    def test_all_193_spools_have_component_roots(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(len(self.proofs),193)
        self.assertTrue(all(p[4]['component_ref'] for p in self.proofs))

    def test_every_root_is_on_the_actual_plt_stroke_and_at_its_piece_midpoint(self):
        for line,number,point,member,proof,actual in self.proofs:
            a,b=[tuple(v/10 for v in actual[key]) for key in ('a','b')]
            _,distance,fraction=nearest_point(point,a,b)
            self.assertLess(distance,1e-7,(line,number));self.assertTrue(0<fraction<1,(line,number))
            aa,bb=proof['usable_segment_mm'];self.assertLess(math.dist(point,[(aa[k]+bb[k])/2 for k in (0,1)]),1e-8)
            self.assertEqual(member['spool_number'],number)

    def test_rolled_pipe_uses_two_port_controls_not_dimension_or_weld_hatch(self):
        case=next(p for p in self.proofs if p[0]=='50-SIO2-66310-201' and p[1]=='B')
        self.assertEqual(case[4]['component_ref'],'LSTU_31181/529')
        self.assertEqual(case[4]['ownership_rule'],'two-mapped-IDF-pipe-ports')
        self.assertGreater(math.dist(case[2],(case[3]['x_mm'],case[3]['y_mm'])),10)


if __name__=='__main__':unittest.main()
