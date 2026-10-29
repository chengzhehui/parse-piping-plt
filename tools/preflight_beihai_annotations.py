"""Fast association-only audit; no layout or PDF regeneration.

Compare all source rows with the last delivered workbook and retain per-row
IDF/HIT/native-glyph evidence so each rule revision can be checked independently.
"""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path

from openpyxl import load_workbook
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from audit_pdms_export import read_csv,coordinate
from beihai_geometry import load_model,load_page,beihai_candidates,resolve_pipe_interiors,unresolved_diagnosis
from render_complete_pdms import resolve_pipeline
from beihai_review_report import audit_path

BASE=REPOSITORY
ROOT=BASE.parent/'北海项目'


def run(unit='PD60',revision='latest',baseline_workbook=None):
    incoming=ROOT/'PLT文件转换'/unit
    baseline_path=Path(baseline_workbook) if baseline_workbook else incoming/f'北海{unit}_标注问题清单.xlsx'
    previous=load_workbook(baseline_path,read_only=True)
    if '标注定位清单' in previous:
        positions=list(previous['标注定位清单'].values)[1:]
    elif not baseline_workbook:
        positions=json.loads(audit_path(unit).read_text(encoding='utf-8'))['sheets']['标注定位清单'][1:]
    else:raise ValueError('指定比较基准必须包含完整定位记录；请使用内部审计记录对应的完整历史工作簿')
    baseline={int(r[3]):{'page_stem':r[0],'x_mm':r[5],'y_mm':r[6]} for r in positions if r[1]=='焊口'}
    old_issues={int(r[6]):list(r) for r in list(previous['未标注编号'].values)[1:] if r[2]=='焊口'}
    previous.close()
    rows,_=read_csv(ROOT/'焊口表.csv');groups=defaultdict(list)
    for p in incoming.rglob('*.plt'):groups[p.stem.rsplit('_Sht_',1)[0]].append(p)
    all_mapped=[];missing=[];resolved=[];changed=[];lost=[]
    for line,paths in sorted(groups.items()):
        model=load_model(ROOT/'IDF'/unit/(line+'.idf'));pages={p.stem:load_page(p) for p in paths}
        local=[r for r in rows if r['管线号']==line]
        mapped,unresolved=resolve_pipeline(local,model,pages,False,beihai_candidates)
        resolve_pipe_interiors(mapped,unresolved,model,pages)
        all_mapped.extend(mapped)
        for t in mapped:
            old=baseline.get(t['source_row'])
            if old and (old['page_stem']!=t['page_stem'] or math.dist((old['x_mm'],old['y_mm']),(t['x_mm'],t['y_mm']))>.2):
                changed.append({'pipeline':line,'number':t['number'],'old':old,'new':t})
            if t['source_row'] in old_issues:resolved.append(t)
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
            entry={'target':t,'diagnosis':unresolved_diagnosis(t,model),'near_components':details,'pipe_interiors':interiors,
                   'page_geometry_counts':{s:{'hits':len(p['hits']),'dots':len(p['dots']),'heavy_axes':len(p['heavy_segments'])} for s,p in pages.items()}}
            missing.append(entry)
            if t['source_row'] in baseline:lost.append(entry)
    report={'revision':revision,'unit':unit,'baseline_workbook':str(baseline_path),'summary':{'mapped':len(all_mapped),'unresolved':len(missing),'newly_resolved':len(resolved),
                'changed_previous':len(changed),'lost_previous':len(lost)},'newly_resolved':resolved,'unresolved':missing,
            'changed_previous':changed,'lost_previous':lost,'mapped':all_mapped}
    folder=BASE/'beihai_audit';folder.mkdir(exist_ok=True)
    path=folder/f'preflight_{revision}.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PREFLIGHT',report['summary'],flush=True)
    print('RESOLVED',[(t['pipeline'],t['number'],t['mapping_method']) for t in resolved],flush=True)
    print('CHANGED',[(t['pipeline'],t['number']) for t in changed],flush=True)
    print('REMAINING',[(t['target']['pipeline'],t['target']['number']) for t in missing],flush=True)
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--unit',default='PD60');ap.add_argument('--revision',default='latest')
    ap.add_argument('--baseline-workbook',type=Path,help='固定系列核对的初始问题清单，避免与正在重建的清单比较')
    args=ap.parse_args();run(args.unit,args.revision,args.baseline_workbook)
