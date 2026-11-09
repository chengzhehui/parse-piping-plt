"""PD20 slash naming and its narrowly observed PLT attribute state."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from analyze_plt_bundle import decode_plt
from beihai_geometry import load_model,load_page
from beihai_unit_profile import unit_config,configured_paths,verify_filename_alias,remap_rows,verify_configured_alias
from audit_pdms_export import read_csv


class PD20InputTests(unittest.TestCase):
    def test_current_batch_model_coverage_and_filename_identities(self):
        config=unit_config('PD20');paths=configured_paths(config,'PD20')
        self.assertEqual(config['page_workers'],8)
        self.assertEqual(config['management_kinds'],['support'])
        self.assertFalse(config['spool_annotations'])
        self.assertNotIn('idf_coordinate_offset_mm',config)
        lines={p.stem.rsplit('_Sht_',1)[0] for p in paths['input_dir'].rglob('*.plt')}
        self.assertEqual(len(lines),522)
        for line in lines:
            name=config['pipeline_aliases'].get(line,line)
            self.assertTrue((paths['idf_dir']/(name+'.idf')).is_file())
        self.assertEqual(len(config['table_pipeline_aliases']),27)
        for line,source in config['table_pipeline_aliases'].items():
            filename=config['pipeline_aliases'].get(line,line)
            model=load_model(paths['idf_dir']/(filename+'.idf'))
            if line in config.get('confirmed_pipeline_renames',{}):
                rows=[r for r in read_csv(WORKSPACE/'北海项目/焊口表.csv')[0] if r['管线号']==source]
                pages={p.stem:load_page(p) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
                proof=verify_configured_alias(config,'PD20',line,source,model,pages,rows)
                self.assertEqual(proof['drawing_pipeline'],line)
                with self.assertRaises(ValueError):verify_configured_alias(config,'PD20',line,source,model,{},rows)
            else:
                self.assertTrue(verify_filename_alias(line,source,model,filename)['identity_verified'])
                with self.assertRaises(ValueError):verify_filename_alias(line+'-WRONG',source,model,filename)

    def test_number_tables_are_not_dropped_by_slash_normalization(self):
        config=unit_config('PD20');paths=configured_paths(config,'PD20')
        lines={p.stem.rsplit('_Sht_',1)[0] for p in paths['input_dir'].rglob('*.plt')}
        aliases={**config['pipeline_aliases'],**config['table_pipeline_aliases']}
        rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],aliases,config.get('weld_pipeline_transfers'))
        self.assertEqual(sum(r['管线号'] in lines for r in rows),7317)
        self.assertEqual(sum(r['管线号']=='80-W-W-40101-204' for r in rows),3)

    def test_attribute_state_decodes_entire_page_without_changing_pen(self):
        path=WORKSPACE/'北海项目/PLT文件转换/PD20/PLT/50-DI-44121-202_Sht_2.plt'
        data=decode_plt(path)
        states=[r for r in data['records'] if r['kind']=='setup_2_after_7_zero']
        self.assertEqual([r['offset'] for r in states],[96462,105422])
        self.assertTrue(all(r['from']==r['to'] for r in states))
        self.assertEqual(len(data['segments']),45110)
        self.assertEqual(data['outside_paper_segments'],0)
        self.assertEqual(data['padding_words'],35)

    def test_standalone_attribute_word_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'invalid.plt'
            words=[11,4202,5942,0,2,1]
            p.write_bytes(b'hedape3010261257'+struct.pack('>'+str(len(words))+'H',*words))
            with self.assertRaisesRegex(ValueError,'Unknown command 2'):decode_plt(p)


if __name__=='__main__':unittest.main()
