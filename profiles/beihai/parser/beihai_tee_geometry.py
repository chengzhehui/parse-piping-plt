"""Native tee ports with long diagram legs and three independently drawn arms."""
import math
from pdms_weld_geometry import projection,native_paths


def tee_third_finite_arm_candidates(weld,model,pages,candidate_resolver):
    """Identify the last native arm only after both other model ports agree."""
    query=weld['coordinate_mm'];choices=[]
    for component in model['components']:
        if component['code']!=45 or component['skey'] not in ('TEBW','TESW') or len(component['ports'])!=3:continue
        index=min(range(3),key=lambda i:math.dist(query,component['ports'][i]))
        if math.dist(query,component['ports'][index])>.11:continue
        controls=[candidate_resolver({'coordinate_mm':p},model,pages,allow_pipe=False,allow_elbow=False)
                  for i,p in enumerate(component['ports']) if i!=index]
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==component['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm']);arms={}
            for axis in page['heavy_segments']:
                if axis.get('stroke_count',0)<3:continue
                for start,end in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                    if math.dist(start,root)<.15 and 3<math.dist(root,end)<30:
                        arms[tuple(end)]=axis['offset']
            if len(arms)!=3:continue
            welded={p for p in arms if any(math.dist(p,(d['x_mm'],d['y_mm']))<.25 for d in page['dots'])}
            if len(welded)<2:continue
            assigned=[];proof=[]
            for group in controls:
                local={(round(t['x_mm'],3),round(t['y_mm'],3)):t for t in group if t['page_stem']==stem}
                if len(local)!=1:break
                t=next(iter(local.values()));matching=[p for p in welded if math.dist(p,(t['x_mm'],t['y_mm']))<.15]
                if len(matching)!=1:break
                assigned.append(matching[0]);proof.append(t)
            if len(assigned)!=2 or len(set(assigned))!=2:continue
            remaining=set(arms)-set(assigned);point=next(iter(remaining))
            choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-235,
                'evidence':[{'ref':component['ref'],'code':45,'idf_line':component['line'],'score':-135,
                    'cross_error_mm':0,'along_mm':math.dist(root,point),
                    'method':'beihai-tee-third-finite-arm-two-independently-resolved-native-ports',
                    'native_body_arms':[{'point':p,'axis_offset':offset,'native_weld_glyph':p in welded} for p,offset in arms.items()],
                    'other_model_port_controls':proof}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def zero_run_olet_body_candidates(weld,model,pages,boundary_distance):
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code']!=40 or c['skey']!='NONE' or len(c['ports'])!=2:continue
        if math.dist(c['segments'][0]['a'],c['segments'][0]['b'])>.11 or math.dist(q,c['ports'][1])>.11:continue
        if math.dist(q,c['ports'][0])<1:continue
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==c['ref'] and h['name'].startswith('OLET ')]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm'])
            if not any(math.dist(root,[d['x_mm'],d['y_mm']])<.15 for d in page['dots']):continue
            for path in native_paths(page['data']):
                ps=path['points']
                if not 5<=len(ps)<=12 or ps[0]!=ps[-1] or min(math.dist(root,p) for p in ps)>.15 or max(math.dist(root,p) for p in ps)>12:continue
                dots=[d for d in page['dots'] if 1<math.dist(root,[d['x_mm'],d['y_mm']])<12
                      and boundary_distance((d['x_mm'],d['y_mm']),ps)<.15]
                if len(dots)!=1:continue
                dot=dots[0]
                choices.append({'page_stem':stem,'x_mm':dot['x_mm'],'y_mm':dot['y_mm'],'score':-230,
                    'evidence':[{'ref':c['ref'],'code':40,'idf_line':c['line'],'score':-130,'cross_error_mm':0,
                        'along_mm':math.dist(root,[dot['x_mm'],dot['y_mm']]),'method':'beihai-zero-main-run-olet-native-body-two-welded-ports',
                        'main_junction_mm':root,'native_body_offset':path['offsets'][0],'native_body_polygon':ps,'dot_offset':dot['offset']}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def extended_tee_candidates(weld,model,pages,axis_covers,candidate_resolver):
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code'] not in (40,45) or c['skey'] not in ('TEBW','TESW') or len(c['ports'])!=3:continue
        if min(math.dist(q,p) for p in c['ports'])>.11:continue
        center=c['segments'][0]['b'];directions=[projection([p[k]-center[k] for k in range(3)]) for p in c['ports']]
        if any(math.hypot(*d)<.01 for d in directions):continue
        directions=[(d[0]/math.hypot(*d),d[1]/math.hypot(*d)) for d in directions]
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==c['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm']);ports=[];symbols=[]
            for u in directions:
                found=[]
                for dot in page['dots']:
                    p=(dot['x_mm'],dot['y_mm']);d=[p[k]-root[k] for k in (0,1)]
                    along=sum(d[k]*u[k] for k in (0,1))
                    if not 1<along<100 or abs(d[0]*u[1]-d[1]*u[0])>.25:continue
                    if axis_covers(page,root,p):found.append((along,p,dot))
                if not found:
                    port=c['ports'][len(ports)]
                    controls=candidate_resolver({'coordinate_mm':port},model,pages,allow_pipe=False,allow_elbow=False)
                    controls=[p for p in controls if p['page_stem']==stem and axis_covers(page,root,(p['x_mm'],p['y_mm']))]
                    unique={(round(p['x_mm'],3),round(p['y_mm'],3)):p for p in controls}
                    if len(unique)!=1:break
                    p=next(iter(unique));d=[p[k]-root[k] for k in (0,1)];along=sum(d[k]*u[k] for k in (0,1))
                    if along<=1 or abs(d[0]*u[1]-d[1]*u[0])>.25:break
                    found=[(along,p,{'offset':None})]
                along,p,dot=min(found,key=lambda x:x[0]);blocked=False
                for hit in page['hits']:
                    if hit['ref']==c['ref']:continue
                    delta=[hit['x_mm']-root[0],hit['y_mm']-root[1]];distance=sum(delta[k]*u[k] for k in (0,1))
                    if .5<distance<along-.5 and abs(delta[0]*u[1]-delta[1]*u[0])<.5:blocked=True
                if blocked:break
                ports.append(p);symbols.append(dot['offset'])
            if len(ports)!=3 or len(set(ports))!=3:continue
            index=min(range(3),key=lambda i:math.dist(q,c['ports'][i]));point=ports[index]
            if symbols[index] is None or sum(s is not None for s in symbols)<2:continue
            choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-210,
                'evidence':[{'ref':c['ref'],'code':c['code'],'idf_line':c['line'],'score':-110,
                    'cross_error_mm':0,'along_mm':math.dist(point,root),'method':'beihai-tee-three-native-welded-arms',
                    'hit_offset_line':hits[0]['line'],'native_ports':ports,'dot_offsets':symbols,'model_port_directions':directions}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def skew_tee_branch_candidates(weld,model,pages,axis_covers,candidate_resolver):
    """Identify a skew branch by eliminating two proven main-run ports.

    The native branch direction may be adjusted on an isometric. Its first
    weld must still lie on the unique third heavy arm from this exact HIT.
    """
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code']!=45 or c['skey']!='TEBW' or len(c['ports'])!=3:continue
        index=min(range(3),key=lambda i:math.dist(q,c['ports'][i]))
        if math.dist(q,c['ports'][index])>.11:continue
        other=[p for i,p in enumerate(c['ports']) if i!=index];center=c['segments'][0]['b']
        vectors=[[p[k]-center[k] for k in range(3)] for p in other]
        lengths=[math.sqrt(sum(v*v for v in d)) for d in vectors]
        if min(lengths)<.1:continue
        if sum(vectors[0][k]*vectors[1][k] for k in range(3))/(lengths[0]*lengths[1])>-.9999:continue
        controls=[candidate_resolver({'coordinate_mm':p},model,pages,allow_pipe=False,allow_elbow=False) for p in other]
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==c['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm']);ends=[]
            for group in controls:
                unique={(round(t['x_mm'],3),round(t['y_mm'],3)):t for t in group if t['page_stem']==stem}
                if len(unique)!=1:break
                point=next(iter(unique))
                if not axis_covers(page,root,point):break
                ends.append(point)
            if len(ends)!=2:continue
            direction=[ends[0][k]-root[k] for k in (0,1)];length=math.hypot(*direction)
            if length<1:continue
            u=[x/length for x in direction];v=[ends[1][k]-root[k] for k in (0,1)]
            if sum(v[k]*u[k] for k in (0,1))>=-1 or abs(v[0]*u[1]-v[1]*u[0])>.25:continue
            dots=[]
            for dot in page['dots']:
                point=(dot['x_mm'],dot['y_mm']);delta=[point[k]-root[k] for k in (0,1)];distance=math.hypot(*delta)
                if not 1<distance<100 or abs(delta[0]*u[1]-delta[1]*u[0])<.5:continue
                if axis_covers(page,root,point):dots.append((distance,point,dot))
            first=[]
            for distance,point,dot in dots:
                ray=[(point[k]-root[k])/distance for k in (0,1)]
                if any(d<distance-.5 and sum((p[k]-root[k])*ray[k] for k in (0,1))>0
                       and abs((p[0]-root[0])*ray[1]-(p[1]-root[1])*ray[0])<.25 for d,p,_ in dots):continue
                if any(h['ref']!=c['ref'] and .5<sum((h[['x_mm','y_mm'][k]]-root[k])*ray[k] for k in (0,1))<distance-.5
                       and abs((h['x_mm']-root[0])*ray[1]-(h['y_mm']-root[1])*ray[0])<.5 for h in page['hits']):continue
                first.append((point,dot))
            if len(first)!=1:continue
            point,dot=first[0]
            choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-210,
                'evidence':[{'ref':c['ref'],'code':45,'idf_line':c['line'],'score':-110,'cross_error_mm':0,
                    'along_mm':math.dist(root,point),'method':'beihai-skew-tee-third-arm-two-proven-main-ports',
                    'main_model_ports':other,'main_native_ports':ends,'dot_offset':dot['offset']}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []
