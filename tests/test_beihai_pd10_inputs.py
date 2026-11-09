"""PD10 keeps supplied IDF/HIT in separate directories and sanitizes filenames."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from project_paths import WORKSPACE
from beihai_unit_profile import unit_config,configured_paths,hit_file,verify_alias
from beihai_geometry import load_page,load_model
from analyze_plt_bundle import read_hit
from audit_pdms_export import read_csv
from verify_beihai_outputs import load_source_page


class PD10InputTests(unittest.TestCase):
    def test_supplied_model_and_hit_directories(self):
        config=unit_config('PD10');paths=configured_paths(config,'PD10')
        self.assertEqual(config['page_workers'],8)
        self.assertEqual(config['management_kinds'],['support'])
        self.assertFalse(config['spool_annotations'])
        self.assertNotEqual(paths['idf_dir'],WORKSPACE/'北海项目/IDF/PD10')
        plts=list(paths['input_dir'].rglob('*.plt'))
        self.assertTrue(plts)
        self.assertTrue(all(hit_file(p,paths['hit_dir']).is_file() for p in plts))
        self.assertTrue(all((paths['idf_dir']/(p.stem.rsplit('_Sht_',1)[0]+'.idf')).is_file() for p in plts))

    def test_page_uses_separate_hit_not_adjacent_path(self):
        paths=configured_paths(unit_config('PD10'),'PD10')
        path=next(paths['input_dir'].rglob('100-AA-10303-204-C1_Sht_1.plt'))
        self.assertFalse(path.with_suffix('.hit').exists())
        separate=hit_file(path,paths['hit_dir'])
        page=load_page(path,separate)
        self.assertTrue(page['hits'])
        self.assertEqual(page['hits'],read_hit(separate))
        self.assertEqual(load_source_page(path,unit_config('PD10'),'PD10')['hits'],page['hits'])

    def test_filename_aliases_match_idf_identity_and_weld_coordinates(self):
        config=unit_config('PD10');paths=configured_paths(config,'PD10')
        rows=read_csv(WORKSPACE/'北海项目/焊口表.csv')[0];count=0
        for drawing,source in config['table_pipeline_aliases'].items():
            model=load_model(paths['idf_dir']/(drawing+'.idf'))
            pages={p.stem:{'hits':read_hit(p)} for p in paths['hit_dir'].glob(drawing+'_Sht_*.hit')}
            local=[r for r in rows if r['管线号']==source]
            proof=verify_alias(drawing,source,model,pages,local,require_idf_identity=True)
            self.assertEqual(proof['idf_pipeline_identity'],[source])
            self.assertLess(proof['maximum_model_distance_mm'],.011)
            self.assertGreater(proof['entity_uci_count'],30)
            with self.assertRaises(ValueError):verify_alias(drawing,'wrong-pipeline',model,pages,local,require_idf_identity=True)
            count+=proof['weld_rows_checked']
        self.assertEqual(count,103)


if __name__=='__main__':unittest.main()
