"""Render native PDMS pages with all EP3D weld, management and spool numbers."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import csv
import json
import math
from pathlib import Path
from project_paths import HISTORICAL_SAMPLES
from statistics import median
import time

import fitz

from analyze_plt_bundle import decode_plt,read_hit
from audit_pdms_export import TABLES,read_csv,coordinate,model_components
from pdms_weld_geometry import (native_weld_dots,component_port_outlines,
                                heavy_straight_segments,weld_candidates)
from pdms_unified_layout import layout,render_svg


def nearest_point(point,a,b):
    v=(b[0]-a[0],b[1]-a[1])
    n=v[0]**2+v[1]**2
    t=max(0,min(1,((point[0]-a[0])*v[0]+(point[1]-a[1])*v[1])/n)) if n else 0
    p=(a[0]+v[0]*t,a[1]+v[1]*t)
    return p,math.dist(point,p),t


def spool_anchor(weld,page):
    root=(weld['x_mm'],weld['y_mm'])
    incident=[]
    for segment in page['heavy_segments']:
        a,b=segment['a'],segment['b']
        point,distance,t=nearest_point(root,a,b)
        length=math.dist(a,b)
        if distance<.9 and length>1.375:
            incident.append((distance,-min(length,40),point,a,b,t))
    if not incident:
        # Chengda also permits decoded component lines, rather than only the
        # long pipe axes. This covers short reducer/valve assemblies.
        for segment in page['data']['segments']:
            a,b=[tuple(v/10 for v in segment[k]) for k in ('a','b')]
            point,distance,t=nearest_point(root,a,b)
            length=math.dist(a,b)
            if distance<.9 and length>1.375:
                incident.append((distance,-min(length,40),point,a,b,t))
        if not incident:
            return root,'mapped-shop-weld-no-incident-line'
        fallback=True
    else:
        fallback=False
    distance,_,point,a,b,t=min(incident)
    far=b if t<=.5 else a
    available=math.dist(point,far)
    travel=min(3.75,max(1.375,available*.35),max(0,available-.2))
    if travel<=.2:
        return root,'mapped-shop-weld-short-incident-line'
    return (point[0]+(far[0]-point[0])/available*travel,
            point[1]+(far[1]-point[1])/available*travel),('mapped-shop-weld-decoded-component-line' if fallback
                                                      else 'mapped-shop-weld-native-component-line')


def resolve_pipeline(rows,model,pages,strict=True,candidate_resolver=weld_candidates):
    mapped=[]
    unresolved=[]
    for row in rows:
        xyz=coordinate(row['焊点位置'])
        source={'pipeline':row['管线号'],'number':row['焊点编号'],'coordinate_mm':xyz}
        candidates=candidate_resolver(source,model,pages)
        target={'key':f"{row['管线号']}:weld:{row['焊点编号']}",'kind':'weld',
                'pipeline':row['管线号'],'number':row['焊点编号'],'source_row':row['_row'],
                'source_file':'焊口表.csv','weld_type':row['焊点类型'],
                'spool_number':row['管段编号'],'coordinate_mm':xyz,
                'model_query_mm':[xyz[0],xyz[1],xyz[2]-model.get('z_offset_mm',1000)],
                'candidates':candidates,'ref':'','source_table_page':row['页码']}
        if candidates:
            best=candidates[0]
            target.update({k:best[k] for k in ('page_stem','x_mm','y_mm')})
            def priority(e):
                return e['score']+(-100 if e['code']==120 else -40 if e['code']==130 else 15 if e['code']==101 else 0)
            target['mapping_method']=min(best['evidence'],key=priority).get('method','model-interface-HIT-ray-native-weld-symbol')
            target['mapping_evidence']=best['evidence']
            target['confidence']='native-geometry-and-model-interface'
            target['review_notes']=[]
            # Retain disagreements between independently resolved component
            # outlines; explicit WELD IDs take precedence over inferred ports.
            physical_by_ref=defaultdict(list)
            for candidate in candidates:
                for ev in candidate['evidence']:
                    if ev['score']<-10 or (ev['code']==130 and ev['score']<1 and 3.8<ev['along_mm']<4.2):
                        physical_by_ref[ev['ref']].append((ev['score'],candidate['x_mm'],candidate['y_mm']))
            physical=[min(v) for v in physical_by_ref.values()]
            if not any(ev['code']==120 for ev in best['evidence']):
                gaps=[math.dist(a[1:],b[1:]) for i,a in enumerate(physical) for b in physical[i+1:]]
                if gaps and max(gaps)>1.5:
                    target['review_notes'].append({'reason':'two component outlines disagree beyond socket insertion allowance',
                                                   'max_gap_mm':max(gaps),'component_candidates':physical,
                                                   'selected_rule':'socket fitting mouth takes precedence over inserted plain pipe'})
            mapped.append(target)
        else:
            unresolved.append(target)
    # Additional fabrication cuts may lie strictly inside an IDF pipe rather
    # than at its original end. Interpolate only between two already resolved
    # endpoints on the same page and on a proven native straight pipe axis.
    progress=True
    while progress and unresolved:
        progress=False
        for target in list(unresolved):
            q=tuple(target['model_query_mm'])
            choices=[]
            for comp in model['components']:
                if comp['code'] not in (100,101) or len(comp['ports'])!=2:
                    continue
                a,b=comp['ports']
                v=tuple(b[k]-a[k] for k in range(3))
                n=sum(x*x for x in v)
                fraction=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
                if not 0<fraction<1 or math.dist(q,tuple(a[k]+v[k]*fraction for k in range(3)))>.1:
                    continue
                ends=[[m for m in mapped if math.dist(tuple(m['model_query_mm']),p)<=1] for p in (a,b)]
                for ma in ends[0]:
                    for mb in ends[1]:
                        if ma['page_stem']!=mb['page_stem']:
                            continue
                        pa=(ma['x_mm'],ma['y_mm']);pb=(mb['x_mm'],mb['y_mm'])
                        page=pages[ma['page_stem']]
                        axes=[s for s in page['heavy_segments'] if
                              nearest_point(pa,s['a'],s['b'])[1]<.2 and
                              nearest_point(pb,s['a'],s['b'])[1]<.2]
                        if axes:
                            p=tuple(pa[k]+(pb[k]-pa[k])*fraction for k in (0,1))
                            choices.append((ma['page_stem'],p,comp['ref'],fraction,ma['key'],mb['key']))
            unique={(stem,round(p[0],3),round(p[1],3)):c for c in choices for stem,p,*_ in [c]}
            if len(unique)==1:
                stem,p,ref,fraction,ka,kb=next(iter(unique.values()))
                target.update({'page_stem':stem,'x_mm':p[0],'y_mm':p[1],
                    'mapping_method':'straight-pipe-extra-cut-interpolation','confidence':'two-proven-pipe-ends',
                    'mapping_evidence':{'pipe_ref':ref,'fraction':fraction,'end_targets':[ka,kb]}})
                mapped.append(target)
                unresolved.remove(target)
                progress=True
    if unresolved and strict:
        raise ValueError(f'Unresolved welds: {[(t["pipeline"],t["number"]) for t in unresolved]}')
    return mapped if strict else (mapped,unresolved)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-dir',type=Path,default=HISTORICAL_SAMPLES/'PDMS_Export')
    ap.add_argument('--out-dir',type=Path,default=HISTORICAL_SAMPLES/'complete_output')
    ap.add_argument('--pipeline',help='Limit rendering to one pipeline; all source associations are still audited')
    ap.add_argument('--png',action='store_true')
    ap.add_argument('--annotation-scale',type=float,default=None,
                    help='Annotation magnification relative to the 3.5 mm A2 version')
    ap.add_argument('--font-height-mm',type=float)
    ap.add_argument('--weld-diameter-mm',type=float)
    ap.add_argument('--compact-frames',action=argparse.BooleanOptionalAction,default=None)
    args=ap.parse_args()
    if args.annotation_scale is not None and args.annotation_scale<=0:
        ap.error('--annotation-scale must be positive')
    legacy=args.annotation_scale is not None and args.font_height_mm is None
    font_height=args.font_height_mm if args.font_height_mm is not None else (None if legacy else 6.)
    circle_diameter=args.weld_diameter_mm if args.weld_diameter_mm is not None else (None if legacy else 12.)
    compact=not legacy if args.compact_frames is None else args.compact_frames
    if any(v is not None and v<=0 for v in (font_height,circle_diameter)):
        ap.error('Font height and circle diameter must be positive')
    out=args.out_dir
    out.mkdir(parents=True,exist_ok=True)
    ex=args.input_dir/'export'
    pages={}
    models={}
    hit_index=defaultdict(list)
    for p in sorted(ex.glob('*.plt')):
        line,number=p.stem.rsplit('_Sht_',1)
        data=decode_plt(p)
        outlines,vertices=component_port_outlines(data)
        hits=read_hit(p.with_suffix('.hit'))
        page={'pipeline':line,'page':int(number),'data':data,'hits':hits,
              'dots':native_weld_dots(data),'port_outlines':outlines,'vertices':vertices,
              'heavy_segments':heavy_straight_segments(data),'targets':[]}
        pages[p.stem]=page
        for hit in hits:
            hit_index[(line,hit['ref'])].append(hit|{'page_stem':p.stem})
    for p in ex.glob('*.idf'):
        if p.stem=='transfer':
            continue
        data,components=model_components(p)
        models[p.stem]={'data':data,'components':components}
    weld_rows,metadata=read_csv(args.input_dir/'焊口表.csv')
    origin_checks=[]
    for row in weld_rows:
        xyz=coordinate(row['焊点位置'])
        q=(xyz[0],xyz[1],xyz[2]-1000)
        distance=min(math.dist(q,p) for c in models[row['管线号']]['components'] for p in c['ports'])
        origin_checks.append(distance)
    for row,distance in zip(weld_rows,origin_checks):
        if distance<=.1:
            continue
        xyz=coordinate(row['焊点位置'])
        q=(xyz[0],xyz[1],xyz[2]-1000)
        interior=False
        for c in models[row['管线号']]['components']:
            if c['code'] not in (100,101) or len(c['ports'])!=2:
                continue
            a,b=c['ports'];v=tuple(b[k]-a[k] for k in range(3));n=sum(x*x for x in v)
            t=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if 0<t<1 and math.dist(q,tuple(a[k]+v[k]*t for k in range(3)))<=.1:
                interior=True
        if not interior:
            raise ValueError(f'Weld frame or topology mismatch at row {row["_row"]}')
    # Independent plot/HIT registration: explicit welds with native filled
    # symbols determine the offset; field-only symbols are not calibration data.
    offsets=[]
    for stem,page in pages.items():
        model=models[page['pipeline']]
        explicit={c['ref'] for c in model['components'] if c['code']==120}
        for hit in page['hits']:
            if hit['ref'] not in explicit:
                continue
            pairs=[(math.dist((hit['x_mm'],hit['y_mm']),(d['x_mm'],d['y_mm'])),d) for d in page['dots']]
            if pairs:
                error,dot=min(pairs,key=lambda x:x[0])
                if error<1.1:
                    offsets.append((dot['x_mm']-hit['x_mm'],dot['y_mm']-hit['y_mm']))
    registration={'sample_count':len(offsets),'dx_mm':median(v[0] for v in offsets),
                  'dy_mm':median(v[1] for v in offsets),'samples':offsets}
    if abs(registration['dx_mm']-.9)>.01 or abs(registration['dy_mm'])>.01:
        raise ValueError('PLT/HIT registration differs from verified +0.9 mm X transform')
    welds=[]
    for line,model in models.items():
        rows=[r for r in weld_rows if r['管线号']==line]
        local_pages={s:p for s,p in pages.items() if p['pipeline']==line}
        welds.extend(resolve_pipeline(rows,model,local_pages))
    targets=list(welds)
    for kind,name,column in TABLES:
        rows,_=read_csv(args.input_dir/name)
        for row in rows:
            matches=hit_index[(row['管线号'],row['UCI'])]
            if len(matches)!=1:
                raise ValueError(f'Non-unique management reference {row}')
            hit=matches[0]
            targets.append({'key':f"{row['管线号']}:{kind}:{row[column]}",'kind':kind,
                'pipeline':row['管线号'],'number':row[column],'source_row':row['_row'],'source_file':name,
                'ref':row['UCI'],'page_stem':hit['page_stem'],'x_mm':hit['x_mm']+.9,'y_mm':hit['y_mm'],
                'mapping_method':'unique-HIT-reference-with-native-plot-registration'})
    spool_groups=defaultdict(list)
    for w in welds:
        if w['spool_number']:
            spool_groups[(w['pipeline'],w['page_stem'],w['spool_number'])].append(w)
    spool_count=0
    for (line,stem,number),members in spool_groups.items():
        candidates=[]
        for member in sorted(members,key=lambda w:(w['weld_type']!='S',w['source_row'])):
            anchor,method=spool_anchor(member,pages[stem])
            candidates.append((method.endswith('no-incident-line'),member['source_row'],anchor,method,member))
        _,_,anchor,method,member=min(candidates,key=lambda c:(c[0],c[1]))
        targets.append({'key':f'{line}:spool:{number}:{stem}','kind':'spool','pipeline':line,'number':number,
            'source_row':member['source_row'],'source_rows':[m['source_row'] for m in members],
            'source_file':'焊口表.csv','ref':'','page_stem':stem,'x_mm':anchor[0],'y_mm':anchor[1],
            'mapping_method':method,'related_weld':member['key']})
        spool_count+=1
    for target in targets:
        pages[target['page_stem']]['targets'].append(target)
    # Association results are always saved before the potentially expensive
    # layout phase so every physical root is reviewable independently.
    mapping={'summary':dict(Counter(t['kind'] for t in targets)),'targets':targets,
             'registration':registration,'ep3d_z_offset_mm':1000,
             'max_model_port_distance_mm':max(origin_checks),'weld_csv_metadata':metadata,
             'spool_rule':'One supplied spool number per pipeline/page; prefer S row; native incident pipe root',
             'unresolved_welds':[],
             'review_welds':[{'key':t['key'],'notes':t['review_notes']} for t in welds if t.get('review_notes')]}
    (out/'annotation_mapping.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Mapping:',mapping['summary'],'registration:',registration['sample_count'],flush=True)
    layouts=[]
    for stem,page in pages.items():
        if args.pipeline and page['pipeline']!=args.pipeline:
            continue
        print('Layout',stem,'targets',len(page['targets']),flush=True)
        placed,audit=layout(page['data'],page['targets'],page['heavy_segments'],args.annotation_scale or 2.,
                            font_height,circle_diameter,compact)
        (out/(stem+'_layout.json')).write_text(json.dumps({'targets':page['targets'],'placements':placed,'audit':audit},ensure_ascii=False,indent=2),encoding='utf-8')
        svg=render_svg(page['data'],page['targets'],placed)
        (out/(stem+'.svg')).write_text(svg,encoding='utf-8')
        layouts.append({'page_stem':stem,'pipeline':page['pipeline'],'page':page['page'],
                        'target_counts':dict(Counter(t['kind'] for t in page['targets'])),**audit})
        print('Done',stem,audit['layout_mode'],'conflicts',len(audit['annotation_conflicts']),
              'seconds',audit['elapsed_seconds'],flush=True)
    (out/'layout_audit.json').write_text(json.dumps({'pages':layouts,'summary':{
        'rendered_pages':len(layouts),'pipelines':len({p['pipeline'] for p in layouts}),
        'annotation_conflicts':sum(len(p['annotation_conflicts']) for p in layouts),
        'layout_modes':dict(Counter(p['layout_mode'] for p in layouts))}},ensure_ascii=False,indent=2),encoding='utf-8')
    from export_complete_pdms_pdf import export_pdf
    export_pdf(out,png=args.png)


if __name__=='__main__':
    main()
