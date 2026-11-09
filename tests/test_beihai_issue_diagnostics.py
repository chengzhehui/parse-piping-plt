"""Issue reasons must distinguish missing controls from missing native axes."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from beihai_issue_diagnostics import paper_diagnosis


class IssueDiagnosticTests(unittest.TestCase):
    def test_inserted_stub_inside_socket_does_not_prove_another_weld(self):
        model={'components':[{'code':126,'skey':'NRSC','ref':'1/2','line':1,'ports':[(0,0,0),(10,0,0)]},
                             {'code':100,'ref':'P','line':2,'ports':[(3,0,0),(10,0,0)]}]}
        reason=paper_diagnosis({'coordinate_mm':(3,0,0)},model,{'Sht_1':{'hits':[{'ref':'1/2'}]}},lambda *args:[])
        self.assertEqual(reason['category'],'承插插入段端点缺少独立焊口依据')
        self.assertEqual(reason['socket_ref'],'1/2')

    def test_both_controls_exist_but_native_pipe_is_not_continuous(self):
        model={'components':[{'code':100,'ref':'P','line':1,'ports':[(0,0,0),(10,0,0)]}],
               'data':{'splits':[]}}
        pages={'Sht_1':{'hits':[],'heavy_segments':[],'flow_axes':[]}}
        def controls(query,model,pages):
            return [{'page_stem':'Sht_1','x_mm':query['coordinate_mm'][0],'y_mm':0}]
        reason=paper_diagnosis({'coordinate_mm':(5,0,0)},model,pages,controls)
        self.assertEqual(reason['category'],'管内焊口缺少唯一连续管轴')
        self.assertEqual(reason['terminal_candidate_counts'],[1,1])
        self.assertNotIn('弯头未在HIT',reason['reason'])

    def test_present_flange_uci_is_reported_as_port_uncertainty(self):
        model={'components':[{'code':105,'ref':'1/2','skey':'FLWN','line':1,'ports':[(0,0,0),(1,0,0)]}]}
        pages={'Sht_1':{'hits':[{'ref':'1/2'}]}}
        reason=paper_diagnosis({'coordinate_mm':(0,0,0)},model,pages,lambda *args:[])
        self.assertEqual(reason['category'],'法兰端口未能唯一还原')
        self.assertIn('已找到法兰UCI',reason['reason'])


if __name__=='__main__':unittest.main()
