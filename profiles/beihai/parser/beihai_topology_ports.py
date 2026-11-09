"""Order native fitting ports by independently located adjacent pipe ends.

Skew IDF axes can project onto the same ray. A complete native body plus an
actual connected pipe identifies the port without choosing a nearby symbol.
"""
import math
import re
from beihai_elbow_geometry import curved_elbow_candidates,extended_leg_elbow_candidates
from pdms_weld_geometry import native_paths


def native_ports(component,model,pages):
    found={}
    for stem,page in pages.items():
        hits=[h for h in page['hits'] if h['ref']==component['ref']]
        if len(hits)!=1:continue
        root=(hits[0]['x_mm'],hits[0]['y_mm'])
        if component['code']==130:
            expected={'CKSW':'check-valve-disc-and-seat','CKFL':'check-valve-disc-and-seat','VBFL':'bowtie-valve','VTSW':'bowtie-valve','VGSW':'bowtie-valve'}.get(component['skey'])
            bodies=[b for b in page['valve_bodies'] if b['shape']==expected and
                    min(math.dist(root,b['a']),math.dist(root,b['b']),math.dist(root,b['center']))<1.6]
            for body in bodies:
                # Socket valves have welded mouths at the two contour ends.
                # Flanged valves need their separate flange joint geometry.
                if component['skey'] not in ('CKSW','VTSW','VGSW'):continue
                if not all(any(math.dist(p,(d['x_mm'],d['y_mm']))<.25 for d in page['dots']) for p in (body['a'],body['b'])):continue
                ports=[list(body['a']),list(body['b'])]
                found[(stem,tuple(sorted(map(tuple,ports))))]={'page_stem':stem,'ports':ports,'body':body,'ref':component['ref'],'kind':'native-gate-valve-two-socket-mouths' if component['skey']=='VGSW' else 'native-check-valve-two-socket-mouths'}
        elif component['code']==35:
            for q in component['ports']:
                candidates=curved_elbow_candidates({'coordinate_mm':q},model,{stem:page})
                candidates+=extended_leg_elbow_candidates({'coordinate_mm':q},model,{stem:page},_unordered=True)
                for candidate in candidates:
                    for proof in candidate['evidence']:
                        if proof['ref']!=component['ref'] or len(proof.get('native_ports',[]))!=2:continue
                        ports=[list(p) for p in proof['native_ports']]
                        found[(stem,tuple(sorted(map(tuple,ports))))]={'page_stem':stem,'ports':ports,'body':proof,'ref':component['ref'],'kind':'native-curved-elbow-two-welded-ports'}
        elif component['code']==55 and component['skey'] in ('REBW','RCBW'):
            from beihai_geometry import point_boundary_distance
            for path in native_paths(page['data']):
                polygon=path['points']
                if not 5<=len(polygon)<=8 or polygon[0]!=polygon[-1] or max(math.dist(root,p) for p in polygon)>15:continue
                inside=False
                for a,b in zip(polygon,polygon[1:]):
                    if (a[1]>root[1])!=(b[1]>root[1]) and root[0]<(b[0]-a[0])*(root[1]-a[1])/(b[1]-a[1])+a[0]:inside=not inside
                if not inside:continue
                dots=[d for d in page['dots'] if d.get('fill_offsets') and point_boundary_distance((d['x_mm'],d['y_mm']),polygon)<.15]
                ports=sorted({(d['x_mm'],d['y_mm']) for d in dots})
                if len(ports)!=2 or not 3<math.dist(*ports)<20:continue
                ports=[list(p) for p in ports]
                found[(stem,tuple(map(tuple,ports))) ]={'page_stem':stem,'ports':ports,'ref':component['ref'],
                    'kind':'native-reducer-closed-contour-two-filled-welded-ports',
                    'body':{'polygon':polygon,'body_offset':path['offsets'][0],'weld_offsets':[d['offset'] for d in dots],'hit_mm':list(root)}}
    return list(found.values()) if len(found)==1 else []


def correct_topology_ports(rows,mapped,missing,model,pages,config,candidate_resolver,axis_covers,chain_anchors):
    if not config.get('native_topology_ports'):return mapped,missing
    components=[c for c in model['components'] if c['code'] in (35,55,130) and c['ref'] and len(c['ports'])==2]
    # Only inspect unresolved or coincident distinct model ports. Zero-length
    # source duplicates keep their own separate reviewer issue.
    suspect=[]
    for c in components:
        related=[t for t in mapped+missing if any(math.dist(t.get('model_query_mm',t['coordinate_mm']),p)<.11 for p in c['ports'])]
        if any(t in missing for t in related) or any(a is not b and a.get('page_stem')==b.get('page_stem') and a.get('page_stem')
            and math.dist([a['x_mm'],a['y_mm']],[b['x_mm'],b['y_mm']])<.25
            and math.dist(a.get('model_query_mm',a['coordinate_mm']),b.get('model_query_mm',b['coordinate_mm']))>1 for a in related for b in related):suspect.append(c)
    bodies={c['ref']:native_ports(c,model,pages) for c in suspect}
    for iteration in range(6):
        changes=0
        for c in suspect:
            if not bodies[c['ref']]:continue
            body=bodies[c['ref']][0];stem=body['page_stem'];page=pages[stem];ports=body['ports'];assignments={};proofs={}
            for index,q in enumerate(c['ports']):
                pipes=[p for p in model['components'] if p['code'] in (100,101) and len(p['ports'])==2 and any(math.dist(q,v)<.11 for v in p['ports'])]
                matches=[]
                for pipe in pipes:
                    a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
                    controls=[t for t in mapped if t['page_stem']==stem and math.dist(t.get('model_query_mm',t['coordinate_mm']),other)<.11
                              and 'interpolation' not in t['mapping_method'] and c['ref'] not in t.get('native_topology_evidence',{}).get('ancestor_refs',[])]
                    for control in controls:
                        bad=any(o is not control and o['page_stem']==stem and math.dist([control['x_mm'],control['y_mm']],[o['x_mm'],o['y_mm']])<.25
                                and math.dist(control.get('model_query_mm',control['coordinate_mm']),o.get('model_query_mm',o['coordinate_mm']))>1 for o in mapped)
                        if bad:continue
                        endpoint=(control['x_mm'],control['y_mm'])
                        for port_index,p in enumerate(ports):
                            if math.dist(p,endpoint)<1 or not axis_covers(page,p,endpoint):continue
                            distance=math.dist(p,endpoint);u=[(endpoint[k]-p[k])/distance for k in (0,1)]
                            if any(h['ref']!=c['ref'] and re.match(r'^(FLANGE|VALVE|TEE|ELBOW|REDUCER|COUPLING|FBLIND|PCOMPONENT)\b',h['name'])
                                   and .5<sum((h[['x_mm','y_mm'][k]]-p[k])*u[k] for k in (0,1))<distance-.5
                                   and abs((h['x_mm']-p[0])*u[1]-(h['y_mm']-p[1])*u[0])<.5 for h in page['hits']):continue
                            matches.append((port_index,{'pipe_ref':pipe['ref'],'pipe_idf_line':pipe['line'],'other_model_mm':other,
                                'control_source_row':control['source_row'],'control_xy_mm':list(endpoint),
                                'ancestor_refs':sorted(set([c['ref'],*control.get('native_topology_evidence',{}).get('ancestor_refs',[])]))}))
                if len({i for i,_ in matches})==1:assignments[index]=matches[0][0];proofs[index]=matches[0][1]
            if len(assignments)==1:
                known=next(iter(assignments));other=1-known;assignments[other]=1-assignments[known]
                proofs[other]={**proofs[known],'inferred_by_two_port_bijection':True,'anchored_model_port_index':known}
            if len(assignments)!=2 or len(set(assignments.values()))!=2:continue
            for target in list(mapped)+list(missing):
                query=target.get('model_query_mm',target['coordinate_mm']);index=min(range(2),key=lambda i:math.dist(query,c['ports'][i]))
                if math.dist(query,c['ports'][index])>.11:continue
                point=ports[assignments[index]];existing=target in mapped
                if existing and target['page_stem']==stem and math.dist(point,[target['x_mm'],target['y_mm']])<=.25:continue
                if any(o is not target and o['page_stem']==stem and math.dist(point,[o['x_mm'],o['y_mm']])<.25 for o in mapped):continue
                previous={k:target.get(k) for k in ('page_stem','x_mm','y_mm','mapping_method','mapping_evidence')}
                proof={'component_ref':c['ref'],'idf_line':c['line'],'model_port_index':index,'model_query_mm':query,
                    'native_body':body,'connection':proofs[index],'ancestor_refs':proofs[index]['ancestor_refs'],
                    'previous':target.get('native_topology_evidence',{}).get('previous',previous),'was_previously_mapped':existing}
                target.update(page_stem=stem,x_mm=point[0],y_mm=point[1],mapping_method='native-fitting-two-port-topology',
                    mapping_evidence=proof,native_topology_evidence=proof,review_notes=[{'reason':'按原图完整元件两端及相邻管线校正；原等轴投影重合导致端口误配，请核对接口。'}])
                if not existing:mapped.append(target);missing.remove(target)
                changes+=1
        if not changes:break
    return mapped,missing
