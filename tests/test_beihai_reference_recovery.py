from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from beihai_reference_recovery import rigid_owner_points,split_pipe_interface,identity_proposals,free_boundary_identity,directed_owner_points
from beihai_elbow_geometry import extended_leg_elbow_candidates
from beihai_geometry import load_model,load_page
from beihai_geometry import native_axis_covers,beihai_candidates
from beihai_tee_geometry import extended_tee_candidates
from beihai_unit_profile import unit_config,configured_paths


def component(ref,code,ports,line):return {'ref':ref,'code':code,'ports':ports,'line':line}


class ReferenceRecoveryTests(unittest.TestCase):
    def test_free_boundary_may_change_length_with_independent_opposite_owner(self):
        old=component('p',100,[[0,0,0],[10,0,0]],1);new=component('p',100,[[0,2,0],[12,2,0]],2)
        reference={'components':[old,component('1/2',105,[[-1,0,0],[0,0,0]],3)]}
        current={'components':[new,component('1/2',105,[[-1,2,0],[0,2,0]],4)]}
        result=free_boundary_identity([10,0,0],old,new,reference,current,{'1/2'})
        self.assertEqual(result['coordinate_mm'],[12,2,0])
        self.assertIsNone(free_boundary_identity([10,0,0],old,new,reference,current,set()))

    def test_leg_length_changes_require_all_signed_directions(self):
        old=dict(component('1/2',35,[[0,0,1],[1,0,0]],1),skey='ELBW',segments=[{'b':[0,0,0]}])
        new=dict(component('1/2',35,[[2,0,0],[0,0,2]],2),skey='ELBW',segments=[{'b':[0,0,0]}])
        self.assertEqual(directed_owner_points([0,0,1],old,new)[0]['coordinate_mm'],[0,0,2])
        new['ports'][0]=[2,1,0];self.assertEqual(directed_owner_points([0,0,1],old,new),[])
    def test_rigid_translation_requires_entire_body_and_unique_port_order(self):
        a=component('1/2',35,[[0,0,0],[1,1,0]],1)
        b=component('1/2',35,[[3,3,0],[2,2,0]],2)
        self.assertEqual(rigid_owner_points([0,0,0],a,b)[0]['coordinate_mm'],[2,2,0])
        b['ports'][0]=[3,4,0]
        self.assertEqual(rigid_owner_points([0,0,0],a,b),[])
        b['code']=45;self.assertEqual(rigid_owner_points([0,0,0],a,b),[])

    def test_pipe_subdivisions_retain_original_fitting_interface(self):
        pipe=component('LSTU_1/1',100,[[0,0,0],[3,0,0]],1)
        segment=component('LSTU_2/2',100,[[3,0,0],[7,0,0]],2)
        fitting=component('3/3',35,[[7,0,0],[8,1,0]],3)
        model={'components':[pipe,segment,fitting]}
        p=split_pipe_interface(pipe,fitting,model)
        self.assertEqual(p[0]['coordinate_mm'],[7,0,0]);self.assertEqual(len(p[0]['pipe_chain']),2)
        segment['ports'][0]=[3.5,0,0]
        self.assertEqual(split_pipe_interface(pipe,fitting,model),[])

    def test_chain_cannot_cross_bend_or_resolve_two_fitting_ports(self):
        pipe=component('p',100,[[0,0,0],[3,0,0]],1)
        fitting=component('3/3',35,[[3,0,0],[7,0,0]],3)
        second=component('q',100,[[3,0,0],[7,0,0]],2)
        self.assertEqual(split_pipe_interface(pipe,fitting,{'components':[pipe,second,fitting]}),[])
        second['ports']=[[3,0,0],[7,1,0]];fitting['ports']=[[7,1,0],[8,2,0]]
        self.assertEqual(split_pipe_interface(pipe,fitting,{'components':[pipe,second,fitting]}),[])

    def test_duplicate_uci_is_not_identity_evidence(self):
        old={'components':[component('1/2',35,[[0,0,0],[1,1,0]],1)]}
        new={'components':[component('1/2',35,[[2,2,0],[3,3,0]],2),component('1/2',35,[[4,4,0],[5,5,0]],3)]}
        self.assertIsNone(identity_proposals([0,0,0],old,new,{'1/2'}))

    def test_real_extended_elbow_requires_two_first_native_welds(self):
        paths=configured_paths(unit_config('PD20'),'PD20');line='80-VENT-56320-106';stem=line+'_Sht_1'
        model=load_model(paths['idf_dir']/(line+'.idf'));page=load_page(next(paths['input_dir'].rglob(stem+'.plt')))
        target={'coordinate_mm':[5836.6,15452.99,5044.5]}
        candidates=extended_leg_elbow_candidates(target,model,{stem:page})
        self.assertEqual(len(candidates),1);self.assertAlmostEqual(candidates[0]['x_mm'],236.4)
        self.assertAlmostEqual(candidates[0]['y_mm'],150.7)
        missing=dict(page,dots=[d for d in page['dots'] if abs(d['x_mm']-236.4)>.1 or abs(d['y_mm']-150.7)>.1])
        self.assertEqual(extended_leg_elbow_candidates(target,model,{stem:missing}),[])

    def test_long_tee_arm_stops_at_first_weld_and_checks_all_three_arms(self):
        paths=configured_paths(unit_config('PD20'),'PD20');line='80-VENT-56320-106';stem=line+'_Sht_1'
        model=load_model(paths['idf_dir']/(line+'.idf'));page=load_page(next(paths['input_dir'].rglob(stem+'.plt')))
        target={'coordinate_mm':[5836.6,21370,5057.2]}
        result=extended_tee_candidates(target,model,{stem:page},native_axis_covers,beihai_candidates)
        self.assertEqual(len(result),1);self.assertAlmostEqual(result[0]['x_mm'],184)
        self.assertAlmostEqual(result[0]['y_mm'],183.2)
        broken=dict(page,heavy_segments=[],flow_axes=[])
        self.assertEqual(extended_tee_candidates(target,model,{stem:broken},native_axis_covers,beihai_candidates),[])


if __name__=='__main__':unittest.main()
