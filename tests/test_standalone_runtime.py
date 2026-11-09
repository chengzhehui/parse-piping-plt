"""Portable checks for independent layout imports and generic table scope."""
from pathlib import Path
import subprocess
import sys
import unittest

PARSER=Path(__file__).resolve().parents[1]/'profiles/beihai/parser'
sys.path.insert(0,str(PARSER))
from beihai_management import resolve_management
from beihai_valve_geometry import valve_body_center


class StandaloneRuntimeTests(unittest.TestCase):
    def test_layout_imports_without_sha_project(self):
        code=f"import sys; sys.path.insert(0,{str(PARSER)!r}); import pdms_unified_layout; assert 'inject_sha_weld_callouts' not in sys.modules; assert 'sha_to_svg_prototype' not in sys.modules; assert not any('parse-piping-sha' in p for p in sys.path)"
        result=subprocess.run([sys.executable,'-B','-I','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_generic_scope_preserves_source_units_and_explicit_filter(self):
        rows=[{'管线号':'L','单元号':unit,'支架编号':number,'UCI':ref,'_row':i,'页码':'1'}
              for unit,number,ref,i in [('A','SP1','1/1',2),('B','SP2','1/2',3)]]
        tables={'support':{'file':'supports.csv','column':'支架编号','rows':rows}}
        page={'hits':[{'ref':r['UCI'],'name':'SUPPORT','x_mm':i,'y_mm':0} for i,r in enumerate(rows)],'hit_offset_mm':(0,0)}
        model={'components':[]}
        mapped,issues,audit,_,_=resolve_management(tables,'L',{'L_Sht_1':page},model,None)
        self.assertFalse(issues);self.assertEqual(len(mapped),2)
        self.assertEqual([r[0] for r in audit],['A','B'])
        selected,*_=resolve_management(tables,'L',{'L_Sht_1':page},model,'A')
        self.assertEqual([t['number'] for t in selected],['SP1'])

    def test_valve_center_hit_and_terminal_hit_select_same_body_center(self):
        component={'code':130,'skey':'VBFL','ports':[(0,0,0),(0,0,10)]}
        body={'a':(0,0),'b':(0,8),'center':(0,4),'shape':'bowtie-valve','offset':1}
        page={'valve_bodies':[body]}
        for y in (4,8):
            actual=valve_body_center(component,{'x_mm':0,'y_mm':y},page)
            self.assertEqual(actual['center'],(0,4))
        neighbour=dict(body,a=(0,4),b=(0,12),center=(0,8),offset=2)
        self.assertEqual(valve_body_center(component,{'x_mm':0,'y_mm':8},{'valve_bodies':[body,neighbour]})['center'],(0,4))
        ambiguous={'valve_bodies':[body,dict(body,offset=2)]}
        with self.assertRaises(ValueError):valve_body_center(component,{'x_mm':0,'y_mm':4},ambiguous)


if __name__=='__main__':unittest.main()
