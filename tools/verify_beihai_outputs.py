"""Check delivered single pages against source weld rows and the issue workbook."""
import argparse
import json
import math
from collections import Counter,defaultdict
from pathlib import Path
import fitz
from openpyxl import load_workbook
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from audit_pdms_export import read_csv,coordinate
from beihai_management import LABEL_NAMES,load_management_tables
from beihai_review_report import audit_path
from analyze_plt_bundle import decode_plt,read_hit
from beihai_geometry import load_model,load_page
from beihai_interface_identity import interface_identity,current_pipe_interior
from beihai_reference_recovery import identity_proposals
from beihai_topology_ports import native_ports
from beihai_geometry import native_axis_covers
from beihai_singleton_geometry import singleton_pipe_candidates
from beihai_unit_profile import remap_rows,unit_config,configured_paths,hit_file,reference_idf_path


def load_source_page(path,config,unit):
    return load_page(path,hit_file(path,configured_paths(config,unit)['hit_dir']))


def segment_projection(point,a,b):
    v=[b[k]-a[k] for k in range(len(a))];n=sum(x*x for x in v)
    f=sum((point[k]-a[k])*v[k] for k in range(len(a)))/n if n else -1
    return f,math.dist(point,[a[k]+f*v[k] for k in range(len(a))])


def verify_interface_evidence(record,source_by_row,mapped,plts,config,unit,idf_dir):
    evidence=record['metadata'].get('weld_interface_evidence',[])
    migrated={int(r[3]):r for r in mapped if str(r[7]).startswith('stable-component-interface:')}
    assert {t['source_row'] for t in evidence}==set(migrated),'接口迁移证据遗漏'
    assert len(evidence)==len(migrated),'接口迁移来源重复'
    models={};references={};pages={};hit_refs={}
    for t in evidence:
        proof=t['interface_identity_evidence'];row=source_by_row[t['source_row']];line=t['pipeline']
        q=coordinate(row['焊点位置']);assert math.dist(q,proof['source_coordinate_mm'])<1e-6
        name=config.get('pipeline_aliases',{}).get(line,line)
        reference=reference_idf_path(config,unit,line).resolve()
        assert Path(proof['reference_idf']).resolve()==reference
        if line not in models:
            models.clear();references.clear();pages.clear();hit_refs.clear()
            models[line]=load_model(idf_dir/(name+'.idf'),config.get('idf_coordinate_offset_mm'))
            references[line]=load_model(reference,config.get('weld_reference_coordinate_offset_mm'))
            hit_refs[line]={h['ref'] for stem,p in plts.items() if stem.rsplit('_Sht_',1)[0]==line
                            for h in read_hit(hit_file(p,configured_paths(config,unit)['hit_dir']))}
        if not row.get('_pipeline_transfer'):
            assert not current_pipe_interior(q,models[line]),'管内分段坐标不应迁移到接口'
        actual=interface_identity(q,references[line],models[line])
        assert actual==proof['interfaces'] and actual,'接口身份无法复现'
        physical=sorted({ref for e in actual for ref in e['refs']
                         if '/' in ref and not ref.startswith(('LSTU_','HSTU_')) and ref in hit_refs[line]})
        assert physical and physical==proof['physical_refs_in_hit'],'接口HIT实体证据不一致'
        assert math.dist(actual[0]['coordinate_mm'],proof['model_query_mm'])<1e-6
        r=migrated[t['source_row']]
        assert r[0]==t['page_stem'] and math.dist(r[5:7],[t['x_mm'],t['y_mm']])<1e-6
        assert row['管线号']==line and row['焊点编号']==t['number']
        stem=t['page_stem']
        if stem not in pages:pages[stem]=load_source_page(plts[stem],config,unit)
        if proof['native_weld_glyph']:
            assert any(math.dist([t['x_mm'],t['y_mm']],[d['x_mm'],d['y_mm']])<.25 for d in pages[stem]['dots'])
    return len(evidence)


def verify_reference_evidence(record,source_by_row,mapped,plts,config,unit,idf_dir):
    evidence=record['metadata'].get('weld_reference_evidence',[])
    migrated={int(r[3]):r for r in mapped if str(r[7]).startswith('reference-owner-verified:')}
    assert {t['source_row'] for t in evidence}==set(migrated) and len(evidence)==len(migrated),'参考模型归属证据遗漏或重复'
    models={};references={};hits={};pages={}
    for t in evidence:
        proof=t['reference_geometry_evidence'];row=source_by_row[t['source_row']];line=t['pipeline'];q=coordinate(row['焊点位置'])
        assert row['管线号']==line and row['焊点编号']==t['number'] and math.dist(q,proof['source_coordinate_mm'])<1e-6
        name=config.get('pipeline_aliases',{}).get(line,line)
        reference=reference_idf_path(config,unit,line).resolve()
        assert Path(proof['reference_idf']).resolve()==reference
        if line not in models:
            models.clear();references.clear();hits.clear();pages.clear()
            models[line]=load_model(idf_dir/(name+'.idf'),config.get('idf_coordinate_offset_mm'))
            references[line]=load_model(reference,config.get('weld_reference_coordinate_offset_mm'))
            hits[line]={h['ref'] for stem,p in plts.items() if stem.rsplit('_Sht_',1)[0]==line
                        for h in read_hit(hit_file(p,configured_paths(config,unit)['hit_dir']))}
        identity=identity_proposals(q,references[line],models[line],hits[line])
        assert json.loads(json.dumps(identity))==proof['identity'] and identity,'参考归属/平移/分段链证据无法复现'
        assert math.dist(identity['coordinate_mm'],proof['model_query_mm'])<1e-6
        original=proof['reference_target'];r=migrated[t['source_row']]
        assert original['source_row']==t['source_row'] and original['page_stem']==t['page_stem']==r[0]
        assert math.dist([original['x_mm'],original['y_mm']],[t['x_mm'],t['y_mm']])<=.25
        assert math.dist(r[5:7],[t['x_mm'],t['y_mm']])<1e-6
        stem=t['page_stem']
        if stem not in pages:pages[stem]=load_source_page(plts[stem],config,unit)
        if proof['native_weld_glyph']:
            assert any(math.dist([t['x_mm'],t['y_mm']],[d['x_mm'],d['y_mm']])<.25 for d in pages[stem]['dots'])
    return len(evidence)


def verify_topology_evidence(record,source_by_row,mapped,plts,config,idf_dir):
    unit=record['metadata']['unit']
    evidence=record['metadata'].get('weld_topology_evidence',[])
    located={int(r[3]):r for r in mapped if r[1]=='焊口'}
    from beihai_port_assignment import METHOD,owned_ports
    corrected={key:r for key,r in located.items() if r[7] in ('native-fitting-two-port-topology',METHOD)}
    assert {t['source_row'] for t in evidence}==set(corrected) and len(evidence)==len(corrected),'元件端口拓扑证据遗漏'
    models={};pages={}
    for t in evidence:
        proof=t['native_topology_evidence'];line=t['pipeline'];stem=t['page_stem'];q=proof['model_query_mm']
        if line not in models:
            models.clear();pages.clear()
            models[line]=load_model(idf_dir/(config.get('pipeline_aliases',{}).get(line,line)+'.idf'),config.get('idf_coordinate_offset_mm'))
        if stem not in pages:pages[stem]=load_source_page(plts[stem],config,unit)
        model=models[line];component=[c for c in model['components'] if c['ref']==proof['component_ref']]
        assert len(component)==1;component=component[0]
        assert component['line']==proof['idf_line'] and math.dist(q,component['ports'][proof['model_port_index']])<.11
        if located[t['source_row']][7]==METHOD:
            controls=[{'source_row':key,'page_stem':r[0],'x_mm':r[5],'y_mm':r[6],
                       'coordinate_mm':coordinate(source_by_row[key]['焊点位置']),'mapping_method':r[7]} for key,r in located.items()]
            assignments=owned_ports(component,model,{stem:pages[stem]},controls)
            actual=[a for a in assignments if a['model_port_index']==proof['model_port_index']]
            assert len(actual)==1 and all(json.loads(json.dumps(actual[0][k]))==proof[k] for k in actual[0]),'元件端口归属证据无法复现'
            row=corrected[t['source_row']]
            assert row[0]==stem and math.dist(row[5:7],[actual[0]['x_mm'],actual[0]['y_mm']])<1e-6
            assert source_by_row[t['source_row']]['焊点编号']==t['number']
            continue
        actual=native_ports(component,model,{stem:pages[stem]})
        assert len(actual)==1 and json.loads(json.dumps(actual[0]))==proof['native_body'],'完整元件两端无法复现'
        connection=proof['connection'];control=located[connection['control_source_row']]
        assert control[0]==stem and math.dist(control[5:7],connection['control_xy_mm'])<1e-6,'独立控制点已改变'
        pipe=[c for c in model['components'] if c['line']==connection['pipe_idf_line'] and c['ref']==connection['pipe_ref']]
        assert len(pipe)==1 and pipe[0]['code'] in (100,101)
        anchor=connection.get('anchored_model_port_index',proof['model_port_index'])
        assert any(math.dist(component['ports'][anchor],p)<.11 for p in pipe[0]['ports'])
        assert any(math.dist(connection['other_model_mm'],p)<.11 for p in pipe[0]['ports'])
        ports=actual[0]['ports'];linked=[i for i,p in enumerate(ports) if math.dist(p,connection['control_xy_mm'])>1 and native_axis_covers(pages[stem],p,connection['control_xy_mm'])]
        assert len(linked)==1,'原图连接管不能唯一确定元件一端'
        index=1-linked[0] if connection.get('inferred_by_two_port_bijection') else linked[0]
        assert math.dist(ports[index],[t['x_mm'],t['y_mm']])<1e-6
        row=corrected[t['source_row']]
        assert row[0]==stem and math.dist(row[5:7],[t['x_mm'],t['y_mm']])<1e-6
        assert source_by_row[t['source_row']]['焊点编号']==t['number']
    return len(evidence)


def verify_singleton_evidence(record,source_by_row,mapped,plts,config,idf_dir):
    unit=record['metadata']['unit']
    evidence=record['metadata'].get('weld_singleton_evidence',[])
    expected={int(r[3]):r for r in mapped if r[7]=='beihai-single-pipe-single-native-axis-free-end'}
    assert len(evidence)==len(expected) and {t['source_row'] for t in evidence}==set(expected)
    for t in evidence:
        name=config.get('pipeline_aliases',{}).get(t['pipeline'],t['pipeline'])
        model=load_model(idf_dir/(name+'.idf'),config.get('idf_coordinate_offset_mm'));page=load_source_page(plts[t['page_stem']],config,unit)
        q=coordinate(source_by_row[t['source_row']]['焊点位置'])
        candidates=singleton_pipe_candidates({'coordinate_mm':q},model,{t['page_stem']:page},native_axis_covers)
        assert len(candidates)==1 and math.dist([candidates[0]['x_mm'],candidates[0]['y_mm']],[t['x_mm'],t['y_mm']])<1e-6
        assert json.loads(json.dumps(candidates[0]['evidence']))==t['mapping_evidence']
    return len(evidence)


def main():
    root=WORKSPACE/'北海项目'
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--unit',default='PD60')
    ap.add_argument('--out-dir',type=Path,help='PDF目录，适用于转换时指定目录或交付文件夹已重命名的情况')
    args=ap.parse_args()
    config=unit_config(args.unit)
    defaults=configured_paths(config,args.unit)
    incoming=root/'PLT文件转换'/args.unit;output=args.out_dir or incoming/config['pdf_folder']
    plts={p.stem:p for p in incoming.rglob('*.plt')};stems=set(plts);pdfs={p.stem:p for p in output.glob('*.pdf')}
    assert set(pdfs)==stems,('PDF文件名/数量不匹配',stems-set(pdfs),set(pdfs)-stems)
    workbook=load_workbook(incoming/f'北海{args.unit}_标注问题清单.xlsx',read_only=True)
    record_path=audit_path(args.unit);record=None
    if record_path.exists():
        record=json.loads(record_path.read_text(encoding='utf-8'))
        assert record['metadata'].get('complete'),'转换尚未完成，请在导出完成后验证'
        sheets=record['sheets']
        if 'page_stats' in record:
            stats=record['page_stats']
            assert {r['stem'] for r in stats}==stems and len(stats)==len(stems),'存在未完成的新页面任务'
            assert all(r['pdf_verified'] for r in stats),'存在页面PDF核验失败'
        assert set(workbook.sheetnames)<= {'未标注编号','已标注需核对','布局需处理'},'交付清单包含非待处理过程记录'
    else:sheets={s.title:[list(r) for r in s.values] for s in workbook}
    mapped=sheets['标注定位清单'][1:];omitted=sheets['未标注编号'][1:]
    selected=record['metadata'].get('annotation_kinds') if record else None
    if selected is not None:
        allowed={LABEL_NAMES[k] for k in selected}
        assert all(r[1] in allowed for r in mapped),'绘制了未选择的编号类别'
        assert all(r[2] in allowed for r in omitted),'未标注清单包含未选择的编号类别'
    valve_proofs=defaultdict(list)
    spool_proofs=defaultdict(list);models={}
    if record:
        for proof in record['valve_centres']:valve_proofs[proof['page_stem']].append(proof)
        assert sum(map(len,valve_proofs.values()))==sum(r[1]=='阀门' for r in mapped),'缺少阀体中心证据'
        if 'spool_roots' in record:
            for proof in record['spool_roots']:spool_proofs[proof['page_stem']].append(proof)
            assert sum(map(len,spool_proofs.values()))==sum(r[1]=='管段' for r in mapped),'缺少管段元件线条中点证据'
    aliases=record['metadata'].get('pipeline_aliases',{}) if record else config.get('pipeline_aliases',{})
    table_aliases=record['metadata'].get('table_pipeline_aliases',aliases) if record else {**aliases,**config.get('table_pipeline_aliases',{})}
    idf_dir=Path(record['metadata'].get('idf_dir') or defaults['idf_dir']) if record else defaults['idf_dir']
    source_rows,_=read_csv(root/'焊口表.csv');source_rows=remap_rows(source_rows,table_aliases,record['metadata'].get('weld_pipeline_transfers',[]) if record else config.get('weld_pipeline_transfers'));source_by_row={r['_row']:r for r in source_rows}
    mapped_by_key={(r[0],r[1],str(r[2])):r for r in mapped}
    expected=defaultdict(Counter)
    root_rows=defaultdict(list)
    expected_colors=defaultdict(lambda:defaultdict(Counter))
    for row in mapped:
        expected[row[0]][str(row[2])]+=1
        root_rows[row[0]].append(row)
    for row in mapped:expected_colors[row[0]][0xff0000 if row[1] in ('焊口','管段') else 0x0066ff][str(row[2])]+=1
    for stem,path in pdfs.items():
        with fitz.open(path) as pdf:
            assert len(pdf)==1,stem
            page=pdf[0]
            assert abs(page.rect.width*25.4/72-594.2)<.1 and abs(page.rect.height*25.4/72-420.2)<.1,stem
            assert Counter(page.get_text().split())==expected[stem],(stem,'PDF编号不一致')
            actual_colors=defaultdict(Counter)
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    for span in line['spans']:
                        assert 'SimHei' in span['font'] and abs(span['size']-6*72/25.4)<.01 and span['color'] in (0xff0000,0x0066ff),(stem,span)
                        actual_colors[span['color']].update(span['text'].split())
            assert dict(actual_colors)==dict(expected_colors[stem]),(stem,'编号颜色/类别不一致')
            blue_lines=[];red_lines=[]
            for shape in page.get_drawings():
                color=shape.get('color')
                if color and max(abs(color[k]-[0,.4,1][k]) for k in range(3))<1e-4:
                    blue_lines.extend(item[1:3] for item in shape['items'] if item[0]=='l')
                if color and max(abs(color[k]-[1,0,0][k]) for k in range(3))<1e-4:
                    red_lines.extend(item[1:3] for item in shape['items'] if item[0]=='l')
            for row in root_rows[stem]:
                point=(row[5]*72/25.4,(420.2-row[6])*72/25.4)
                leaders=red_lines if row[1] in ('焊口','管段') else blue_lines
                assert any(min(math.dist(point,a),math.dist(point,b))<.03 for a,b in leaders),(stem,row[1],row[2],'PDF实际引线落点与审计位置不一致')
            if valve_proofs[stem] or spool_proofs[stem]:
                assert len({(round(p['x_mm'],3),round(p['y_mm'],3)) for p in valve_proofs[stem]})==len(valve_proofs[stem]),(stem,'多个阀门错误关联到同一阀体')
                for proof in valve_proofs[stem]:
                    body=proof['valve_body_evidence'];center=[(body['a'][k]+body['b'][k])/2 for k in (0,1)]
                    assert math.dist(center,[proof['x_mm'],proof['y_mm']])<.001,(stem,proof['number'],'阀门未取两端中点')
                    point=(center[0]*72/25.4,(420.2-center[1])*72/25.4)
                    assert any(min(math.dist(point,a),math.dist(point,b))<.03 for a,b in blue_lines),(stem,proof['number'],'PDF引线未落在阀体中心')
                if spool_proofs[stem]:
                    source_segments={s['offset']:s for s in decode_plt(plts[stem])['segments']}
                    for proof in spool_proofs[stem]:
                        row=mapped_by_key[(stem,'管段',str(proof['number']))];point=(row[5],row[6])
                        aa,bb=proof['usable_segment_mm'];centre=[(aa[k]+bb[k])/2 for k in (0,1)]
                        assert math.dist(point,centre)<1e-7,(stem,proof['number'],'未取元件线段中点')
                        native=source_segments[proof['native_stroke']['offset']];a,b=[tuple(v/10 for v in native[key]) for key in ('a','b')]
                        fraction,distance=segment_projection(point,a,b)
                        assert distance<1e-7 and 0<fraction<1,(stem,proof['number'],'落点未位于真实PLT线条')
                        pipeline=proof['pipeline']
                        if pipeline not in models:models[pipeline]=load_model(idf_dir/(aliases.get(pipeline,pipeline)+'.idf'),record['metadata'].get('idf_coordinate_offset_mm',config.get('idf_coordinate_offset_mm')))
                        component=next(c for c in models[pipeline]['components'] if c['line']==proof['idf_line'])
                        assert component['ref']==proof['component_ref'] and component['code']==proof['component_code']
                        query=proof['model_weld_mm'];adjacent=any(math.dist(query,p)<1 for p in component['ports'])
                        if not adjacent and component['code'] in (100,101):
                            f,d=segment_projection(query,*component['ports']);adjacent=0<f<1 and d<.11
                        assert adjacent,(stem,proof['number'],'未证明元件与管段焊口相邻')
                        related_number=proof['related_weld'].rsplit(':weld:',1)[1]
                        related=mapped_by_key[(stem,'焊口',related_number)];source=source_by_row[int(related[3])]
                        assert source['管段编号']==str(proof['number']),(stem,proof['number'],'焊口不属于此管段')
                        pdf_point=(point[0]*72/25.4,(420.2-point[1])*72/25.4)
                        assert any(min(math.dist(pdf_point,a),math.dist(pdf_point,b))<.03 for a,b in red_lines),(stem,proof['number'],'PDF管段引线未生根在元件线条中点')
    pipelines={s.rsplit('_Sht_',1)[0] for s in stems};rows=source_rows
    interface_count=verify_interface_evidence(record,source_by_row,mapped,plts,config,args.unit,idf_dir) if record else 0
    reference_count=verify_reference_evidence(record,source_by_row,mapped,plts,config,args.unit,idf_dir) if record else 0
    topology_count=verify_topology_evidence(record,source_by_row,mapped,plts,config,idf_dir) if record else 0
    source_warnings=record['metadata'].get('source_drawing_issues',[]) if record else []
    from pdms_source_warnings import native_source_warnings
    for warning in source_warnings:
        stem=warning['page_stem']
        actual=[dict(w,page_stem=stem) for w in native_source_warnings(decode_plt(plts[stem]))]
        assert warning in actual,(stem,'源图FAIL标记或来源文件哈希无法复现')
    singleton_count=verify_singleton_evidence(record,source_by_row,mapped,plts,config,idf_dir) if record else 0
    source={(r['管线号'],r['焊点编号']) for r in rows if r['管线号'] in pipelines}
    located={(r[0].rsplit('_Sht_',1)[0],str(r[2])) for r in mapped if r[1]=='焊口'}
    missing={(r[0].rsplit('_Sht_',1)[0],str(r[3])) for r in omitted if r[2]=='焊口'}
    assert not located&missing and source==located|missing,'焊口覆盖不守恒'
    assert len(located)==sum(r[1]=='焊口' for r in mapped),'焊口重复标注'
    management_rows=sheets.get('管理编号逐行核对',[[]])[1:]
    management_counts={}
    if management_rows:
        kinds=[k for k in ('valve','flange','support') if selected is None or k in selected]
        tables=load_management_tables(root,kinds)
        for kind,table in tables.items():table['rows']=remap_rows(table['rows'],table_aliases,[t for t in record['metadata'].get('management_pipeline_transfers',[]) if t['kind']==kind])
        expected_rows={(t['file'],r['_row']) for t in tables.values() for r in t['rows'] if r['管线号'] in pipelines and (not r.get('单元号') or r['单元号']==args.unit)}
        assert {(r[5],int(r[6])) for r in management_rows}==expected_rows,'管理表来源行未全部核对'
        for kind,table in tables.items():
            label=LABEL_NAMES[kind]
            source_keys={(r['管线号'],r[table['column']]) for r in table['rows'] if r['管线号'] in pipelines and (not r.get('单元号') or r['单元号']==args.unit)}
            drawn_keys={(r[0].rsplit('_Sht_',1)[0],str(r[2])) for r in mapped if r[1]==label}
            omitted_keys={(r[0].rsplit('_Sht_',1)[0],str(r[3])) for r in omitted if r[2]==label}
            assert not drawn_keys&omitted_keys and source_keys==drawn_keys|omitted_keys,(kind,'管理编号覆盖不守恒')
            assert len(drawn_keys)==sum(r[1]==label for r in mapped),(kind,'管理编号重复标注')
            for r in [r for r in mapped if r[1]==label]:
                source_rows={int(n) for n in str(r[11]).split(',')};source_refs={ref.strip().lstrip('=') for row in table['rows'] if row['_row'] in source_rows for ref in row['UCI'].split(';')}
                assert source_refs==set(r[9].split(';')),(kind,r[2],'UCI合并遗漏')
            management_counts[kind]={'annotated':len(drawn_keys),'omitted':len(omitted_keys)}
    for row in sheets['单页转换结果'][1:]:
        assert row[5]==0 and str(row[6]).startswith('通过'),row
    print({'pages':len(pdfs),'source_welds':len(source),'annotated_welds':len(located),
           'unannotated_welds':len(missing),'spool_labels':sum(r[1]=='管段' for r in mapped),
           'management':management_counts,
           'valve_body_centres':sum(map(len,valve_proofs.values())),
           'spool_component_midpoints':sum(map(len,spool_proofs.values())),
           'pdf_leader_roots':len(mapped),
           'verified_interface_migrations':interface_count,
           'verified_reference_recoveries':reference_count,
           'verified_native_topology_ports':topology_count,
           'verified_source_drawing_warnings':len(source_warnings),
           'verified_singleton_pipe_ends':singleton_count,
           'pdf_font_color_counts':'passed','source_coverage':'passed','layout_checks':'passed'})
    workbook.close()


if __name__=='__main__':main()
