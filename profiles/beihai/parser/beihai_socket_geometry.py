"""Socket mouths and short fitting interfaces proven by native outlines."""
import math


def socket_outline_candidates(weld,model,pages,candidate_resolver,axis_covers,chain_anchors,boundary_distance):
    q=weld['coordinate_mm'];choices=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    physical=[c for c in near if c['code'] not in (110,115,120,150)]
    for fitting in (c for c in near if c['code'] in (95,126) and len(c['ports'])==2):
        for stem,page in pages.items():
            hits=[h for h in page['hits'] if h['ref']==fitting['ref']]
            if len(hits)!=1:continue
            root=(hits[0]['x_mm'],hits[0]['y_mm'])
            if fitting['code']==95 and fitting['skey']=='CHSW' and len(physical)==1 and any(c['code']==120 for c in near):
                if math.dist(q,fitting['ports'][0])>.11:continue
                sockets=[d for d in page['dots'] if d['method']=='native-socket-outline-and-hatch']
                if not any(math.dist(root,(d['x_mm'],d['y_mm']))<.15 for d in sockets):continue
                for dot in sockets:
                    point=(dot['x_mm'],dot['y_mm']);length=math.dist(root,point)
                    if not 2.1<length<2.7:continue
                    u=[(point[k]-root[k])/length for k in (0,1)];matched=[]
                    for mouth,sign in ((root,-1),(point,1)):
                        for outline in page['port_outlines']:
                            ends=outline['ports'];close=min(ends,key=lambda p:math.dist(p,mouth));far=max(ends,key=lambda p:math.dist(p,mouth))
                            delta=[far[k]-mouth[k] for k in (0,1)]
                            if math.dist(close,mouth)<.15 and sum(delta[k]*u[k] for k in (0,1))*sign>1 and abs(delta[0]*u[1]-delta[1]*u[0])<.2:
                                matched.append(outline);break
                    if len(matched)!=2:continue
                    choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-230,
                        'evidence':[{'ref':fitting['ref'],'code':95,'idf_line':fitting['line'],'score':-130,'cross_error_mm':0,
                            'along_mm':length,'method':'beihai-CHSW-two-opposed-native-socket-mouths-free-port',
                            'known_other_native_port':root,'socket_dot_offset':dot['offset'],'native_socket_outlines':matched}]})
            if fitting['code']!=126 or fitting['skey']!='NRSC':continue
            if math.dist(q,fitting['ports'][1])<.11:
                a,b=fitting['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v);returning=[]
                for pipe in (c for c in near if c['code'] in (100,101) and len(c['ports'])==2):
                    other=max(pipe['ports'],key=lambda p:math.dist(q,p))
                    fraction=sum((other[k]-a[k])*v[k] for k in range(3))/n if n else -1
                    if 0<fraction<1 and math.dist(other,[a[k]+fraction*v[k] for k in range(3)])<.11:returning.append(pipe['ref'])
                if returning:
                    controls=candidate_resolver({'coordinate_mm':a},model,pages,allow_pipe=False)
                    for outline in page['port_outlines']:
                        if not 3<math.dist(*outline['ports'])<6 or boundary_distance(root,outline['polygon'])>.8:continue
                        known={i for i,port in enumerate(outline['ports']) for control in controls
                               if control['page_stem']==stem and math.dist(port,(control['x_mm'],control['y_mm']))<1.4
                               and any(math.dist((control['x_mm'],control['y_mm']),(d['x_mm'],d['y_mm']))<.15 for d in page['dots'])}
                        if len(known)!=1:continue
                        point=outline['ports'][1-next(iter(known))]
                        choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-230,
                            'evidence':[{'ref':fitting['ref'],'code':126,'idf_line':fitting['line'],'score':-130,'cross_error_mm':0,
                                'along_mm':math.dist(root,point),'method':'beihai-NRSC-native-body-end-opposite-proven-socket-returning-stub',
                                'native_outline':outline,'returning_pipe_refs':returning,'opposite_port_candidates':controls}]})
            for pipe in (c for c in near if c['code'] in (100,101) and len(c['ports'])==2):
                a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
                controls=candidate_resolver({'coordinate_mm':other},model,pages,allow_pipe=False)
                if not controls:controls=chain_anchors(q,other,pipe,model,pages)
                for outline in page['port_outlines']:
                    if not 3<math.dist(*outline['ports'])<6 or boundary_distance(root,outline['polygon'])>.8:continue
                    for axis in page['heavy_segments']:
                        if axis.get('stroke_count',0)<3 or math.dist(axis['a'],axis['b'])<3:continue
                        for point,far in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                            if min(math.dist(point,p) for p in outline['ports'])>1.4:continue
                            for control in controls:
                                if control['page_stem']!=stem:continue
                                end=(control['x_mm'],control['y_mm'])
                                if math.dist(point,end)<2 or not axis_covers(page,point,end):continue
                                u=[far[k]-point[k] for k in (0,1)];v=[end[k]-point[k] for k in (0,1)]
                                if sum(u[k]*v[k] for k in (0,1))<=0:continue
                                choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-230,
                                    'evidence':[{'ref':fitting['ref'],'code':126,'idf_line':fitting['line'],'score':-130,'cross_error_mm':0,
                                        'along_mm':math.dist(root,point),'method':'beihai-NRSC-outline-adjacent-pipe-end-independent-control',
                                        'native_outline':outline,'axis_offset':axis['offset'],'opposite_terminal':control,'pipe_ref':pipe['ref']}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []
