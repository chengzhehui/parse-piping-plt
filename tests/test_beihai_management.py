"""Actual PD60 grouped-flange and coincident-support source regressions."""
import copy
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from analyze_plt_bundle import read_hit,decode_plt
from beihai_valve_geometry import native_valve_bodies
from beihai_management import load_management_tables,resolve_management
from beihai_geometry import load_model

ROOT=WORKSPACE/'北海项目'


class ManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables=load_management_tables(ROOT);cls.pages={}
        for p in (ROOT/'PLT文件转换/PD60').rglob('*.hit'):
            cls.pages[p.stem]={'hits':read_hit(p),'hit_offset_mm':(0,0),
                               'valve_bodies':native_valve_bodies(decode_plt(p.with_suffix('.plt')))}

    def resolve(self,line,pages=None):
        local=pages or {s:p for s,p in self.pages.items() if s.rsplit('_Sht_',1)[0]==line}
        return resolve_management(self.tables,line,local,load_model(ROOT/'IDF/PD60'/(line+'.idf')),'PD60')

    def test_all_actual_source_rows_accounted_for(self):
        counts={};audit_rows=0
        for line in sorted({s.rsplit('_Sht_',1)[0] for s in self.pages}):
            _,_,audit,_,local=self.resolve(line);audit_rows+=len(audit)
            for k,v in local.items():counts[k]=counts.get(k,0)+v
        self.assertEqual(audit_rows,377)
        self.assertEqual([counts['mapped_'+k] for k in ('valve','flange','support')],[81,182,108])
        self.assertEqual(counts['merged_support_rows'],4)
        self.assertEqual(counts['unresolved_flange'],2)

    def test_semicolon_group_targets_actual_flange_once(self):
        targets,_,_,_,_=self.resolve('25-H2SO4-66208-106B')
        target=next(t for t in targets if t['kind']=='flange' and t['number']=='FL3')
        self.assertEqual(set(target['ref'].split(';')),{'22989/2179','22989/2031'})
        self.assertEqual((target['x_mm'],target['y_mm']),(187.9,352.6))

    def test_coincident_support_rows_are_retained_and_labelled_once(self):
        targets,_,audit,_,_=self.resolve('25-H2SO4-66208-106B')
        targets=[t for t in targets if t['kind']=='support' and t['number']=='SP4']
        self.assertEqual(len(targets),1);self.assertEqual(len(targets[0]['source_rows']),2)
        self.assertEqual(sum(r[4]=='SP4' and r[3]=='支架' for r in audit),2)

    def test_duplicate_number_at_distinct_positions_is_not_merged(self):
        pages=copy.deepcopy({s:p for s,p in self.pages.items() if s.startswith('25-H2SO4-66208-106B_Sht_')})
        for p in pages.values():
            for h in p['hits']:
                if h['ref']=='22989/4471':h['x_mm']+=10
        targets,issues,_,_,_=self.resolve('25-H2SO4-66208-106B',pages)
        self.assertFalse(any(t['kind']=='support' and t['number']=='SP4' for t in targets))
        self.assertTrue(any(r[2]=='支架' and r[3]=='SP4' and '不同位置' in r[4] for r in issues))

    def test_valves_land_at_body_centres_not_HIT_or_adjacent_flange(self):
        targets,_,_,_,_=self.resolve('50-SIO2-66906-201')
        valves={t['number']:t for t in targets if t['kind']=='valve'}
        self.assertEqual((valves['V1']['x_mm'],valves['V1']['y_mm']),(333.2,155.3))
        self.assertEqual((valves['V4']['x_mm'],valves['V4']['y_mm']),(179.,240.6))

    def test_check_valve_uses_its_body_not_neighbouring_bowtie(self):
        targets,_,_,_,_=self.resolve('80-PW-66811-202')
        valve=next(t for t in targets if t['kind']=='valve' and t['number']=='V2')
        self.assertAlmostEqual(valve['x_mm'],315.25,places=2)
        self.assertAlmostEqual(valve['y_mm'],197.2,places=2)

    def test_adjacent_inline_valves_are_disambiguated_by_IDF_direction(self):
        targets,_,_,_,_=self.resolve('40-H2SO4-66201-106B')
        valves={t['number']:t for t in targets if t['kind']=='valve'}
        self.assertEqual((valves['V2']['x_mm'],valves['V2']['y_mm']),(345.65,183.4))
        self.assertEqual((valves['V3']['x_mm'],valves['V3']['y_mm']),(353.55,178.8))


if __name__=='__main__':unittest.main()
