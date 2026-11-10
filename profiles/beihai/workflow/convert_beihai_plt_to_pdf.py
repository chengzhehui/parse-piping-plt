"""Fixed Beihai entry: native PLT + HIT + matching IDF + EP3D weld table.

Outputs only single-sheet PDFs and an Excel issue/audit workbook. Transient
SVGs and layouts live in a temporary directory and are removed after export.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor,as_completed

from openpyxl.styles import Alignment,Font,PatternFill

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from audit_beihai_inputs import main as input_audit
from audit_pdms_export import read_csv,coordinate
from beihai_geometry import load_model,load_page,beihai_candidates,resolve_pipe_interiors,unresolved_diagnosis
from render_complete_pdms import resolve_pipeline
from beihai_interface_identity import resolve_welds
from beihai_management import LABEL_NAMES,load_management_tables,resolve_management
from beihai_review_report import save_internal_audit,reviewer_workbook
from beihai_spool_geometry import component_midpoint_anchor
from beihai_page_jobs import render_page_job,physical_conflicts
from beihai_resource_monitor import ResourceMonitor
from beihai_unit_profile import unit_config,remap_rows,verify_alias,verify_configured_alias,verify_filename_alias,configured_paths,hit_file,validate_coordinate_frame,validate_management_transfers

BASE=REPOSITORY


def sheet(wb,name,headers):
    result=wb.create_sheet(name);result.append(headers);return result


def style_workbook(wb):
    for s in wb:
        s.freeze_panes='A2';s.auto_filter.ref=s.dimensions
        for c in s[1]:
            c.fill=PatternFill('solid',fgColor='1F4E78');c.font=Font(color='FFFFFF',bold=True)
        for column in s.columns:
            s.column_dimensions[column[0].column_letter].width=min(80,max(14,max(len(str(c.value or '')) for c in list(column)[:150])+2))
        for row in s.iter_rows(min_row=2):
            for c in row:c.alignment=Alignment(vertical='top',wrap_text=True)


def main(argv=None):
    config=json.loads((BASE/'profiles/beihai/config.json').read_text(encoding='utf-8'))
    selector=argparse.ArgumentParser(add_help=False)
    selector.add_argument('--unit',default=config['default_unit'])
    selector.add_argument('--generic',action='store_true')
    selected=selector.parse_known_args(argv)[0]
    if selected.generic:
        config.update(default_unit='通用',page_workers=8,spool_annotations=False,native_topology_ports=True)
    else:config=unit_config(selected.unit)
    aliases=config.get('pipeline_aliases',{})
    table_aliases={**aliases,**config.get('table_pipeline_aliases',{})}
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--unit',default=config['default_unit'],help='项目单元，例如 PD60')
    ap.add_argument('--generic',action='store_true',help='不加载北海单元专属名称、坐标及历史模型配置')
    ap.add_argument('--all-units',action='store_true',help='管理表不按单元号过滤，仅按输入管线关联')
    ap.add_argument('--input-dir',type=Path)
    ap.add_argument('--idf-dir',type=Path)
    ap.add_argument('--hit-dir',type=Path)
    ap.add_argument('--weld-table',type=Path)
    ap.add_argument('--out-dir',type=Path)
    ap.add_argument('--report-path',type=Path)
    ap.add_argument('--support-table',type=Path)
    ap.add_argument('--valve-table',type=Path)
    ap.add_argument('--flange-table',type=Path)
    ap.add_argument('--pipeline',help='仅处理指定管线，用于复核')
    ap.add_argument('--management',action=argparse.BooleanOptionalAction,default=config.get('management_annotations',False))
    ap.add_argument('--spool',action=argparse.BooleanOptionalAction,default=config.get('spool_annotations',True),help='是否标注管段号，默认由单元配置决定')
    ap.add_argument('--management-kinds',nargs='+',choices=('valve','flange','support'),default=config.get('management_kinds',['valve','flange','support']),help='需标注的管理编号类别')
    ap.add_argument('--management-tables-dir',type=Path,help='阀门、法兰、支架CSV所在目录，默认与焊口表相同')
    ap.add_argument('--workers',type=int,default=config.get('page_workers',2),help='独立页面工作进程数，默认由单元配置决定')
    args=ap.parse_args(argv)
    if args.workers<1:ap.error('--workers必须大于等于1')
    # Bound native numerical threads inside each spawned page process.
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
    defaults=configured_paths(config,args.unit)
    incoming=(args.input_dir or defaults['input_dir']).resolve()
    idfs=(args.idf_dir or defaults['idf_dir']).resolve()
    hits=(args.hit_dir or defaults['hit_dir'])
    if hits is not None:hits=hits.resolve()
    weld_table=(args.weld_table or WORKSPACE/config['weld_table']).resolve()
    table_paths={kind:getattr(args,kind+'_table') for kind in ('support','valve','flange') if getattr(args,kind+'_table')}
    management_tables=load_management_tables(args.management_tables_dir or weld_table.parent,args.management_kinds,table_paths) if args.management else {}
    for kind,table in management_tables.items():table['rows']=remap_rows(table['rows'],table_aliases,[t for t in config.get('management_pipeline_transfers',[]) if t['kind']==kind])
    annotation_kinds=['weld']+(['spool'] if args.spool else [])+list(management_tables)
    out=(args.out_dir or incoming/config['pdf_folder']).resolve();out.mkdir(parents=True,exist_ok=True)
    report=args.report_path or incoming/f'北海{args.unit}_标注问题清单.xlsx'
    report.parent.mkdir(parents=True,exist_ok=True)
    if args.pipeline:
        if not args.out_dir:out=out/('复核_'+args.pipeline);out.mkdir(parents=True,exist_ok=True)
        if not args.report_path:report=incoming/f'北海{args.unit}_{args.pipeline}_标注问题清单.xlsx'
    paths=sorted(p for p in incoming.rglob('*.plt') if out not in p.parents)
    if not paths:ap.error(f'未找到 PLT: {incoming}')
    if len({p.stem for p in paths})!=len(paths):ap.error('存在重复的管线号和sheet文件名，请先消除多版本输入歧义')
    groups=defaultdict(list)
    for p in paths:
        line,number=p.stem.rsplit('_Sht_',1);int(number)
        if not args.pipeline or line==args.pipeline:groups[line].append(p)
    if not groups:ap.error('未找到指定管线')
    print('Preflight',incoming,flush=True)
    validate_management_transfers(config,args.unit)
    frame_evidence=validate_coordinate_frame(config,idfs,args.management_tables_dir or weld_table.parent,args.unit)
    audit_args=['--input-dir',str(incoming),'--idf-dir',str(idfs),'--weld-table',str(weld_table)]
    if hits is not None:audit_args+=['--hit-dir',str(hits)]
    wb=input_audit(audit_args,save=False,pipeline_aliases=aliases,table_aliases=table_aliases,
                   model_offset_mm=config.get('idf_coordinate_offset_mm'),weld_transfers=config.get('weld_pipeline_transfers'))
    issues=sheet(wb,'未标注编号',['单页图号','页码','编号类型','编号','未标注原因','参考坐标','来源表行号'])
    review=sheet(wb,'自动匹配需审核',['单页图号','页码','编号类型','编号','自动匹配方法','UCI','审核说明'])
    mapping=sheet(wb,'标注定位清单',['单页图号','编号类型','编号','来源表行号','模型坐标mm','纸面Xmm','纸面Ymm','定位方法','相关焊口','UCI','来源文件','来源行合集'])
    results=sheet(wb,'单页转换结果',['单页图号','PDF文件','焊口数','管段数','布局状态','标注冲突数','PDF验证','耗时秒','阀门数','法兰数','支架数'])
    management_audit=sheet(wb,'管理编号逐行核对',['单元号','管线号','表页码','编号类型','编号','来源文件','来源行号','UCI','定位图页','结果','定位方法','问题说明','纸面Xmm','纸面Ymm'])
    rows,_=read_csv(weld_table)
    rows=remap_rows(rows,table_aliases,config.get('weld_pipeline_transfers'))
    duplicates=Counter((r['管线号'],r['焊点编号']) for r in rows)
    totals=Counter();timing=time.monotonic();pdf_names=[];failures=[]
    valve_centres=[];spool_roots=[];page_stats=[];jobs={}
    metadata={'unit':args.unit,'pipeline':args.pipeline,'input_dir':str(incoming),'pdf_dir':str(out),
              'weld_table':str(weld_table),'management_tables_dir':str(args.management_tables_dir or weld_table.parent),
              'management_table_paths':{kind:table['source_path'] for kind,table in management_tables.items()},
              'complete':False,'report_coincident_welds':True,'page_workers':args.workers,'spool_rule':'IDF-owned component stroke midpoint',
              'annotation_kinds':annotation_kinds,'pipeline_aliases':aliases,'alias_evidence':[],
              'table_pipeline_aliases':table_aliases,'weld_pipeline_transfers':config.get('weld_pipeline_transfers',[]),'management_pipeline_transfers':config.get('management_pipeline_transfers',[]),'idf_dir':str(idfs),'hit_dir':str(hits) if hits is not None else None,
              'idf_coordinate_offset_mm':config.get('idf_coordinate_offset_mm'),'coordinate_frame_evidence':frame_evidence,
              'support_duplicate_evidence':[],'weld_interface_evidence':[],'weld_reference_evidence':[],'weld_topology_evidence':[],'weld_singleton_evidence':[]}
    performance_path=AUDIT/'performance'/f'{args.unit}_workers{args.workers}.json'
    with tempfile.TemporaryDirectory(prefix='beihai_plt_') as temp, ResourceMonitor(performance_path,args.workers) as monitor, ProcessPoolExecutor(max_workers=args.workers) as executor:
        stage=Path(temp)
        for line,line_paths in sorted(groups.items()):
            print('Mapping',line,flush=True)
            local=[r for r in rows if r['管线号']==line];valid=[]
            for r in local:
                reason='焊口号在同一管线内重复，无法唯一关联' if duplicates[(line,r['焊点编号'])]>1 else ''
                q=coordinate(r['焊点位置'])
                if q is None or not all(math.isfinite(v) for v in q):reason='焊口坐标缺失或格式错误'
                if reason:issues.append([line,r['页码'],'焊口',r['焊点编号'],reason,r['焊点位置'],r['_row']])
                else:valid.append(r)
            try:
                source_line=aliases.get(line,line)
                model=load_model(idfs/(source_line+'.idf'),config.get('idf_coordinate_offset_mm'))
                pages={p.stem:load_page(p,hit_file(p,hits)) for p in line_paths}
                if line in table_aliases:
                    if config.get('filename_aliases_only') and line not in config.get('confirmed_pipeline_renames',{}):
                        proof=verify_filename_alias(line,table_aliases[line],model,source_line)
                        alias_note='已核对IDF内部管线号与斜杠文件名转换；焊口坐标和实体UCI仍按原有规则逐项定位。'
                    else:
                        proof=verify_configured_alias(config,args.unit,line,table_aliases[line],model,pages,local)
                        alias_note='已核对IDF内部名称、实体UCI及焊口模型坐标，请确认命名一致性。'
                    metadata['alias_evidence'].append(proof)
                    stem=sorted(pages)[0]
                    review.append([stem,stem.rsplit('_Sht_',1)[1],'文件配套','','pipeline-alias','',
                        f'原图文件管线号 {line} 与编号表管线号 {table_aliases[line]} 不同；'+alias_note])
                for page in pages.values():
                    page['data']['drawing_bounds_mm']=config['drawing_bounds_mm']
                    page['hit_offset_mm']=config['hit_offset_mm']
                mapped,unresolved=resolve_welds(valid,model,pages,config,line,args.unit)
                for target in mapped:target['source_file']=weld_table.name
            except Exception as exc:
                failures.append((line,str(exc)))
                for r in valid:issues.append([line,r['页码'],'焊口',r['焊点编号'],str(exc),r['焊点位置'],r['_row']])
                # Do not publish a partial/incorrect base page after parse failures.
                for p in line_paths:results.append([p.stem,'',0,0,'读取/关联失败','','',0])
                save_internal_audit(wb,args.unit,args.pipeline,valve_centres,metadata,spool_roots,page_stats);continue
            totals['source_welds']+=len(local)
            for t in unresolved:
                issues.append([line,t['source_table_page'],'焊口',t['number'],
                    unresolved_diagnosis(t,model,pages)['reason'],str(t['coordinate_mm']),t['source_row']])
            metadata['weld_interface_evidence'].extend({k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','interface_identity_evidence')} for t in mapped if t.get('interface_identity_evidence'))
            metadata['weld_reference_evidence'].extend({k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','reference_geometry_evidence')} for t in mapped if t.get('reference_geometry_evidence'))
            metadata['weld_topology_evidence'].extend({k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','native_topology_evidence')} for t in mapped if t.get('native_topology_evidence'))
            metadata['weld_singleton_evidence'].extend({k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','coordinate_mm','mapping_evidence')} for t in mapped if t['mapping_method']=='beihai-single-pipe-single-native-axis-free-end')
            targets=list(mapped);spool_members=defaultdict(list)
            for t in mapped:
                if args.spool and t['spool_number']:spool_members[(t['page_stem'],t['spool_number'])].append(t)
                # All inferred symbol rules remain inspectable; native evidence
                # does not turn a software placement into a manual verification.
                notes=t.get('review_notes',[])
                ambiguous=len({(c['page_stem'],round(c['x_mm'],1),round(c['y_mm'],1)) for c in t.get('candidates',[])})>1
                if notes or ambiguous or t['mapping_method'] in ('HIT-local-leg-and-native-vertex','model-interface-HIT-ray-native-weld-symbol'):
                    review.append([t['page_stem'],t['page_stem'].rsplit('_Sht_',1)[1],'焊口',t['number'],t['mapping_method'],
                        ','.join(sorted({e.get('ref') or '' for e in t.get('mapping_evidence',[]) if isinstance(e,dict)})) if isinstance(t.get('mapping_evidence'),list) else '',
                        json.dumps(notes,ensure_ascii=False) if notes else ('存在多个候选位置，已按证据排序选择，请复核' if ambiguous else '按元件方向及符号规则自动匹配，请结合原图复核')])
            all_spools={r['管段编号'] for r in valid if r['管段编号']} if args.spool else set()
            for number in sorted(all_spools-{n for s,n in spool_members}):
                r=next(r for r in valid if r['管段编号']==number)
                issues.append([line,r['页码'],'管段',number,'所属焊口均未可靠定位，无法确定管段引线位置',r['焊点位置'],r['_row']])
            for (stem,number),members in sorted(spool_members.items()):
                try:
                    anchor,member,proof=component_midpoint_anchor(members,pages[stem],model,[w for w in mapped if w['page_stem']==stem])
                except ValueError as exc:
                    member=members[0]
                    issues.append([stem,stem.rsplit('_Sht_',1)[1],'管段',number,str(exc),'',member['source_row']]);continue
                method=proof['method'];spool_roots.append(dict(proof,page_stem=stem,number=number,pipeline=line))
                targets.append({'key':f'{line}:spool:{number}:{stem}','kind':'spool','pipeline':line,'number':number,
                    'page_stem':stem,'x_mm':anchor[0],'y_mm':anchor[1],'source_row':member['source_row'],
                    'mapping_method':method,'related_weld':member['key']})
            # A source spool remains partially unlocated if any of its welds fail.
            for t in unresolved:
                if t['spool_number'] and t['spool_number'] in {n for s,n in spool_members}:
                    review.append([line,t['source_table_page'],'管段',t['spool_number'],'partial-spool-membership','',
                        f"管段部分焊口未定位（焊口 {t['number']}），已按成功定位的成员绘制管段号"])
            management,management_issues,management_rows,management_review,management_counts=resolve_management(management_tables,line,pages,model,None if args.all_units else args.unit)
            targets.extend(management);totals.update(management_counts)
            metadata['support_duplicate_evidence'].extend({k:t[k] for k in ('pipeline','number','page_stem','ref','x_mm','y_mm','source_rows','duplicate_support_evidence')}
                for t in management if t.get('duplicate_support_evidence'))
            valve_centres.extend({k:t[k] for k in ('key','pipeline','number','page_stem','ref','x_mm','y_mm','valve_body_evidence')}
                                 for t in management if t['kind']=='valve')
            for row in management_issues:issues.append(row)
            for row in management_rows:management_audit.append(row)
            for row in management_review:review.append(row)
            for t in targets:
                mapping.append([t['page_stem'],LABEL_NAMES[t['kind']],t['number'],t['source_row'],
                    str(t.get('coordinate_mm','')),t['x_mm'],t['y_mm'],t['mapping_method'],t.get('related_weld',''),
                    t.get('ref',''),t.get('source_file','焊口表.csv'),','.join(str(n) for n in t.get('source_rows',[t['source_row']]))])
            totals['mapped_welds']+=len(mapped);totals['unresolved_welds']+=len(unresolved)
            totals['spool_labels']+=sum(t['kind']=='spool' for t in targets)
            for stem,page in sorted(pages.items()):
                page_targets=[t for t in targets if t['page_stem']==stem]
                path=next(p for p in line_paths if p.stem==stem)
                job={'plt_path':str(path),'targets':page_targets,'config':config,'stage':str(stage)}
                jobs[executor.submit(render_page_job,job)]={'stem':stem,'targets':page_targets}
                print('Queued',stem,len(page_targets),flush=True)
            # Save review data per pipeline so an interrupted run retains evidence.
            save_internal_audit(wb,args.unit,args.pipeline,valve_centres,metadata,spool_roots,page_stats)
            del pages,model
        monitor.phase='page-workers';completed={}
        for future in as_completed(jobs):
            context=jobs[future];stem=context['stem']
            try:
                result=future.result();page_stats.append(result);completed[stem]=result
                if not result['pdf_verified']:raise ValueError('PDF编号或页面验证失败')
                shutil.copy2(stage/'pdfs'/(stem+'.pdf'),out/(stem+'.pdf'));pdf_names.append(stem)
                totals['annotation_conflicts']+=len(result['conflicts'])
                print('Done',stem,'pid',result['pid'],'seconds',result['elapsed_seconds'],flush=True)
            except Exception as exc:
                failures.append((stem,str(exc)))
                for t in context['targets']:issues.append([stem,stem.rsplit('_Sht_',1)[1],LABEL_NAMES[t['kind']],t['number'],'页面转换失败: '+str(exc),'',t['source_row']])
        for stem,result in sorted(completed.items()):
            counts=result['counts']
            results.append([stem,stem+'.pdf',counts.get('weld',0),counts.get('spool',0),result['mode'],len(result['conflicts']),
                '通过：单页、图幅及标注编号一致' if result['pdf_verified'] else '失败：PDF校验不一致',result['elapsed_seconds'],
                *[counts.get(kind,0) for kind in ('valve','flange','support')]])
            for conflict in result['conflicts']:review.append([stem,stem.rsplit('_Sht_',1)[1],'布局','','joint-layout','',json.dumps(conflict,ensure_ascii=False)])
    metadata['performance']=monitor.summary
    metadata['source_drawing_issues']=[dict(w,page_stem=r['stem']) for r in page_stats for w in r.get('source_warnings',[])]
    summary=sheet(wb,'本次转换汇总',['项目','数值','说明'])
    for k,v in [('输入管线',len(groups)),('输入PLT页数',sum(map(len,groups.values()))),('输出单页PDF',len(pdf_names)),
                ('来源焊口',totals['source_welds']),('已定位焊口',totals['mapped_welds']),('未定位焊口',totals['unresolved_welds']),
                ('管段标注数',totals['spool_labels']),('标注之间冲突数',totals['annotation_conflicts']),('处理失败数',len(failures)),
                ('未标注清单记录数',issues.max_row-1),('自动匹配审核记录数',review.max_row-1),('耗时秒',round(time.monotonic()-timing,2))]:summary.append([k,v,''])
    for kind in ('valve','flange','support'):
        for label,key in [('来源表记录','source_'+kind+'_rows'),('已标注','mapped_'+kind),('未标注','unresolved_'+kind),('同号同位置合并记录','merged_'+kind+'_rows')]:
            summary.append([LABEL_NAMES[kind]+label,totals[key],''])
    summary.append(['样式','6mm字高；12mm红色焊口圈；紧凑红色双框管段号；蓝色紧凑管理编号框','本次标注：'+'、'.join(LABEL_NAMES[k] for k in annotation_kinds)+'；统一避让及分档引线长度惩罚'])
    summary.append(['输入范围',str(incoming),'PLT+HIT+同期IDF+焊口表'+''.join('＋'+t['file'] for t in management_tables.values())+'；DXF未读取；不生成合并PDF'])
    summary.append(['审核说明','自动定位不等同于人工验证','原图还原包含原有内容；导出日志问题与本工具未标注问题分表列示'])
    summary.append(['页面工作进程',args.workers,'每个页面独立解析、布局、PDF输出与核验；主进程汇总清单'])
    for name,reason in failures:summary.append(['处理失败',name,reason])
    metadata['complete']=True
    save_internal_audit(wb,args.unit,args.pipeline,valve_centres,metadata,spool_roots,page_stats)
    public=reviewer_workbook(wb,metadata);style_workbook(public)
    for s in public:
        for column,width in zip('ABCDEFG',(38,8,12,14,64,36,16)):s.column_dimensions[column].width=width
        s.row_dimensions[1].height=24
        for number in range(2,s.max_row+1):
            text=str(s.cell(number,5).value or '')
            units=sum(2 if ord(char)>127 else 1 for char in text)
            s.row_dimensions[number].height=max(42,min(120,14*math.ceil(units/60)+8))
    public.save(report)
    print('COMPLETE',dict(totals),'PDFs',len(pdf_names),'failures',len(failures),'report',report,flush=True)
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
