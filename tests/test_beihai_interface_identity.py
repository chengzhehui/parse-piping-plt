"""Stable identity migration must not turn proximity into a weld association."""
from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from beihai_interface_identity import interface_identity,resolve_welds,current_pipe_interior
from beihai_geometry import load_model,load_page
from beihai_unit_profile import unit_config,configured_paths,remap_rows
from audit_pdms_export import read_csv
from project_paths import WORKSPACE


def component(ref,ports,code=100):
    return {'ref':ref,'ports':ports,'code':code,'line':1}


class InterfaceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.old={'components':[component('pipe',[[0,0,0],[1,0,0]]),component('2/3',[[1,0,0],[1,1,0]],35)]}
        self.new={'components':[component('pipe',[[3,0,0],[2,0,0]]),component('2/3',[[2,1,0],[2,0,0]],35)]}

    def test_port_order_can_change(self):
        self.assertEqual(interface_identity([1,0,0],self.old,self.new)[0]['coordinate_mm'],[2,0,0])

    def test_existing_pipe_interior_must_keep_segmentation_semantics(self):
        self.assertTrue(current_pipe_interior([2.5,0,0],self.new))
        self.assertFalse(current_pipe_interior([2.5,1,0],self.new))

    def test_missing_or_changed_owner_is_rejected(self):
        for mutate in ('missing','changed','duplicate'):
            model=copy.deepcopy(self.new)
            if mutate=='missing':model['components'].pop()
            elif mutate=='changed':model['components'][1]['code']=45
            else:model['components'].append(copy.deepcopy(model['components'][1]))
            self.assertEqual(interface_identity([1,0,0],self.old,model),[])

    def test_nonjoining_or_multiple_interfaces_are_rejected(self):
        model=copy.deepcopy(self.new);model['components'][1]['ports']=[[5,0,0],[6,0,0]]
        self.assertEqual(interface_identity([1,0,0],self.old,model),[])
        model['components'][1]['ports']=model['components'][0]['ports']
        self.assertEqual(interface_identity([1,0,0],self.old,model),[])

    def test_real_pipeline_preserves_source_coordinates_and_existing_welds(self):
        config=unit_config('PD20');paths=configured_paths(config,'PD20');line='100-CHS-24101-106-C1'
        rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{**config['pipeline_aliases'],**config['table_pipeline_aliases']})
        rows=[r for r in rows if r['管线号']==line];original=copy.deepcopy(rows)
        model=load_model(paths['idf_dir']/(line+'.idf'))
        pages={p.stem:load_page(p) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
        baseline,_=resolve_welds(rows,model,pages)
        mapped,missing=resolve_welds(rows,model,pages,config,line,'PD20')
        byrow={t['source_row']:t for t in mapped}
        for t in baseline:self.assertEqual(byrow[t['source_row']],t)
        recovered=[t for t in mapped if t.get('interface_identity_evidence')]
        self.assertTrue(recovered)
        for t in recovered:
            self.assertEqual(t['coordinate_mm'],t['source_coordinate_mm'])
            self.assertNotEqual(t['coordinate_mm'],t['model_query_mm'])
            self.assertTrue(t['interface_identity_evidence']['physical_refs_in_hit'])
        self.assertEqual(rows,original)


if __name__=='__main__':unittest.main()
