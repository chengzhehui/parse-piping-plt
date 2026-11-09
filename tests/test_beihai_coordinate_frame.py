"""Coordinate-frame correction needs independent UCI evidence, not nearest welds."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from beihai_geometry import load_model
from beihai_unit_profile import unit_config,configured_paths,validate_coordinate_frame


class CoordinateFrameTests(unittest.TestCase):
    def test_translation_preserves_topology_and_native_records(self):
        config=unit_config('PD73');paths=configured_paths(config,'PD73')
        path=paths['idf_dir']/'100-PA-80107-106.idf'
        original=load_model(path);model=load_model(path,config['idf_coordinate_offset_mm'])
        self.assertEqual(model['data']['logical_records'],original['data']['logical_records'])
        self.assertEqual(model['idf_origin_mm'],(-110000,-56000,0))
        self.assertEqual(model['origin_mm'],(200,600,200))
        self.assertEqual(len(model['components']),len(original['components']))
        for a,b in zip(original['components'],model['components']):
            self.assertEqual((a['ref'],a['code']),(b['ref'],b['code']))
            for p,q in zip(a['ports'],b['ports']):
                self.assertLess(math.dist(q,[p[k]+config['idf_coordinate_offset_mm'][k] for k in range(3)]),1e-6)

    def test_offset_requires_multiple_independent_uci_anchors(self):
        config=unit_config('PD73');paths=configured_paths(config,'PD73')
        proof=validate_coordinate_frame(config,paths['idf_dir'],WORKSPACE/'北海项目','PD73')
        self.assertGreaterEqual(proof['agreeing_pipelines'],20)
        self.assertGreaterEqual(proof['agreeing_anchors']/proof['anchor_count'],.9)
        self.assertGreater(proof['anchor_count'],100)
        with self.assertRaisesRegex(ValueError,'未通过独立UCI校验'):
            validate_coordinate_frame(dict(config,idf_coordinate_offset_mm=[110200,56600,400]),paths['idf_dir'],WORKSPACE/'北海项目','PD73')

    def test_invalid_transform_is_rejected(self):
        path=configured_paths(unit_config('PD73'),'PD73')['idf_dir']/'100-PA-80107-106.idf'
        for offset in ([1,2],[0,0,float('nan')]):
            with self.assertRaises(ValueError):load_model(path,offset)


if __name__=='__main__':unittest.main()
