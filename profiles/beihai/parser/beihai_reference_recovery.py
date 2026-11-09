"""Reference-model owners, current topology, and independent paper agreement."""
from collections import defaultdict
from itertools import permutations
import math
from beihai_geometry import load_model,beihai_candidates,resolve_pipe_interiors
from render_complete_pdms import resolve_pipeline
from project_paths import WORKSPACE
from beihai_unit_profile import reference_idf_path


def rigid_owner_points(q,old,new):
    if old['code']!=new['code'] or len(old['ports'])!=len(new['ports']) or len(old['ports'])>3:return []
    results=[]
    for ports in permutations(new['ports']):
        shift=[ports[0][k]-old['ports'][0][k] for k in range(3)]
        if all(math.dist([p[k]+shift[k] for k in range(3)],r)<=.11 for p,r in zip(old['ports'],ports)):
            results.append({'ref':old['ref'],'code':old['code'],'reference_idf_line':old['line'],
                'current_idf_line':new['line'],'shift_mm':shift,'coordinate_mm':[q[k]+shift[k] for k in range(3)]})
    return results if len(results)==1 else []


def directed_owner_points(q,old,new):
    """Allow leg lengths to change only when every signed 3D direction agrees."""
    if old['code']!=new['code'] or old.get('skey')!=new.get('skey') or len(old['ports'])!=len(new['ports']):return []
    if old['code'] not in (35,45,55,105,130):return []
    def directions(c):
        center=c['segments'][0]['b'] if c['code'] in (35,45) else [sum(p[k] for p in c['ports'])/len(c['ports']) for k in range(3)]
        result=[]
        for p in c['ports']:
            v=[p[k]-center[k] for k in range(3)];length=math.sqrt(sum(x*x for x in v))
            if length<.01:return []
            result.append([x/length for x in v])
        return result
    a,b=directions(old),directions(new)
    if not a or not b:return []
    orders=[order for order in permutations(range(len(b))) if all(math.dist(a[i],b[j])<.001 for i,j in enumerate(order))]
    if len(orders)!=1:return []
    index=min(range(len(a)),key=lambda i:math.dist(q,old['ports'][i]))
    if math.dist(q,old['ports'][index])>1:return []
    return [{'ref':old['ref'],'code':old['code'],'reference_idf_line':old['line'],'current_idf_line':new['line'],
             'coordinate_mm':list(new['ports'][orders[0][index]]),'reference_directions':a,'current_directions':b,'port_order':list(orders[0])}]


def straight_pipe_chain(pipe,model):
    pipes=[c for c in model['components'] if c['code'] in (100,101) and len(c['ports'])==2]
    direction=[pipe['ports'][1][k]-pipe['ports'][0][k] for k in range(3)]
    length=math.sqrt(sum(v*v for v in direction))
    if not length:return []
    def on_axis(p):
        d=[p[k]-pipe['ports'][0][k] for k in range(3)]
        f=sum(d[k]*direction[k] for k in range(3))/(length*length)
        return math.dist(p,[pipe['ports'][0][k]+f*direction[k] for k in range(3)])<=.11
    pending=[pipe];seen=set();chain=[]
    while pending:
        c=pending.pop()
        if c['line'] in seen:continue
        seen.add(c['line']);chain.append(c)
        for other in pipes:
            if other['line'] in seen or not all(on_axis(p) for p in other['ports']):continue
            if any(math.dist(a,b)<=.11 for a in c['ports'] for b in other['ports']):pending.append(other)
    return chain


def split_pipe_interface(pipe,fitting,model):
    """Follow only connected straight pipe subdivisions, stopping at fittings."""
    chain=straight_pipe_chain(pipe,model)
    matches=[p for p in fitting['ports'] if any(math.dist(p,b)<=.11 for c in chain for b in c['ports'])]
    points={tuple(p) for p in matches}
    if len(points)!=1:return []
    return [{'coordinate_mm':list(next(iter(points))),'refs':[pipe['ref'],fitting['ref']],
             'pipe_chain':[{'ref':c['ref'],'idf_line':c['line'],'ports':c['ports']} for c in chain],
             'fitting_idf_line':fitting['line']}]


def free_boundary_identity(q,old,new,reference,current,hit_refs):
    if old['code'] not in (100,101) or new['code']!=old['code'] or len(old['ports'])!=2 or len(new['ports'])!=2:return None
    index=min(range(2),key=lambda i:math.dist(q,old['ports'][i]))
    a,b=old['ports'];u=[b[k]-a[k] for k in range(3)]
    a2,b2=new['ports'];v=[b2[k]-a2[k] for k in range(3)]
    lengths=[math.sqrt(sum(x*x for x in d)) for d in (u,v)]
    if min(lengths)<.01:return None
    alignment=sum(u[k]*v[k] for k in range(3))/(lengths[0]*lengths[1])
    if abs(alignment)<.99999:return None
    current_index=index if alignment>0 else 1-index
    other=old['ports'][1-index];new_other=new['ports'][1-current_index]
    old_anchors=[c for c in reference['components'] if c['code'] not in (100,101,110,115,120,150) and c['ref']
                 and any(math.dist(other,p)<=.11 for p in c['ports'])]
    verified=[]
    for anchor in old_anchors:
        matching=[c for c in current['components'] if c['ref']==anchor['ref'] and c['code']==anchor['code']]
        if len(matching)==1 and anchor['ref'] in hit_refs and any(math.dist(new_other,p)<=.11 for p in matching[0]['ports']):verified.append(anchor['ref'])
    if not verified:return None
    chain=straight_pipe_chain(new,current);boundaries=[]
    for pipe in chain:
        for point in pipe['ports']:
            connected=[c for c in current['components'] if c['code'] not in (110,115,120,150) and any(math.dist(point,p)<=.11 for p in c['ports'])]
            if len(connected)==1:boundaries.append(point)
    points={tuple(p) for p in boundaries}
    if len(points)!=1:return None
    point=next(iter(points))
    return {'kind':'free-pipe-boundary-owner','coordinate_mm':list(point),'owners':[{
        'ref':old['ref'],'code':old['code'],'reference_idf_line':old['line'],'current_idf_line':new['line'],
        'source_port_index':index,'independent_opposite_refs':verified,
        'pipe_chain':[{'ref':p['ref'],'idf_line':p['line'],'ports':p['ports']} for p in chain]}]}


def identity_proposals(q,reference,current,hit_refs):
    old_index=defaultdict(list);new_index=defaultdict(list)
    for c in reference['components']:old_index[c['ref']].append(c)
    for c in current['components']:new_index[c['ref']].append(c)
    owners=[c for c in reference['components'] if c['code'] not in (110,115,120,150) and c['ref']
            and any(math.dist(q,p)<=1 for p in c['ports'])]
    stable=[c for c in owners if len(old_index[c['ref']])==1 and len(new_index[c['ref']])==1
            and new_index[c['ref']][0]['code']==c['code']]
    chains=[]
    for pipe in stable:
        if pipe['code'] not in (100,101):continue
        for fitting in stable:
            if fitting['code'] in (100,101) or fitting['ref'] not in hit_refs:continue
            chains.extend(split_pipe_interface(new_index[pipe['ref']][0],new_index[fitting['ref']][0],current))
    if len({tuple(p['coordinate_mm']) for p in chains})==1:
        return {'kind':'split-pipe-owner-chain','coordinate_mm':chains[0]['coordinate_mm'],'owners':chains}
    transforms=[p for c in stable for p in rigid_owner_points(q,c,new_index[c['ref']][0])]
    physical=[p for p in transforms if p['code'] not in (100,101) and p['ref'] in hit_refs]
    if len({tuple(p['coordinate_mm']) for p in physical})==1:
        return {'kind':'rigid-physical-owner','coordinate_mm':physical[0]['coordinate_mm'],'owners':physical}
    if physical:return None
    directed=[p for c in stable if c['ref'] in hit_refs for p in directed_owner_points(q,c,new_index[c['ref']][0])]
    if len({tuple(p['coordinate_mm']) for p in directed})==1:
        return {'kind':'direction-preserved-physical-owner','coordinate_mm':directed[0]['coordinate_mm'],'owners':directed}
    if directed:return None
    if len(owners)==1 and owners[0] in stable:
        boundary=free_boundary_identity(q,owners[0],new_index[owners[0]['ref']][0],reference,current,hit_refs)
        if boundary:return boundary
    # A free pipe boundary or fabrication cut needs agreement between the
    # independently resolved reference and current pipe geometries as well.
    if not owners:
        for c in reference['components']:
            if c['code'] not in (100,101) or len(c['ports'])!=2:continue
            a,b=c['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
            f=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if 0<f<1 and math.dist(q,[a[k]+f*v[k] for k in range(3)])<=.1 and len(new_index[c['ref']])==1:
                transforms.extend(rigid_owner_points(q,c,new_index[c['ref']][0]))
    pipes=[p for p in transforms if p['code'] in (100,101)]
    if len({tuple(p['coordinate_mm']) for p in pipes})==1:
        return {'kind':'rigid-pipe-owner','coordinate_mm':pipes[0]['coordinate_mm'],'owners':pipes}
    return None


def recover_reference_welds(rows,mapped,missing,model,pages,config,line,unit):
    mode=config.get('weld_reference_recovery')
    if not mode or not missing or not config.get('weld_reference_idf_pattern'):return mapped,missing
    path=reference_idf_path(config,unit,line)
    if not path.is_file():return mapped,missing
    reference=load_model(path,config.get('weld_reference_coordinate_offset_mm'))
    hits={h['ref'] for p in pages.values() for h in p['hits']}
    proposals={t['source_row']:identity_proposals(t['coordinate_mm'],reference,model,hits) for t in missing}
    proposals={k:v for k,v in proposals.items() if v}
    if not proposals:return mapped,missing
    old,old_missing=resolve_pipeline(rows,reference,pages,False,beihai_candidates)
    resolve_pipe_interiors(old,old_missing,reference,pages);old_by={t['source_row']:t for t in old}
    queries={t['source_row']:t['model_query_mm'] for t in mapped if t.get('interface_identity_evidence')}
    queries.update({k:p['coordinate_mm'] for k,p in proposals.items()})
    copied=[dict(r,焊点位置=','.join(map(str,queries[r['_row']]))) if r['_row'] in queries else dict(r) for r in rows]
    trial,trial_missing=resolve_pipeline(copied,model,pages,False,beihai_candidates)
    resolve_pipe_interiors(trial,trial_missing,model,pages);by_row={t['source_row']:t for t in trial}
    # Resolve new roots independently of source-table interpolation controls.
    # Existing targets are retained verbatim; only independently reproduced
    # additions are appended after collision checks.
    candidates=[]
    for t in trial:
        row=t['source_row'];old_target=old_by.get(row)
        if row not in proposals or not old_target:continue
        single=next(r for r in copied if r['_row']==row)
        independent,pending=resolve_pipeline([single],model,pages,False,beihai_candidates)
        resolve_pipe_interiors(independent,pending,model,pages)
        if len(independent)!=1:continue
        t=independent[0]
        if t['page_stem']!=old_target['page_stem'] or math.dist([t['x_mm'],t['y_mm']],[old_target['x_mm'],old_target['y_mm']])>.25:continue
        glyph=any(math.dist([t['x_mm'],t['y_mm']],[d['x_mm'],d['y_mm']])<.25 for d in pages[t['page_stem']]['dots'])
        if mode=='glyph' and not glyph:continue
        t['reference_geometry_evidence']={'reference_idf':str(path),'identity':proposals[row],
            'reference_target':old_target,'native_weld_glyph':glyph,'current_native_method':t['mapping_method'],
            'current_native_evidence':t['mapping_evidence'],'model_query_mm':t['coordinate_mm']}
        candidates.append(t)
    accepted=set()
    for t in candidates:
        if any(o['source_row']!=t['source_row'] and o['page_stem']==t['page_stem'] and
               math.dist([t['x_mm'],t['y_mm']],[o['x_mm'],o['y_mm']])<.25 for o in mapped+candidates):continue
        original=next(o for o in missing if o['source_row']==t['source_row'])
        proof=t['reference_geometry_evidence'];proof['source_coordinate_mm']=original['coordinate_mm']
        t['model_query_mm']=t['coordinate_mm'];t['coordinate_mm']=original['coordinate_mm'];t['source_coordinate_mm']=original['coordinate_mm']
        t['mapping_method']='reference-owner-verified:'+t['mapping_method']
        t.setdefault('review_notes',[]).append({'reason':'参考IDF与当前IDF端口独立定位一致；按稳定元件归属、分段链或刚性平移关联，请复核版本及接口。'})
        mapped.append(t);accepted.add(t['source_row'])
    missing[:]=[t for t in missing if t['source_row'] not in accepted]
    return mapped,missing
