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

from audit_pdms_export import read_csv
from beihai_management import LABEL_NAMES,load_management_tables
from beihai_review_report import audit_path
from analyze_plt_bundle import decode_plt
from beihai_geometry import load_model


def segment_projection(point,a,b):
    v=[b[k]-a[k] for k in range(len(a))];n=sum(x*x for x in v)
    f=sum((point[k]-a[k])*v[k] for k in range(len(a)))/n if n else -1
    return f,math.dist(point,[a[k]+f*v[k] for k in range(len(a))])


def main():
    root=WORKSPACE/'北海项目'
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--unit',default='PD60')
    ap.add_argument('--out-dir',type=Path,help='PDF目录，适用于转换时指定目录或交付文件夹已重命名的情况')
    args=ap.parse_args()
    incoming=root/'PLT文件转换'/args.unit;output=args.out_dir or incoming/'转换标注PDF'
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
    valve_proofs=defaultdict(list)
    spool_proofs=defaultdict(list);models={}
    if record:
        for proof in record['valve_centres']:valve_proofs[proof['page_stem']].append(proof)
        assert sum(map(len,valve_proofs.values()))==sum(r[1]=='阀门' for r in mapped),'缺少阀体中心证据'
        if 'spool_roots' in record:
            for proof in record['spool_roots']:spool_proofs[proof['page_stem']].append(proof)
            assert sum(map(len,spool_proofs.values()))==sum(r[1]=='管段' for r in mapped),'缺少管段元件线条中点证据'
    source_rows,_=read_csv(root/'焊口表.csv');source_by_row={r['_row']:r for r in source_rows}
    mapped_by_key={(r[0],r[1],str(r[2])):r for r in mapped}
    expected=defaultdict(Counter)
    expected_colors=defaultdict(lambda:defaultdict(Counter))
    for row in mapped:expected[row[0]][str(row[2])]+=1
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
            if valve_proofs[stem] or spool_proofs[stem]:
                assert len({(round(p['x_mm'],3),round(p['y_mm'],3)) for p in valve_proofs[stem]})==len(valve_proofs[stem]),(stem,'多个阀门错误关联到同一阀体')
                blue_lines=[];red_lines=[]
                for shape in page.get_drawings():
                    color=shape.get('color')
                    if color and max(abs(color[k]-[0,.4,1][k]) for k in range(3))<1e-4:
                        blue_lines.extend(item[1:3] for item in shape['items'] if item[0]=='l')
                    if color and max(abs(color[k]-[1,0,0][k]) for k in range(3))<1e-4:
                        red_lines.extend(item[1:3] for item in shape['items'] if item[0]=='l')
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
                        if pipeline not in models:models[pipeline]=load_model(root/'IDF'/args.unit/(pipeline+'.idf'))
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
    pipelines={s.rsplit('_Sht_',1)[0] for s in stems};rows,_=read_csv(root/'焊口表.csv')
    source={(r['管线号'],r['焊点编号']) for r in rows if r['管线号'] in pipelines}
    located={(r[0].rsplit('_Sht_',1)[0],str(r[2])) for r in mapped if r[1]=='焊口'}
    missing={(r[0].rsplit('_Sht_',1)[0],str(r[3])) for r in omitted if r[2]=='焊口'}
    assert not located&missing and source==located|missing,'焊口覆盖不守恒'
    assert len(located)==sum(r[1]=='焊口' for r in mapped),'焊口重复标注'
    management_rows=sheets.get('管理编号逐行核对',[[]])[1:]
    management_counts={}
    if management_rows:
        tables=load_management_tables(root)
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
           'pdf_font_color_counts':'passed','source_coverage':'passed','layout_checks':'passed'})
    workbook.close()


if __name__=='__main__':main()
