"""Use a native curved elbow body and its two welded ports, not a fixed ray."""
import math
from pdms_weld_geometry import native_paths,weld_candidates,projection


def equal_leg_elbow_endpoint_candidates(weld,model,pages,candidate_resolver):
    """A finite native elbow leg may end without a separate filled weld glyph.

    Use equal model tangent lengths, a proven other welded port, actual finite
    thick-leg endpoints, and a unique connected local body. No point is placed
    at an assumed offset from HIT.
    """
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code']!=35 or len(c['ports'])!=2 or min(math.dist(q,p) for p in c['ports'])>.11:continue
        center=c['segments'][0]['b'];lengths=[math.dist(p,center) for p in c['ports']]
        if min(lengths)<.1 or abs(lengths[0]-lengths[1])>.005*max(lengths):continue
        index=min(range(2),key=lambda i:math.dist(q,c['ports'][i]));other=c['ports'][1-index]
        controls=candidate_resolver({'coordinate_mm':other},model,pages,allow_pipe=False)
        directions=[projection([p[k]-center[k] for k in range(3)]) for p in c['ports']]
        if any(math.hypot(*d)<.01 for d in directions):continue
        norms=[(d[0]/math.hypot(*d),d[1]/math.hypot(*d)) for d in directions]
        degenerate=sum(norms[0][k]*norms[1][k] for k in (0,1))<-.98
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==c['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm'])
            known={(round(t['x_mm'],3),round(t['y_mm'],3)):t for t in controls if t['page_stem']==stem
                   and any(math.dist((t['x_mm'],t['y_mm']),(d['x_mm'],d['y_mm']))<.15 for d in page['dots'])}
            if len(known)!=1:continue
            start=next(iter(known));radius=math.dist(start,root)
            if not 3<radius<30:continue
            d=[start[k]-root[k] for k in (0,1)];u=norms[1-index]
            if sum(d[k]*u[k] for k in (0,1))<=0 or abs(d[0]*u[1]-d[1]*u[0])>.25:continue
            nodes=[];edges=[]
            def node(p):
                for i,v in enumerate(nodes):
                    if math.dist(p,v)<.2:return i
                nodes.append(tuple(p));return len(nodes)-1
            local=[s for s in page['heavy_segments'] if s.get('stroke_count',0)>=3 and math.dist(s['a'],s['b'])>1
                   and max(math.dist(root,s['a']),math.dist(root,s['b']))<radius+.5]
            for s in local:edges.append((node(s['a']),node(s['b']),s['offset'],'axis'))
            curve_offsets=[]
            for path in native_paths(page['data']):
                ps=path['points']
                if len(ps)<16 or ps[0]!=ps[-1] or max(math.dist(root,p) for p in ps)>12 or min(math.dist(root,p) for p in ps)>3.2:continue
                far=max(ps,key=lambda p:math.dist(p,ps[0]));v=[far[k]-ps[0][k] for k in (0,1)];span=math.hypot(*v)
                if span<1 or max(abs((p[0]-ps[0][0])*v[1]-(p[1]-ps[0][1])*v[0])/span for p in ps)<.65:continue
                touched=[i for i,p in enumerate(nodes) if min(math.dist(p,v) for v in ps)<.4]
                if len(touched)!=2:continue
                edges.append((*touched,path['offsets'][0],'curve'));curve_offsets.append(path['offsets'][0])
            initial=[i for i,p in enumerate(nodes) if math.dist(p,start)<.2]
            if len(initial)!=1:continue
            graph={i:set() for i in range(len(nodes))}
            for a,b,_,_ in edges:graph[a].add(b);graph[b].add(a)
            seen=set();pending=[initial[0]]
            while pending:
                v=pending.pop()
                if v in seen:continue
                seen.add(v);pending.extend(graph[v]-seen)
            terminals=[i for i in seen if len(graph[i])==1]
            if len(terminals)!=2 or initial[0] not in terminals or any(len(graph[i])>2 for i in seen):continue
            end=next(i for i in terminals if i!=initial[0]);point=nodes[end]
            if abs(math.dist(root,point)-radius)>.2:continue
            used=[e for e in edges if e[0] in seen and e[1] in seen]
            actual_curves=[o for _,_,o,kind in used if kind=='curve']
            if not actual_curves and not degenerate:continue
            if not actual_curves:
                def on_segment(s):
                    a,b=s['a'],s['b'];v=[b[k]-a[k] for k in (0,1)];n=sum(x*x for x in v);f=sum((root[k]-a[k])*v[k] for k in (0,1))/n if n else -1
                    return 0<f<1 and math.dist(root,[a[k]+f*v[k] for k in (0,1)])<.25
                if not any(on_segment(s) for s in local):continue
            choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-230,
                'evidence':[{'ref':c['ref'],'code':35,'idf_line':c['line'],'score':-130,'cross_error_mm':0,'along_mm':radius,
                    'method':'beihai-equal-elbow-legs-native-finite-end-opposite-proven-weld',
                    'known_other_model_mm':other,'opposite_terminal':known[start],'native_body_nodes':[nodes[i] for i in sorted(seen)],
                    'native_axis_offsets':[o for _,_,o,kind in used if kind=='axis'],'native_curve_offsets':actual_curves,
                    'model_tangent_lengths_mm':lengths,'projected_straight_body':not bool(actual_curves)}]})
    unique={(t['page_stem'],round(t['x_mm'],3),round(t['y_mm'],3)):t for t in choices}
    return list(unique.values()) if len(unique)==1 else []


def extended_leg_elbow_candidates(weld,model,pages,_unordered=False):
    """Two native welded legs can be much longer than the usual 25mm cap.

    Identify both ports from the same real curved body. Both model directions
    must select different native legs, each ending at its first weld glyph.
    """
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code']!=35 or len(c['ports'])!=2 or min(math.dist(q,p) for p in c['ports'])>.11:continue
        center=c['segments'][0]['b']
        directions=[projection([p[k]-center[k] for k in range(3)]) for p in c['ports']]
        if not _unordered:
            if any(math.hypot(*d)<.01 for d in directions):continue
            directions=[(d[0]/math.hypot(*d),d[1]/math.hypot(*d)) for d in directions]
            if abs(directions[0][0]*directions[1][1]-directions[0][1]*directions[1][0])<.3:continue
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==c['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm'])
            for path in native_paths(page['data']):
                ps=path['points']
                if len(ps)<16 or ps[0]!=ps[-1] or min(math.dist(p,root) for p in ps)>3.2 or max(math.dist(p,root) for p in ps)>12:continue
                far=max(ps,key=lambda p:math.dist(p,ps[0]));v=[far[k]-ps[0][k] for k in (0,1)];length=math.hypot(*v)
                if length<1 or max(abs((p[0]-ps[0][0])*v[1]-(p[1]-ps[0][1])*v[0])/length for p in ps)<.65:continue
                if sum(math.dist(a,b) for a,b in zip(ps,ps[1:]))<2.5*length:continue
                ports={}
                for segment in page['heavy_segments']:
                    for near,far in ((segment['a'],segment['b']),(segment['b'],segment['a'])):
                        distance=math.dist(near,far)
                        if not 1<distance<100 or min(math.dist(near,p) for p in ps)>.4:continue
                        dots=[d for d in page['dots'] if math.dist(far,[d['x_mm'],d['y_mm']])<.35]
                        if not dots:continue
                        direction=[(far[k]-near[k])/distance for k in (0,1)]
                        blocked=False
                        for d in page['dots']:
                            delta=[d['x_mm']-near[0],d['y_mm']-near[1]]
                            along=sum(delta[k]*direction[k] for k in (0,1))
                            if .5<along<distance-.5 and abs(delta[0]*direction[1]-delta[1]*direction[0])<.25:blocked=True
                        for hit in page['hits']:
                            if hit['ref']==c['ref']:continue
                            delta=[hit['x_mm']-near[0],hit['y_mm']-near[1]];along=sum(delta[k]*direction[k] for k in (0,1))
                            if .5<along<distance-.5 and abs(delta[0]*direction[1]-delta[1]*direction[0])<.5:blocked=True
                        if not blocked:ports[tuple(far)]=(segment,dots[0])
                if len(ports)!=2:continue
                selected=list(ports) if _unordered else []
                if not _unordered:
                    for d in directions:
                        matching=[p for p in ports if (p[0]-root[0])*d[0]+(p[1]-root[1])*d[1]>1
                                  and abs((p[0]-root[0])*d[1]-(p[1]-root[1])*d[0])<.4]
                        if len(matching)!=1:break
                        selected.append(matching[0])
                if len(selected)!=2 or selected[0]==selected[1]:continue
                index=min(range(2),key=lambda i:math.dist(q,c['ports'][i]));point=selected[index];segment,dot=ports[point]
                choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-210,
                    'evidence':[{'ref':c['ref'],'code':35,'idf_line':c['line'],'score':-110,'cross_error_mm':0,
                        'along_mm':math.dist(point,root),'method':'beihai-extended-elbow-two-first-native-welded-legs',
                        'curve_offset':path['offsets'][0],'leg_offset':segment['offset'],'dot_offset':dot['offset'],
                        'native_ports':selected,'model_port_directions':directions}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def curved_elbow_candidates(weld,model,pages,_shallow=False):
    query=weld['coordinate_mm'];choices=[]
    for component in model['components']:
        if component['code']!=35 or len(component['ports'])!=2:continue
        a,b=component['ports']
        if min(math.dist(query,a),math.dist(query,b))>.11:continue
        other=b if math.dist(query,a)<.11 else a
        anchors=weld_candidates({'coordinate_mm':other},model,pages)
        for stem,page in pages.items():
            hit=next((h for h in page['hits'] if h['ref']==component['ref']),None)
            if not hit:continue
            root=(hit['x_mm'],hit['y_mm'])
            dots=[d for d in page['dots'] if 1<math.dist(root,(d['x_mm'],d['y_mm']))<30]
            # A sheet boundary may have a verified open port instead of a weld
            # glyph. Accept it only as the independently anchored OTHER port;
            # the requested port still needs its own native welded symbol.
            controls=[{'x_mm':a['x_mm'],'y_mm':a['y_mm'],'offset':None,'control_only':True}
                      for a in anchors if a['page_stem']==stem]
            for path in native_paths(page['data']):
                points=path['points']
                # Shallow arcs use only 18 vertices; their nominal HIT corner
                # can sit just over 3mm from the actual curved body. Keep the
                # closed/repeated stroke, two-port and independent-anchor tests.
                if len(points)<(16 if _shallow else 20) or points[0]!=points[-1]:continue
                if min(math.dist(p,root) for p in points)>(3.2 if _shallow else 2) or max(math.dist(p,root) for p in points)>12:continue
                diagonal=math.hypot(max(p[0] for p in points)-min(p[0] for p in points),max(p[1] for p in points)-min(p[1] for p in points))
                travel=sum(math.dist(p,q) for p,q in zip(points,points[1:]))
                if diagonal<1 or travel<2.5*diagonal:continue
                ports={}
                for segment in page['heavy_segments']:
                    if not 1<math.dist(segment['a'],segment['b'])<25:continue
                    for near,far in ((segment['a'],segment['b']),(segment['b'],segment['a'])):
                        if min(math.dist(near,p) for p in points)>.4:continue
                        for dot in controls+dots:
                            point=(dot['x_mm'],dot['y_mm'])
                            if math.dist(far,point)<.35:ports[point]=(dot,segment)
                if len(ports)!=2:continue
                known=[p for p in ports if any(c['page_stem']==stem and math.dist(p,(c['x_mm'],c['y_mm']))<.35 for c in anchors)]
                if len(known)!=1:continue
                point=next(p for p in ports if p!=known[0]);dot,segment=ports[point]
                if dot.get('control_only'):continue
                choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-210,
                    'evidence':[{'ref':component['ref'],'code':35,'idf_line':component['line'],'score':-110,
                        'cross_error_mm':0,'along_mm':math.dist(root,point),'method':'beihai-curved-elbow-two-native-welded-ports',
                        'curve_offset':path['offsets'][0],'leg_offset':segment['offset'],'dot_offset':dot['offset'],
                        'native_ports':list(ports),'known_other_port':known[0],'known_other_model_mm':other}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    if not unique and not _shallow:
        return curved_elbow_candidates(weld,model,pages,_shallow=True)
    return list(unique.values()) if len(unique)==1 else []


def boundary_elbow_candidates(weld,model,pages,candidate_resolver):
    """A split at an elbow port may omit the usual filled weld glyph.

    Require a real open leg, a closed native elbow body and its independently
    located other port. The model must additionally prove an IDF120 free port
    or an adjacent pipe whose unique opposite control is on another sheet.
    """
    q=weld['coordinate_mm'];choices=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    physical=[c for c in near if c['code']!=120]
    for component in (c for c in near if c['code']==35):
        free=len(physical)==1 and any(c['code']==120 for c in near)
        boundary_controls=[]
        for pipe in (c for c in near if c['code'] in (100,101) and len(c['ports'])==2):
            a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
            controls=candidate_resolver({'coordinate_mm':other},model,pages,allow_pipe=False,allow_elbow=False)
            locations={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)) for c in controls}
            if len(locations)==1:
                boundary_controls.append({'pipe_ref':pipe['ref'],'idf_line':pipe['line'],'control':controls[0]})
        for stem,page in pages.items():
            hit=next((h for h in page['hits'] if h['ref']==component['ref']),None)
            remote=[c for c in boundary_controls if c['control']['page_stem']!=stem]
            flange_controls=[{'ref':f['ref'],'idf_line':f['line'],'hit':h} for f in near if f['code']==105
                             for h in page['hits'] if h['ref']==f['ref']]
            if not hit or not (free or remote or flange_controls):continue
            root=(hit['x_mm'],hit['y_mm']);bodies=[]
            for path in native_paths(page['data']):
                ps=path['points']
                if len(ps)<16 or ps[0]!=ps[-1]:continue
                if min(math.dist(p,root) for p in ps)>3.2 or max(math.dist(p,root) for p in ps)>12:continue
                diagonal=math.hypot(max(p[0] for p in ps)-min(p[0] for p in ps),max(p[1] for p in ps)-min(p[1] for p in ps))
                far=max(ps,key=lambda p:math.dist(p,ps[0]));v=[far[k]-ps[0][k] for k in (0,1)];length=math.hypot(*v)
                curved=length>0 and max(abs((p[0]-ps[0][0])*v[1]-(p[1]-ps[0][1])*v[0])/length for p in ps)>.65
                if curved and diagonal>1 and sum(math.dist(a,b) for a,b in zip(ps,ps[1:]))>2.5*diagonal:bodies.append(path)
            if not bodies:continue
            extra=[];left,bottom,right,top=page['data']['drawing_bounds_mm']
            for axis in page['heavy_segments']:
                for point in (axis['a'],axis['b']):
                    if not left<point[0]<right or not bottom<point[1]<top:continue
                    if not 1<math.dist(root,point)<30:continue
                    if not free and not remote and not any(math.dist(point,(f['hit']['x_mm'],f['hit']['y_mm']))<6 for f in flange_controls):continue
                    if min(math.dist(point,p) for body in bodies for p in body['points'])<.8:continue
                    degree=sum(min(math.dist(point,s['a']),math.dist(point,s['b']))<.25 for s in page['heavy_segments'])
                    if degree!=1:continue
                    if any(h['ref']!=component['ref'] and math.dist(point,(h['x_mm'],h['y_mm']))<.8 for h in page['hits']):continue
                    extra.append({'x_mm':point[0],'y_mm':point[1],'offset':axis['offset'],
                                  'method':'native-open-elbow-port-boundary'})
            if not extra:continue
            modified={**pages,stem:dict(page,dots=[*page['dots'],*extra])}
            found=curved_elbow_candidates(weld,model,modified)
            for candidate in found:
                if candidate['page_stem']!=stem or candidate['evidence'][0]['ref']!=component['ref']:continue
                end=next((d for d in extra if math.dist((d['x_mm'],d['y_mm']),(candidate['x_mm'],candidate['y_mm']))<.15),None)
                if end is None:continue
                proof=candidate['evidence'][0]
                proof['method']='beihai-boundary-elbow-native-open-port'
                proof['native_open_port_axis_offset']=proof.pop('dot_offset')
                proof['boundary_context']={'explicit_120_lines':[c['line'] for c in near if c['code']==120],
                                           'other_sheet_pipe_controls':remote,'adjacent_flange_controls':flange_controls}
                choices.append(candidate)
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []
