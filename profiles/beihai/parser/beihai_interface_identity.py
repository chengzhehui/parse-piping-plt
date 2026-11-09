"""Recover changed model coordinates through unique, stable component interfaces.

The reference IDF identifies the source weld's two owners only. All paper
geometry still comes from the current IDF, HIT and PLT. Original matches win.
"""
from collections import defaultdict
from itertools import combinations
from pathlib import Path
import math

from project_paths import WORKSPACE
from beihai_unit_profile import reference_idf_path
from beihai_geometry import load_model, beihai_candidates, resolve_pipe_interiors
from render_complete_pdms import resolve_pipeline


def current_pipe_interior(point,model):
    for c in model['components']:
        if c['code'] not in (100,101) or len(c['ports'])!=2:continue
        a,b=c['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
        f=sum((point[k]-a[k])*v[k] for k in range(3))/n if n else -1
        if 0<f<1 and math.dist(point,[a[k]+f*v[k] for k in range(3)])<=.1:return True
    return False


def interface_identity(point, reference, current):
    indexes=[]
    for model in (reference,current):
        index=defaultdict(list)
        for component in model['components']:
            if component.get('ref'):index[component['ref']].append(component)
        indexes.append(index)
    old_index,new_index=indexes
    neighbors=[c for c in reference['components'] if c['code'] not in (110,115,120,150)
               and c.get('ref') and any(math.dist(point,p)<=1 for p in c['ports'])]
    stable=[c for c in neighbors if len(old_index[c['ref']])==1
            and len(new_index[c['ref']])==1 and new_index[c['ref']][0]['code']==c['code']]
    interfaces=[]
    for a,b in combinations(stable,2):
        for pa in new_index[a['ref']][0]['ports']:
            for pb in new_index[b['ref']][0]['ports']:
                if math.dist(pa,pb)<=.11:
                    interfaces.append({'refs':[a['ref'],b['ref']], 'coordinate_mm':list(pa),
                        'reference_idf_lines':[a['line'],b['line']],
                        'current_idf_lines':[new_index[a['ref']][0]['line'],new_index[b['ref']][0]['line']]})
    points={tuple(e['coordinate_mm']) for e in interfaces}
    return interfaces if len(points)==1 else []


def resolve_interface_welds(rows,model,pages,config=None,line=None,unit=None):
    transferred=[r for r in rows if r.get('_pipeline_transfer')]
    ordinary=[r for r in rows if not r.get('_pipeline_transfer')]
    mapped,missing=resolve_pipeline(ordinary,model,pages,False,beihai_candidates)
    resolve_pipe_interiors(mapped,missing,model,pages)
    # A moved branch may overlap an unrelated new pipe at its old coordinate.
    # Such rows must first prove their old/new UCI ownership, even when the old
    # coordinate happens to produce a plausible paper candidate.
    _,forced=resolve_pipeline(transferred,model,pages,False,lambda *args:[])
    missing.extend(forced)
    transfer_ids={r['_row'] for r in transferred}
    config=config or {};pattern=config.get('weld_reference_idf_pattern')
    if not pattern or not missing:return mapped,missing
    path=reference_idf_path(config,unit,line)
    if not path.is_file():return mapped,missing
    reference=load_model(path,config.get('weld_reference_coordinate_offset_mm'))
    proposals={}
    for t in missing:
        q=t['coordinate_mm']
        # Current interfaces retain their existing interpretation, even if the
        # paper evidence is insufficient. No nearest-coordinate substitution.
        if t['source_row'] not in transfer_ids:
            if any(math.dist(q,p)<=1 for c in model['components'] for p in c['ports']):continue
            if current_pipe_interior(q,model):continue
        proof=interface_identity(q,reference,model)
        if proof:proposals[t['source_row']]=proof
    if not proposals:return mapped,missing
    copied=[]
    for row in rows:
        copy=dict(row)
        if row['_row'] in proposals:
            copy['焊点位置']=','.join(map(str,proposals[row['_row']][0]['coordinate_mm']))
        copied.append(copy)
    trial,remaining=resolve_pipeline(copied,model,pages,False,beihai_candidates)
    resolve_pipe_interiors(trial,remaining,model,pages)
    trial_by_row={t['source_row']:t for t in trial}
    # Resolve in full pipeline context, and reject the migration batch if it
    # could change any established weld, including its sheet assignment.
    if any(t['source_row'] not in trial_by_row or
           t['page_stem']!=trial_by_row[t['source_row']]['page_stem'] or
           math.dist((t['x_mm'],t['y_mm']),(trial_by_row[t['source_row']]['x_mm'],trial_by_row[t['source_row']]['y_mm']))>1e-6
           for t in mapped):return mapped,missing
    candidates=[t for t in trial if t['source_row'] in proposals]
    hit_refs={h['ref'] for p in pages.values() for h in p['hits']}
    accepted=set()
    for t in candidates:
        proof=proposals[t['source_row']]
        physical=sorted({ref for e in proof for ref in e['refs']
                         if '/' in ref and not ref.startswith(('LSTU_','HSTU_')) and ref in hit_refs})
        if not physical:continue
        if any(other['source_row']!=t['source_row'] and other['page_stem']==t['page_stem']
               and math.dist((t['x_mm'],t['y_mm']),(other['x_mm'],other['y_mm']))<.25
               for other in mapped+candidates):continue
        original=next(x for x in missing if x['source_row']==t['source_row'])
        glyph=any(math.dist((t['x_mm'],t['y_mm']),(d['x_mm'],d['y_mm']))<.25
                  for d in pages[t['page_stem']]['dots'])
        if config.get('weld_interface_require_glyph',False) and not glyph:continue
        t['model_query_mm']=t['coordinate_mm'];t['coordinate_mm']=original['coordinate_mm']
        t['source_coordinate_mm']=original['coordinate_mm']
        t['interface_identity_evidence']={'reference_idf':str(path),'interfaces':proof,
            'source_coordinate_mm':t['source_coordinate_mm'],'model_query_mm':t['model_query_mm'],
            'physical_refs_in_hit':physical,'native_weld_glyph':glyph,'native_method':t['mapping_method']}
        t['mapping_method']='stable-component-interface:'+t['mapping_method']
        t.setdefault('review_notes',[]).append({'reason':'新旧IDF接口坐标不一致；按相同元件UCI的唯一接口定位，请核对表与图纸版本及处理差异。'})
        mapped.append(t);accepted.add(t['source_row'])
    missing[:]=[t for t in missing if t['source_row'] not in accepted]
    return mapped,missing


def resolve_welds(rows,model,pages,config=None,line=None,unit=None):
    mapped,missing=resolve_interface_welds(rows,model,pages,config,line,unit)
    from beihai_reference_recovery import recover_reference_welds
    mapped,missing=recover_reference_welds(rows,mapped,missing,model,pages,config or {},line,unit)
    from beihai_topology_ports import correct_topology_ports
    from beihai_geometry import native_axis_covers,pipe_chain_anchors
    mapped,missing=correct_topology_ports(rows,mapped,missing,model,pages,config or {},beihai_candidates,native_axis_covers,pipe_chain_anchors)
    for t in mapped:
        transfer=next((r['_pipeline_transfer'] for r in rows if r['_row']==t['source_row'] and r.get('_pipeline_transfer')),None)
        if transfer:
            t['pipeline_transfer_evidence']=transfer
            t.setdefault('review_notes',[]).append({'reason':f'原表管线 {transfer["source_pipeline"]} 的元件已出现在 {line}；按新旧UCI归属及原图端口关联，保留原编号与来源行，请核对设计分管线变更。'})
        if t['mapping_method']=='beihai-single-pipe-single-native-axis-free-end':
            t.setdefault('review_notes',[]).append({'reason':'HIT为空；按唯一模型管子、原图唯一直管及一致投影方向识别自由端，请核对单管端点。'})
    return mapped,missing
