"""Fast association-only audit; no layout or PDF regeneration.

Compare all source rows with the last delivered workbook and retain per-row
IDF/HIT/native-glyph evidence so each rule revision can be checked independently.
"""
import argparse
from collections import Counter,defaultdict
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from pathlib import Path

from openpyxl import load_workbook
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from audit_pdms_export import read_csv,coordinate
from beihai_geometry import load_model,load_page,beihai_candidates,resolve_pipe_interiors,unresolved_diagnosis
from render_complete_pdms import resolve_pipeline
from beihai_interface_identity import resolve_welds
from beihai_review_report import audit_path
from beihai_unit_profile import unit_config,remap_rows,configured_paths,hit_file,validate_coordinate_frame,verify_filename_alias,verify_alias,verify_configured_alias,validate_management_transfers
from beihai_management import load_management_tables,resolve_management,LABEL_NAMES
from pdms_source_warnings import native_source_warnings

BASE=REPOSITORY
ROOT=BASE.parent/'北海项目'


def pipeline_preflight(job):
    """One pipeline's association and evidence, without any drawing/layout work."""
    line=job['line'];config=job['config'];paths_config=job['paths_config']
    aliases=config.get('pipeline_aliases',{})
    table_aliases={**aliases,**config.get('table_pipeline_aliases',{})}
    model=load_model(paths_config['idf_dir']/(aliases.get(line,line)+'.idf'),config.get('idf_coordinate_offset_mm'))
    if config.get('filename_aliases_only') and line in table_aliases and line not in config.get('confirmed_pipeline_renames',{}):
        verify_filename_alias(line,table_aliases[line],model,aliases.get(line,line))
    pages={p.stem:load_page(p,hit_file(p,paths_config['hit_dir'])) for p in job['paths']}
    if line in table_aliases and (not config.get('filename_aliases_only') or line in config.get('confirmed_pipeline_renames',{})):
        verify_configured_alias(config,job['unit'],line,table_aliases[line],model,pages,job['rows'])
    mapped,unresolved=resolve_welds(job['rows'],model,pages,config,line,job['unit'])
    mt,mi,ma,mr,mc=resolve_management(job['tables'],line,pages,model,job['unit'])
    missing=[]
    for t in unresolved:
        q=t['coordinate_mm'];near=[c for c in model['components'] if any(math.dist(q,p)<=1 for p in c['ports'])]
        details=[]
        for c in near:
            info={k:c[k] for k in ('code','skey','ref','line','ports','segments')}
            info['hits']=[{'page_stem':stem,**h} for stem,page in pages.items() for h in page['hits'] if h['ref']==c['ref']]
            details.append(info)
        interiors=[]
        for c in model['components']:
            if c['code'] not in (100,101) or len(c['ports'])!=2:continue
            a,b=c['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
            f=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if 0<f<1 and math.dist(q,[a[k]+f*v[k] for k in range(3)])<=.1:
                interiors.append({'ref':c['ref'],'line':c['line'],'fraction':f,'ports':c['ports'],
                    'terminal_candidates':[beihai_candidates({'coordinate_mm':p},model,pages) for p in c['ports']]})
        missing.append({'target':t,'diagnosis':unresolved_diagnosis(t,model,pages),'near_components':details,'pipe_interiors':interiors,
            'page_geometry_counts':{s:{'hits':len(p['hits']),'dots':len(p['dots']),'heavy_axes':len(p['heavy_segments'])} for s,p in pages.items()}})
    return {'line':line,'mapped':mapped,'missing':missing,'management_mapped':mt,'management_missing':mi,
            'management_audit':ma,'management_review':mr,'management_counts':mc,
            'source_drawing_issues':[dict(w,page_stem=stem) for stem,page in pages.items() for w in native_source_warnings(page['data'])]}


def verify_declared_corrections(changed,declarations):
    expected={int(d['source_row']):d for d in declarations};verified=[];unexpected=[]
    if len(expected)!=len(declarations):raise ValueError('校正清单来源行重复')
    for change in changed:
        target=change['new'];d=expected.get(target['source_row']);proof=target.get('native_topology_evidence')
        good=bool(d and proof and d['pipeline']==target['pipeline'] and str(d['number'])==str(target['number']))
        for actual,declared in ((change['old'],d.get('baseline',{}) if d else {}),(target,d.get('current',{}) if d else {})):
            good=good and actual.get('page_stem')==declared.get('page_stem') and all(abs(actual.get(k,1e20)-declared.get(k,-1e20))<1e-6 for k in ('x_mm','y_mm'))
        (verified if good else unexpected).append(change)
    unused=[d for key,d in expected.items() if key not in {c['new']['source_row'] for c in verified}]
    return verified,unexpected,unused


def run(unit='PD60',revision='latest',baseline_workbook=None,workers=None,verified_corrections=None):
    config=unit_config(unit);validate_management_transfers(config,unit);aliases=config.get('pipeline_aliases',{})
    workers=config.get('page_workers',2) if workers is None else workers
    if workers<1:raise ValueError('预检工作进程必须大于等于1')
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    table_aliases={**aliases,**config.get('table_pipeline_aliases',{})};paths_config=configured_paths(config,unit)
    incoming=ROOT/'PLT文件转换'/unit
    frame_evidence=validate_coordinate_frame(config,paths_config['idf_dir'],ROOT,unit)
    baseline_path=Path(baseline_workbook) if baseline_workbook else incoming/f'北海{unit}_标注问题清单.xlsx'
    previous=load_workbook(baseline_path,read_only=True)
    if '标注定位清单' in previous:
        positions=list(previous['标注定位清单'].values)[1:]
    elif not baseline_workbook:
        positions=json.loads(audit_path(unit).read_text(encoding='utf-8'))['sheets']['标注定位清单'][1:]
    else:raise ValueError('指定比较基准必须包含完整定位记录；请使用内部审计记录对应的完整历史工作簿')
    baseline={int(r[3]):{'page_stem':r[0],'x_mm':r[5],'y_mm':r[6]} for r in positions if r[1]=='焊口'}
    old_issues={int(r[6]):list(r) for r in list(previous['未标注编号'].values)[1:] if r[2]=='焊口'}
    management_baseline={(r[0].rsplit('_Sht_',1)[0],r[1],str(r[2])):{'page_stem':r[0],'x_mm':r[5],'y_mm':r[6]}
                         for r in positions if r[1] in ('支架','阀门','法兰')}
    old_management_issues={(r[0].rsplit('_Sht_',1)[0],r[2],str(r[3])):list(r)
                           for r in list(previous['未标注编号'].values)[1:] if r[2] in ('支架','阀门','法兰')}
    previous.close()
    rows,_=read_csv(ROOT/'焊口表.csv');rows=remap_rows(rows,table_aliases,config.get('weld_pipeline_transfers'));groups=defaultdict(list)
    for p in incoming.rglob('*.plt'):groups[p.stem.rsplit('_Sht_',1)[0]].append(p)
    all_mapped=[];missing=[];resolved=[];changed=[];lost=[]
    baseline_kinds={k[1] for k in management_baseline}|{k[1] for k in old_management_issues}
    tables=load_management_tables(ROOT,[k for k in ('valve','flange','support') if LABEL_NAMES[k] in baseline_kinds])
    for kind,table in tables.items():table['rows']=remap_rows(table['rows'],table_aliases,[t for t in config.get('management_pipeline_transfers',[]) if t['kind']==kind])
    management_mapped=[];management_missing=[];management_resolved=[];management_changed=[];management_lost=[]
    management_audit=[];management_review=[];management_counts=Counter();jobs=[];source_drawing_issues=[]
    for line,paths in sorted(groups.items()):
        scoped={kind:dict(table,rows=[r for r in table['rows'] if r['管线号']==line]) for kind,table in tables.items()}
        jobs.append({'line':line,'paths':sorted(paths),'paths_config':paths_config,'config':config,
                     'unit':unit,'rows':[r for r in rows if r['管线号']==line],'tables':scoped})
    with (ProcessPoolExecutor(max_workers=workers) if workers>1 else nullcontext(None)) as executor:
        results=executor.map(pipeline_preflight,jobs) if executor else map(pipeline_preflight,jobs)
        for index,result in enumerate(results,1):
            line=result['line'];mapped=result['mapped'];mt=result['management_mapped'];mi=result['management_missing']
            source_drawing_issues.extend(result.get('source_drawing_issues',[]))
            management_mapped.extend(mt);management_missing.extend(mi)
            management_audit.extend(result['management_audit']);management_review.extend(result['management_review']);management_counts.update(result['management_counts'])
            for target in mt:
                key=(line,LABEL_NAMES[target['kind']],str(target['number']));old=management_baseline.get(key)
                if key in old_management_issues:management_resolved.append(target)
                if old and (old['page_stem']!=target['page_stem'] or math.dist((old['x_mm'],old['y_mm']),(target['x_mm'],target['y_mm']))>.2):
                    management_changed.append({'key':key,'old':old,'new':target})
            for issue in mi:
                if (line,issue[2],str(issue[3])) in management_baseline:management_lost.append(issue)
            all_mapped.extend(mapped)
            for t in mapped:
                old=baseline.get(t['source_row'])
                if old and (old['page_stem']!=t['page_stem'] or math.dist((old['x_mm'],old['y_mm']),(t['x_mm'],t['y_mm']))>.2):
                    changed.append({'pipeline':line,'number':t['number'],'old':old,'new':t})
                if t['source_row'] in old_issues:resolved.append(t)
            for entry in result['missing']:
                missing.append(entry)
                if entry['target']['source_row'] in baseline:lost.append(entry)
            if index%25==0 or index==len(jobs):print(f'Preflight {index}/{len(jobs)} pipelines; {workers} workers',flush=True)
    report={'revision':revision,'unit':unit,'baseline_workbook':str(baseline_path),'summary':{'mapped':len(all_mapped),'unresolved':len(missing),'newly_resolved':len(resolved),
                'changed_previous':len(changed),'lost_previous':len(lost),
                'management_mapped':len(management_mapped),'management_unresolved':len(management_missing),
                'management_newly_resolved':len(management_resolved),'management_changed_previous':len(management_changed),
                'management_lost_previous':len(management_lost)},'newly_resolved':resolved,'unresolved':missing,
            'changed_previous':changed,'lost_previous':lost,'mapped':all_mapped}
    report.update(management_mapped=management_mapped,management_unresolved=management_missing,
                  management_newly_resolved=management_resolved,management_changed_previous=management_changed,
                  management_lost_previous=management_lost)
    report.update(management_audit=management_audit,management_review=management_review,management_counts=dict(management_counts))
    report['coordinate_frame_evidence']=frame_evidence
    report['source_drawing_issues']=source_drawing_issues
    report['workers']=workers
    declared=json.loads(Path(verified_corrections).read_text(encoding='utf-8')) if verified_corrections else []
    verified,unexpected,unused=verify_declared_corrections(changed,declared)
    report.update(verified_previous_changes=verified,unexpected_previous_changes=unexpected,unused_verified_corrections=unused)
    report['summary'].update(verified_previous_changes=len(verified),unexpected_previous_changes=len(unexpected),unused_verified_corrections=len(unused))
    report['verified_corrections_file']=str(verified_corrections) if verified_corrections else None
    report['regression_passed']=not any((unexpected,unused,lost,management_changed,management_lost))
    folder=AUDIT;folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'preflight_{revision}.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PREFLIGHT',report['summary'],flush=True)
    print('RESOLVED',[(t['pipeline'],t['number'],t['mapping_method']) for t in resolved],flush=True)
    print('CHANGED',[(t['pipeline'],t['number']) for t in changed],flush=True)
    print('REMAINING',[(t['target']['pipeline'],t['target']['number']) for t in missing],flush=True)
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--unit',default='PD60');ap.add_argument('--revision',default='latest')
    ap.add_argument('--baseline-workbook',type=Path,help='固定系列核对的初始问题清单，避免与正在重建的清单比较')
    ap.add_argument('--workers',type=int,help='管线关联预检进程数，默认沿用单元配置；1为串行')
    ap.add_argument('--verified-corrections',type=Path,help='已经逐项核验的既有落点校正，严格匹配来源行、原位置、新位置及拓扑证据')
    args=ap.parse_args();report=run(args.unit,args.revision,args.baseline_workbook,args.workers,args.verified_corrections)
    raise SystemExit(0 if report['regression_passed'] else 2)
