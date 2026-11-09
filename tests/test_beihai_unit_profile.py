"""PD01 name differences require corroborated model and drawing identities."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from beihai_unit_profile import unit_config,remap_rows,verify_alias
from beihai_geometry import load_model
from audit_pdms_export import read_csv
from analyze_plt_bundle import read_hit
from project_paths import WORKSPACE


class UnitProfileTests(unittest.TestCase):
    def test_pd01_defaults_and_source_rows(self):
        config=unit_config('PD01')
        self.assertEqual(config['page_workers'],8)
        self.assertFalse(config['spool_annotations'])
        self.assertEqual(config['management_kinds'],['support'])
        rows=[{'管线号':'40-POW-01006-106-C1','_row':42}]
        mapped=remap_rows(rows,config['pipeline_aliases'])
        self.assertEqual(mapped[0],{'管线号':'40-POW-01006-202-C1','_row':42})
        self.assertEqual(rows[0]['管线号'],'40-POW-01006-106-C1')

    def test_ambiguous_source_identity_is_rejected(self):
        with self.assertRaises(ValueError):remap_rows([{'管线号':'A'},{'管线号':'B'}],{'A':'B'})
        self.assertEqual(remap_rows([{'管线号':'A'}],{'A':'B'}),[{'管线号':'A'}])
        with self.assertRaises(ValueError):remap_rows([],{'A':'C','B':'C'})

    def test_explicit_rename_chain_preserves_each_source_row(self):
        rows=[{'管线号':'A','_row':1},{'管线号':'B','_row':2}]
        self.assertEqual(remap_rows(rows,{'A':'B','C':'A'}),
                         [{'管线号':'C','_row':1},{'管线号':'A','_row':2}])
        self.assertEqual(remap_rows(rows,{'A':'B','B':'A'}),
                         [{'管线号':'B','_row':1},{'管线号':'A','_row':2}])
        self.assertEqual(rows[0]['管线号'],'A')

    def test_row_transfer_is_pinned_to_original_identity_and_coordinate(self):
        row={'管线号':'A','_row':7,'焊点编号':'15','焊点位置':'1,2,3'}
        transfer={'source_row':7,'source_pipeline':'A','drawing_pipeline':'B','number':'15','source_coordinate_mm':[1,2,3]}
        mapped=remap_rows([row],{},[transfer])[0]
        self.assertEqual(mapped['管线号'],'B')
        self.assertEqual(mapped['焊点位置'],'1,2,3')
        self.assertEqual(row['管线号'],'A')
        for changed in [dict(row,焊点编号='16'),dict(row,焊点位置='1,2,4'),dict(row,管线号='C')]:
            with self.assertRaises(ValueError):remap_rows([changed],{},[transfer])
        with self.assertRaises(ValueError):remap_rows([],{},[transfer])

    def test_support_transfer_also_requires_the_original_uci(self):
        row={'管线号':'A','_row':7,'支架编号':'SP1','支架坐标':'1,2,3','UCI':'1/2'}
        transfer={'kind':'support','source_row':7,'source_pipeline':'A','drawing_pipeline':'B','number':'SP1','source_coordinate_mm':[1,2,3],'ref':'1/2'}
        self.assertEqual(remap_rows([row],{},[transfer])[0]['管线号'],'B')
        with self.assertRaises(ValueError):remap_rows([dict(row,UCI='1/3')],{},[transfer])

    def test_pd01_actual_alias_and_missing_uci(self):
        root=WORKSPACE/'北海项目';drawing='40-POW-01006-202-C1';source='40-POW-01006-106-C1'
        model=load_model(root/'IDF/PD01'/(source+'.idf'))
        rows=[r for r in read_csv(root/'焊口表.csv')[0] if r['管线号']==source]
        page={'hits':read_hit(root/'PLT文件转换/PD01/PLT'/(drawing+'_Sht_1.hit'))}
        proof=verify_alias(drawing,source,model,{'page':page},rows)
        self.assertEqual(proof['entity_uci_count'],9)
        self.assertEqual(proof['weld_rows_checked'],21)
        self.assertLess(proof['maximum_model_distance_mm'],.001)
        with self.assertRaises(ValueError):verify_alias(drawing,source,model,{'page':{'hits':[]}},rows)


if __name__=='__main__':unittest.main()
