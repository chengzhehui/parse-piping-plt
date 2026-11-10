"""Native topology must distinguish ports that overlap in model projection."""
from pathlib import Path
import copy,sys,unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'),str(Path(__file__).resolve().parents[1]/'tools')]
from beihai_geometry import load_model,load_page,beihai_candidates,native_axis_covers,pipe_chain_anchors,point_boundary_distance
from beihai_unit_profile import unit_config,configured_paths,remap_rows
from beihai_interface_identity import resolve_welds
from beihai_socket_geometry import socket_outline_candidates
from beihai_tee_geometry import skew_tee_branch_candidates
from beihai_flange_geometry import flange_valve_interface_candidates
from beihai_singleton_geometry import singleton_pipe_candidates
from audit_pdms_export import read_csv
from project_paths import WORKSPACE
from preflight_beihai_annotations import verify_declared_corrections


class NativeTopologyTests(unittest.TestCase):
    def test_coincident_nrsc_and_tee_ports_use_distinct_native_endpoints(self):
        from beihai_port_assignment import owned_ports
        for line,numbers,expected,ref in (
            ('40-POW-89703-202-C1',('9','10'),((327.2,95.3),(313.7,103.1)),'47564/914'),
            ('80-CHS-44101-106-C1',('14','22'),((322.,145.8),(332.,144.3)),'22988/22119'),
            ('80-CHR-44101-106-C1',('13','1'),((173.9,117.5),(181.4,116.5)),'22988/22154')):
            c,m,p=self.pipeline(line)
            rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{**c.get('pipeline_aliases',{}),**c.get('table_pipeline_aliases',{})},c.get('weld_pipeline_transfers'))
            rows=[r for r in rows if r['管线号']==line];original=copy.deepcopy(rows)
            mapped,missing=resolve_welds(rows,m,p,c,line,'PD20');by={t['number']:t for t in mapped}
            self.assertEqual(tuple((by[n]['x_mm'],by[n]['y_mm']) for n in numbers),expected)
            self.assertEqual(rows,original)
            component=next(v for v in m['components'] if v['ref']==ref)
            broken={stem:dict(page,heavy_segments=[]) for stem,page in p.items()}
            self.assertEqual(owned_ports(component,m,broken,mapped),[])
            if component['code']==126:
                broken={stem:dict(page,port_outlines=[]) for stem,page in p.items()}
                self.assertEqual(owned_ports(component,m,broken,mapped),[])
                self.assertEqual(owned_ports(component,m,p,[]),[])

    def test_single_pipe_empty_hit_is_only_resolved_with_one_native_axis(self):
        _,m,p=self.pipeline('50-INI-22002-204');q={'coordinate_mm':[13100,12650,432]}
        result=singleton_pipe_candidates(q,m,p,native_axis_covers)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(366.0,305.8)])
        changed=copy.deepcopy(m);changed['components'].append(copy.deepcopy(changed['components'][-1]))
        self.assertEqual(singleton_pipe_candidates(q,changed,p,native_axis_covers),[])
    def pipeline(self,line):
        config=unit_config('PD20');paths=configured_paths(config,'PD20')
        model=load_model(paths['idf_dir']/(config['pipeline_aliases'].get(line,line)+'.idf'))
        pages={p.stem:load_page(p) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
        return config,model,pages

    def test_skew_check_valve_and_neighbor_elbow_are_bijective(self):
        line='25-PA-21003-202';c,m,p=self.pipeline(line)
        rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{**c['pipeline_aliases'],**c['table_pipeline_aliases']})
        rows=[r for r in rows if r['管线号']==line];original=copy.deepcopy(rows)
        mapped,missing=resolve_welds(rows,m,p,c,line,'PD20');by={t['number']:t for t in mapped}
        for number,point in {'28':(107.1,235.7),'29':(111.1,228.8),'30':(117.8,217.2),'31':(123.8,218.8),'32':(123.8,280.3)}.items():
            self.assertEqual((by[number]['x_mm'],by[number]['y_mm']),point)
        self.assertEqual(rows,original)
        self.assertTrue(by['29']['native_topology_evidence']['connection']['inferred_by_two_port_bijection'])

    def test_skew_tee_needs_connected_native_arms(self):
        _,m,p=self.pipeline('50-CHR-56501-106-C1');q={'coordinate_mm':[-5155.56,11470.4,3100]}
        result=skew_tee_branch_candidates(q,m,p,native_axis_covers,beihai_candidates)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(232.8,83.0)])
        broken={stem:dict(page,heavy_segments=[],flow_axes=[]) for stem,page in p.items()}
        self.assertEqual(skew_tee_branch_candidates(q,m,broken,native_axis_covers,beihai_candidates),[])

    def test_nrsc_pipe_end_requires_real_body_outline(self):
        _,m,p=self.pipeline('80-CHS-44101-106-C1');q={'coordinate_mm':[24965.12,25965.12,1110.79]}
        result=socket_outline_candidates(q,m,p,beihai_candidates,native_axis_covers,pipe_chain_anchors,point_boundary_distance)
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in result],[(322.0,111.8)])
        broken={stem:dict(page,port_outlines=[]) for stem,page in p.items()}
        self.assertEqual(socket_outline_candidates(q,m,broken,beihai_candidates,native_axis_covers,pipe_chain_anchors,point_boundary_distance),[])

    def test_flange_uses_connected_valve_and_actual_plate(self):
        _,m,p=self.pipeline('50-DI-56101-202');q={'coordinate_mm':[4286.78,33109.57,1673]}
        self.assertEqual([(t['x_mm'],t['y_mm']) for t in flange_valve_interface_candidates(q,m,p)],[(245.9,174.1)])
        broken={stem:dict(page,valve_bodies=[]) for stem,page in p.items()}
        self.assertEqual(flange_valve_interface_candidates(q,m,broken),[])

    def test_correction_manifest_never_accepts_an_unlisted_or_changed_root(self):
        old={'page_stem':'P_Sht_1','x_mm':1,'y_mm':2}
        target={'pipeline':'P','number':'1','source_row':10,'page_stem':'P_Sht_1','x_mm':3,'y_mm':4,'native_topology_evidence':{'body':'verified'}}
        change={'old':old,'new':target};declaration={'pipeline':'P','number':'1','source_row':10,'baseline':old,'current':target}
        self.assertEqual(len(verify_declared_corrections([change],[declaration])[0]),1)
        self.assertEqual(len(verify_declared_corrections([change],[])[1]),1)
        wrong=copy.deepcopy(declaration);wrong['current']['x_mm']=3.1
        result=verify_declared_corrections([change],[wrong]);self.assertEqual((len(result[0]),len(result[1]),len(result[2])),(0,1,1))


if __name__=='__main__':unittest.main()
