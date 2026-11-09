"""Native end proofs from FW, EE91 and PD60, with missing-evidence abstention."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import WORKSPACE
from audit_pdms_export import read_csv,coordinate
from beihai_geometry import load_model,load_page,beihai_candidates,resolve_pipe_interiors
from beihai_unit_profile import unit_config,configured_paths,hit_file,verify_configured_alias,remap_rows
from beihai_interface_identity import resolve_welds


class NativeRecoveryTests(unittest.TestCase):
    rows=None

    def fixture(self,unit,line,number):
        if self.rows is None:type(self).rows=read_csv(WORKSPACE/'北海项目/焊口表.csv')[0]
        config=unit_config(unit);paths=configured_paths(config,unit)
        model=load_model(paths['idf_dir']/(line+'.idf'))
        pages={p.stem:load_page(p,hit_file(p,paths['hit_dir'])) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
        row=next(r for r in self.rows if r['管线号']==line and r['焊点编号']==str(number))
        return model,pages,{'coordinate_mm':coordinate(row['焊点位置'])}

    def test_finite_elbow_legs_and_olet_body_need_native_geometry(self):
        for line,number,expected in [('200-PW-73122-106',6,(298.4,60.5)),
                                     ('500-CWS-73201-106',14,(337.5,102.0)),
                                     ('250-FW-73126-108',7,(242.6,191.7))]:
            with self.subTest(line=line):
                model,pages,query=self.fixture('EE73-FW',line,number)
                actual=beihai_candidates(query,model,pages)
                self.assertEqual([(t['x_mm'],t['y_mm']) for t in actual],[expected])
                empty={s:dict(p,heavy_segments=[],dots=[],shapes=[],paths=[]) for s,p in pages.items()}
                self.assertFalse(beihai_candidates(query,model,empty))

    def test_vtsw_hit_is_downstream_native_socket_port(self):
        model,pages,query=self.fixture('EE91','50-PA-91001-106',13)
        result=beihai_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(207.5,129.1)])
        self.assertFalse(beihai_candidates(query,model,{s:dict(p,dots=[],heavy_segments=[]) for s,p in pages.items()}))

    def test_free_end_needs_filled_control_boundary_and_flow_axis(self):
        model,pages,query=self.fixture('EE91','15-PA-91008-106',1)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in beihai_candidates(query,model,pages)],[(171.1,115.0)])
        self.assertFalse(beihai_candidates(query,model,{s:dict(p,flow_axes=[]) for s,p in pages.items()}))
        hollow={s:dict(p,dots=[{k:v for k,v in d.items() if k!='fill_offsets'} for d in p['dots']]) for s,p in pages.items()}
        self.assertFalse(beihai_candidates(query,model,hollow))

    def test_pd60_returning_stub_does_not_invent_short_backwards_cut(self):
        model,pages,query=self.fixture('PD60','40-POW-69701-106',11)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in beihai_candidates(query,model,pages)],[(82.3,58.7)])
        model,pages,query=self.fixture('PD60','40-POW-69701-106',12)
        mapped=[];pending=[query];resolve_pipe_interiors(mapped,pending,model,pages)
        self.assertFalse(mapped)
        self.assertEqual(len(pending),1)

    def test_confirmed_rename_chain_checks_both_models_and_all_coordinates(self):
        unit='PD20';line='25-PA-21001-202';source='25-PA21001-202'
        model,pages,_=self.fixture(unit,line,1)
        config=unit_config(unit)
        rows=[r for r in self.rows if r['管线号']==source]
        proof=verify_configured_alias(config,unit,line,source,model,pages,rows)
        self.assertEqual(proof['coordinate_identity_reference']['weld_rows_checked'],16)
        self.assertEqual(proof['coordinate_identity_reference']['maximum_model_distance_mm'],0)
        with self.assertRaises(ValueError):
            verify_configured_alias(config,unit,line,source,model,{s:dict(p,hits=[]) for s,p in pages.items()},rows)
        remapped=remap_rows([{'管线号':'25-PA-21001-202','_row':1},{'管线号':source,'_row':2}],config['table_pipeline_aliases'])
        self.assertEqual([r['管线号'] for r in remapped],['25-PA-40103-202',line])

    def test_moved_elbow_does_not_interpolate_on_an_unrelated_current_pipe(self):
        config=unit_config('EE73-脱盐水');paths=configured_paths(config,'EE73-脱盐水');line='40-DI-73321-202'
        model=load_model(paths['idf_dir']/(line+'.idf'))
        pages={p.stem:load_page(p) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
        rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{},config['weld_pipeline_transfers'])
        rows=[r for r in rows if r['管线号']==line]
        mapped,missing=resolve_welds(rows,model,pages,config,line,'EE73-脱盐水')
        self.assertFalse(missing);self.assertEqual(len(mapped),8)
        target=next(t for t in mapped if t['number']=='15')
        self.assertEqual((target['x_mm'],target['y_mm']),(150.8,227.6))
        self.assertTrue(target['mapping_method'].startswith('reference-owner-verified:'))
        self.assertEqual(tuple(target['coordinate_mm']),(200,-16422,2650.02))
        self.assertNotEqual(target['model_query_mm'],target['coordinate_mm'])
        removed={s:dict(p,hits=[h for h in p['hits'] if h['ref']!='31185/55369']) for s,p in pages.items()}
        mapped,missing=resolve_welds(rows,model,removed,config,line,'EE73-脱盐水')
        self.assertNotIn('15',{t['number'] for t in mapped})

    def test_fabricated_pipe_ends_need_both_flanges_and_continuous_native_axis(self):
        for line,number,expected in [('80-H2SO4-10496-611',1,(162.6,375.2)),
                                     ('80-H2SO4-10496-611',4,(226.8,338.2)),
                                     ('50-H2SO4-10498-611',1,(314.9,218.9))]:
            model,pages,query=self.fixture('PD10',line,number)
            result=beihai_candidates(query,model,pages)
            self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[expected])
            self.assertEqual(result[0]['evidence'][0]['method'],'beihai-FPFL-slip-on-flanges-native-pipe-ends')
            self.assertFalse(beihai_candidates(query,model,{s:dict(p,heavy_segments=[]) for s,p in pages.items()}))
            other=result[0]['evidence'][0]['flange_refs'][1]
            self.assertFalse(beihai_candidates(query,model,{s:dict(p,hits=[h for h in p['hits'] if h['ref']!=other]) for s,p in pages.items()}))

    def test_gate_valve_ports_use_neighbour_pipe_topology_with_centre_hit(self):
        config=unit_config('PD10');line='25-PA-10302-202';model,pages,_=self.fixture('PD10',line,33)
        rows=[r for r in self.rows if r['管线号']==line]
        mapped,missing=resolve_welds(rows,model,pages,config,line,'PD10')
        ports={t['number']:(t['x_mm'],t['y_mm']) for t in mapped}
        self.assertEqual(ports['33'],(268.5,345.0));self.assertEqual(ports['34'],(264.5,351.9))
        broken={s:dict(p,valve_bodies=[]) for s,p in pages.items()}
        mapped,missing=resolve_welds(rows,model,broken,config,line,'PD10')
        self.assertTrue({'33','34'}<={t['number'] for t in missing})

    def test_tee_third_arm_requires_two_distinct_native_model_port_controls(self):
        model,pages,query=self.fixture('PD10','40-C16-10607-201',34)
        result=beihai_candidates(query,model,pages)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(267.9,333.5)])
        self.assertFalse(beihai_candidates(query,model,{s:dict(p,dots=[]) for s,p in pages.items()}))

    def test_reducer_contour_and_external_pipe_order_both_filled_ports(self):
        config=unit_config('PD20');paths=configured_paths(config,'PD20');line='80-W-W-44103-204'
        model=load_model(paths['idf_dir']/(config['pipeline_aliases'][line]+'.idf'))
        pages={p.stem:load_page(p) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
        rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{**config['pipeline_aliases'],**config['table_pipeline_aliases']},config.get('weld_pipeline_transfers'))
        rows=[r for r in rows if r['管线号']==line]
        mapped,missing=resolve_welds(rows,model,pages,config,line,'PD20')
        self.assertFalse(missing);by={t['number']:t for t in mapped}
        self.assertEqual((by['3']['x_mm'],by['3']['y_mm']),(160.2,239.1))
        self.assertEqual((by['4']['x_mm'],by['4']['y_mm']),(155.4,234.1))
        self.assertEqual((by['5']['x_mm'],by['5']['y_mm']),(314,325.7))
        for n in ['3','4']:self.assertTrue(by[n].get('native_topology_evidence'))
        hollow={s:dict(p,dots=[{k:v for k,v in d.items() if k!='fill_offsets'} for d in p['dots']]) for s,p in pages.items()}
        mapped,missing=resolve_welds(rows,model,hollow,config,line,'PD20')
        self.assertIn('3',{t['number'] for t in missing})
        self.assertFalse(any(t.get('native_topology_evidence') for t in mapped))


if __name__=='__main__':unittest.main()
