"""Resolve coincident roots using complete native bodies and port ownership."""
import math
from pdms_weld_geometry import projection


METHOD='native-fitting-owned-port-assignment'


def owned_ports(component,model,pages,mapped):
    """Return independently reproducible assignments, never a nearest weld."""
    c=component;result=[]
    for stem,page in pages.items():
        hits=[h for h in page['hits'] if h['ref']==c['ref']]
        if len(hits)!=1:continue
        root=(hits[0]['x_mm'],hits[0]['y_mm'])
        if c['code']==45 and c['skey'] in ('TEBW','TESW') and len(c['ports'])==3:
            center=c['segments'][0]['b'];vectors=[[p[k]-center[k] for k in range(3)] for p in c['ports']]
            main=[(i,j) for i in range(3) for j in range(i+1,3)
                  if math.dist([v/math.dist(c['ports'][i],center) for v in vectors[i]],
                               [-v/math.dist(c['ports'][j],center) for v in vectors[j]])<.01
                  ] if all(math.dist(p,center)>1 for p in c['ports']) else []
            if len(main)!=1:continue
            arms={}
            for axis in page['heavy_segments']:
                if axis.get('stroke_count',0)<3:continue
                for a,b in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                    if math.dist(a,root)<.15 and 3<math.dist(root,b)<30:arms[tuple(b)]=axis['offset']
            if len(arms)!=3:continue
            if sum(any(math.dist(p,(d['x_mm'],d['y_mm']))<.6 for d in page['dots']) for p in arms)<2:continue
            assignment={}
            for index in main[0]:
                direction=projection(vectors[index]);length=math.hypot(*direction)
                if length<.01:break
                u=[v/length for v in direction]
                matches=[p for p in arms if sum((p[k]-root[k])*u[k] for k in (0,1))>1
                         and abs((p[0]-root[0])*u[1]-(p[1]-root[1])*u[0])<.15]
                if len(matches)!=1:break
                assignment[index]=matches[0]
            if len(assignment)!=2 or len(set(assignment.values()))!=2:continue
            branch=next(i for i in range(3) if i not in assignment)
            assignment[branch]=next(p for p in arms if p not in assignment.values())
            a,b=[assignment[i] for i in main[0]];va=[a[k]-root[k] for k in (0,1)];vb=[b[k]-root[k] for k in (0,1)]
            if sum(va[k]*vb[k] for k in (0,1))>=0 or abs(va[0]*vb[1]-va[1]*vb[0])/math.hypot(*va)>.15:continue
            for index,point in assignment.items():
                result.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],
                    'component_ref':c['ref'],'idf_line':c['line'],'model_port_index':index,
                    'kind':'tee-main-run-opposite-arms-branch-by-bijection',
                    'hit_mm':root,'main_model_indices':main[0],
                    'native_arms':[{'point':p,'axis_offset':arms[p]} for p in sorted(arms)]})
        elif c['code']==126 and c['skey']=='NRSC' and len(c['ports'])==2:
            bodies=[o for o in page['port_outlines'] if 3<math.dist(*o['ports'])<6
                    and math.dist(root,[(o['ports'][0][k]+o['ports'][1][k])/2 for k in (0,1)])<.15]
            if len(bodies)!=1:continue
            body=bodies[0]
            for index,q in enumerate(c['ports']):
                direction=projection([q[k]-c['ports'][1-index][k] for k in range(3)]);length=math.hypot(*direction)
                if length<.01:continue
                u=[v/length for v in direction]
                face=max(body['ports'],key=lambda p:sum((p[k]-root[k])*u[k] for k in (0,1)))
                if abs((face[0]-root[0])*u[1]-(face[1]-root[1])*u[0])>.15:continue
                for pipe in model['components']:
                    if pipe['code'] not in (100,101) or len(pipe['ports'])!=2:continue
                    ends=[p for p in pipe['ports'] if math.dist(p,q)<.11]
                    if len(ends)!=1:continue
                    other=next(p for p in pipe['ports'] if math.dist(p,q)>=.11)
                    controls=[t for t in mapped if t['page_stem']==stem and math.dist(t.get('model_query_mm',t['coordinate_mm']),other)<.11
                              and 'interpolation' not in t['mapping_method']]
                    for control in controls:
                        anchor=(control['x_mm'],control['y_mm'])
                        for axis in page['heavy_segments']:
                            if axis.get('stroke_count',0)<3:continue
                            for point,end in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                                delta=[point[k]-face[k] for k in (0,1)]
                                if math.dist(end,anchor)>.15 or math.dist(point,end)<2:continue
                                if not 1<sum(delta[k]*u[k] for k in (0,1))<1.4 or abs(delta[0]*u[1]-delta[1]*u[0])>.15:continue
                                result.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],
                                    'component_ref':c['ref'],'idf_line':c['line'],'model_port_index':index,
                                    'kind':'nrsc-center-hit-contour-and-connected-pipe-end',
                                    'native_body':body,'hit_mm':root,'axis_offset':axis['offset'],
                                    'pipe_ref':pipe['ref'],'pipe_idf_line':pipe['line'],
                                    'control_source_row':control['source_row'],'control_xy_mm':anchor})
    unique={}
    for t in result:unique.setdefault(t['model_port_index'],{})[(t['page_stem'],t['x_mm'],t['y_mm'])]=t
    return [next(iter(group.values())) for group in unique.values() if len(group)==1]


def correct_coincident_ports(mapped,model,pages):
    """Keep the proven neighbor; move only an independently owned native port."""
    suspect={v['source_row'] for i,t in enumerate(mapped) for o in mapped[i+1:]
             if t['page_stem']==o['page_stem'] and math.dist((t['x_mm'],t['y_mm']),(o['x_mm'],o['y_mm']))<.25
             for v in (t,o)}
    for c in model['components']:
        if c['code'] not in (45,126):continue
        related=[t for t in mapped if t['source_row'] in suspect and any(math.dist(t.get('model_query_mm',t['coordinate_mm']),q)<.11 for q in c['ports'])]
        if not related:continue
        assignments=owned_ports(c,model,pages,mapped)
        for t in related:
            query=t.get('model_query_mm',t['coordinate_mm'])
            choices=[a for a in assignments if math.dist(query,c['ports'][a['model_port_index']])<.11]
            if len(choices)!=1:continue
            a=choices[0];point=(a['x_mm'],a['y_mm'])
            if t['page_stem']==a['page_stem'] and math.dist(point,(t['x_mm'],t['y_mm']))<.25:continue
            if any(o is not t and o['page_stem']==a['page_stem'] and math.dist(point,(o['x_mm'],o['y_mm']))<.25 for o in mapped):continue
            proof={**a,'model_query_mm':query,'previous':{k:t[k] for k in ('page_stem','x_mm','y_mm','mapping_method')}}
            t.update(page_stem=a['page_stem'],x_mm=a['x_mm'],y_mm=a['y_mm'],mapping_method=METHOD,
                     mapping_evidence=proof,native_topology_evidence=proof)
