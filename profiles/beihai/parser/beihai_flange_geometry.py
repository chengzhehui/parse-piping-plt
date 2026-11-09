"""Locate a flange weld on a real pipe endpoint using its other known port."""
import math
import re
from pdms_weld_geometry import weld_candidates
from beihai_elbow_geometry import curved_elbow_candidates
from pdms_weld_geometry import projection


def fabricated_pipe_slip_on_candidates(weld,model,pages,axis_covers):
    """Use the two real pipe ends between uniquely identified slip-on flanges."""
    q=weld['coordinate_mm'];choices=[]
    for pipe in model['components']:
        if pipe['code'] not in (100,101) or pipe.get('skey')!='FPFL' or len(pipe['ports'])!=2:continue
        if min(math.dist(q,p) for p in pipe['ports'])>.11:continue
        flanges=[]
        for port in pipe['ports']:
            connected=[c for c in model['components'] if c['code']==105 and c.get('skey')=='FLSO'
                       and any(math.dist(port,p)<.11 for p in c['ports'])]
            if len(connected)!=1:break
            flanges.append(connected[0])
        if len(flanges)!=2 or flanges[0]['ref']==flanges[1]['ref']:continue
        delta=projection([pipe['ports'][1][k]-pipe['ports'][0][k] for k in range(3)]);projected=math.hypot(*delta)
        if projected<.01:continue
        for stem,page in pages.items():
            hits=[[h for h in page['hits'] if h['ref']==f['ref']] for f in flanges]
            if any(len(h)!=1 for h in hits):continue
            roots=[(h[0]['x_mm'],h[0]['y_mm']) for h in hits];span=math.dist(*roots)
            if span<5:continue
            u=[(roots[1][k]-roots[0][k])/span for k in (0,1)]
            if sum(u[k]*delta[k] for k in (0,1))/projected<.99:continue
            ends=[]
            for index,root in enumerate(roots):
                local={}
                for axis in page['heavy_segments']:
                    if axis.get('stroke_count',0)<3 or math.dist(axis['a'],axis['b'])<3:continue
                    for end,far in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                        d=[end[k]-root[k] for k in (0,1)];along=sum(d[k]*u[k] for k in (0,1))*(1 if index==0 else -1)
                        if not .05<along<2.5 or math.dist(end,root)>2.5 or abs(d[0]*u[1]-d[1]*u[0])>.25:continue
                        forward=sum((far[k]-end[k])*u[k] for k in (0,1))*(1 if index==0 else -1)
                        if forward<=1 or abs((far[0]-end[0])*u[1]-(far[1]-end[1])*u[0])>.25:continue
                        local[tuple(end)]=axis['offset']
                if len(local)!=1:break
                ends.append((next(iter(local)),next(iter(local.values()))))
            if len(ends)!=2:continue
            bridges=[]
            if not axis_covers(page,ends[0][0],ends[1][0],bridges):continue
            blocked=False
            for h in page['hits']:
                if h['ref'] in {f['ref'] for f in flanges}:continue
                if not re.match(r'^(BEND|ELBOW|TEE|VALVE|FLANGE|REDUCER|COUPLING|PCOMPONENT|OLET|FBLIND)\b',h['name']):continue
                d=[h['x_mm']-roots[0][0],h['y_mm']-roots[0][1]];along=sum(d[k]*u[k] for k in (0,1))
                if .5<along<span-.5 and abs(d[0]*u[1]-d[1]*u[0])<.5:blocked=True
            if blocked:continue
            index=min(range(2),key=lambda i:math.dist(q,pipe['ports'][i]));point=ends[index][0]
            choices.append({'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-235,
                'evidence':[{'ref':flanges[index]['ref'],'code':105,'idf_line':flanges[index]['line'],'score':-135,
                    'cross_error_mm':0,'along_mm':math.dist(point,roots[index]),
                    'method':'beihai-FPFL-slip-on-flanges-native-pipe-ends','pipe_ref':pipe['ref'],'pipe_idf_line':pipe['line'],
                    'flange_refs':[f['ref'] for f in flanges],'flange_hits_mm':roots,'native_pipe_ends':[e[0] for e in ends],
                    'native_axis_offsets':[e[1] for e in ends],'native_axis_bridges':bridges}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def flange_pipe_candidates(weld,model,pages,candidate_resolver):
    q=weld['coordinate_mm'];choices=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    for flange in (c for c in near if c['code']==105):
        for pipe in (c for c in near if c['code'] in (100,101) and len(c['ports'])==2):
            a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
            controls=candidate_resolver({'coordinate_mm':other},model,pages,allow_pipe=False,allow_elbow=False)
            controls+=weld_candidates({'coordinate_mm':other},model,pages)
            controls+=curved_elbow_candidates({'coordinate_mm':other},model,pages)
            for stem,page in pages.items():
                hit=next((h for h in page['hits'] if h['ref']==flange['ref']),None)
                if not hit:continue
                root=(hit['x_mm'],hit['y_mm'])
                for axis in page['heavy_segments']:
                    if axis.get('stroke_count',0)<3:continue
                    for end,far in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                        length=math.dist(end,far)
                        if length<3 or math.dist(root,end)>6:continue
                        u=[(far[k]-end[k])/length for k in (0,1)]
                        for control in controls:
                            if control['page_stem']!=stem:continue
                            v=[control['x_mm']-end[0],control['y_mm']-end[1]]
                            along=sum(v[k]*u[k] for k in (0,1));cross=abs(v[0]*u[1]-v[1]*u[0])
                            if not 1<along<length+.3 or cross>.25:continue
                            choices.append({'page_stem':stem,'x_mm':end[0],'y_mm':end[1],'score':-220,
                                'evidence':[{'ref':flange['ref'],'code':105,'idf_line':flange['line'],'score':-120,
                                    'along_mm':math.dist(root,end),'cross_error_mm':cross,
                                    'method':'beihai-flange-weld-native-pipe-end-independent-control',
                                    'pipe_ref':pipe['ref'],'pipe_idf_line':pipe['line'],
                                    'known_other_model_mm':other,'opposite_terminal':control,'axis_offset':axis['offset']}]})
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def flange_continuous_axis_candidates(weld,model,pages,candidate_resolver,axis_covers,chain_anchors):
    """Follow a real pipe axis across a verified FLOW gap or support split."""
    q=weld['coordinate_mm'];choices=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    for flange in (c for c in near if c['code']==105):
        for pipe in (c for c in near if c['code'] in (100,101) and len(c['ports'])==2):
            a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
            controls=candidate_resolver({'coordinate_mm':other},model,pages,allow_pipe=False,allow_elbow=False)
            controls+=weld_candidates({'coordinate_mm':other},model,pages)
            controls+=curved_elbow_candidates({'coordinate_mm':other},model,pages)
            if not controls:controls=chain_anchors(q,other,pipe,model,pages)
            for stem,page in pages.items():
                hits=[h for h in page['hits'] if h['ref']==flange['ref']]
                if len(hits)!=1:continue
                root=(hits[0]['x_mm'],hits[0]['y_mm'])
                for axis in page['heavy_segments']:
                    if axis.get('stroke_count',0)<3:continue
                    for end,far in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                        length=math.dist(end,far)
                        if length<3 or math.dist(root,end)>6:continue
                        u=[(far[k]-end[k])/length for k in (0,1)]
                        for control in controls:
                            if control['page_stem']!=stem:continue
                            point=(control['x_mm'],control['y_mm']);v=[point[k]-end[k] for k in (0,1)]
                            along=sum(v[k]*u[k] for k in (0,1));cross=abs(v[0]*u[1]-v[1]*u[0]);breaks=[]
                            if along<=1 or cross>.25 or not axis_covers(page,end,point,breaks):continue
                            blocked=False
                            for hit in page['hits']:
                                if hit['ref']==flange['ref'] or not re.match(r'^(FLANGE|VALVE|TEE|ELBOW|REDUCER|COUPLING|FBLIND|PCOMPONENT)\b',hit['name']):continue
                                delta=[hit['x_mm']-end[0],hit['y_mm']-end[1]];distance=sum(delta[k]*u[k] for k in (0,1))
                                if .5<distance<along-.5 and abs(delta[0]*u[1]-delta[1]*u[0])<.5:blocked=True
                            if blocked:continue
                            choices.append({'page_stem':stem,'x_mm':end[0],'y_mm':end[1],'score':-220,
                                'evidence':[{'ref':flange['ref'],'code':105,'idf_line':flange['line'],'score':-120,
                                    'along_mm':math.dist(root,end),'cross_error_mm':cross,'method':'beihai-flange-continuous-native-axis-independent-control',
                                    'pipe_ref':pipe['ref'],'pipe_idf_line':pipe['line'],'opposite_terminal':control,
                                    'axis_offset':axis['offset'],'native_axis_breaks':breaks}]})
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def flange_valve_interface_candidates(weld,model,pages):
    """Use a connected valve and actual flange face to order a skew pipe end."""
    q=weld['coordinate_mm'];choices=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    if not any(c['code'] in (100,101) for c in near):return []
    for flange in (c for c in near if c['code']==105 and c.get('skey') in ('FLWN','FLSW')):
        other=max(flange['ports'],key=lambda p:math.dist(q,p));frontier=[other];seen=set();valves=[]
        while frontier:
            point=frontier.pop()
            for c in model['components']:
                if c['line'] in seen or c is flange or not any(math.dist(point,p)<.11 for p in c['ports']):continue
                seen.add(c['line'])
                if c['code'] in (90,130):valves.append(c)
                elif c['code']==110:frontier.extend(p for p in c['ports'] if math.dist(point,p)>.11)
        for valve in valves:
            for stem,page in pages.items():
                fh=[h for h in page['hits'] if h['ref']==flange['ref']];vh=[h for h in page['hits'] if h['ref']==valve['ref']]
                if len(fh)!=1 or len(vh)!=1:continue
                root=(fh[0]['x_mm'],fh[0]['y_mm']);vroot=(vh[0]['x_mm'],vh[0]['y_mm'])
                bodies=[b for b in page['valve_bodies'] if min(math.dist(vroot,b['a']),math.dist(vroot,b['b']),math.dist(vroot,b['center']))<1.6]
                if len(bodies)!=1:continue
                body=bodies[0];a=min((body['a'],body['b']),key=lambda p:math.dist(root,p));b=max((body['a'],body['b']),key=lambda p:math.dist(root,p))
                span=math.dist(a,b);u=[(b[k]-a[k])/span for k in (0,1)]
                if abs((root[0]-a[0])*u[1]-(root[1]-a[1])*u[0])>.25:continue
                plates=[o for o in page['port_outlines'] if .4<math.dist(*o['ports'])<2
                        and min(math.dist(p,root) for p in o['ports'])<3 and min(math.dist(p,a) for p in o['ports'])<2]
                if len(plates)!=1:continue
                for axis in page['heavy_segments']:
                    if axis.get('stroke_count',0)<3 or math.dist(axis['a'],axis['b'])<3:continue
                    for end,far in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                        if math.dist(end,root)>6:continue
                        delta=[end[k]-a[k] for k in (0,1)];along=sum(delta[k]*u[k] for k in (0,1))
                        if along>=-1 or abs(delta[0]*u[1]-delta[1]*u[0])>.25:continue
                        if sum((far[k]-end[k])*u[k] for k in (0,1))>=-1:continue
                        if not along<sum((root[k]-a[k])*u[k] for k in (0,1))<0:continue
                        choices.append({'page_stem':stem,'x_mm':end[0],'y_mm':end[1],'score':-230,
                            'evidence':[{'ref':flange['ref'],'code':105,'idf_line':flange['line'],'score':-130,
                                'cross_error_mm':0,'along_mm':math.dist(root,end),'method':'beihai-flange-actual-pipe-end-plate-and-connected-valve',
                                'valve_ref':valve['ref'],'valve_idf_line':valve['line'],'valve_native_body':body,
                                'flange_native_plate':plates[0],'axis_offset':axis['offset']}]})
    unique={(c['page_stem'],round(c['x_mm'],3),round(c['y_mm'],3)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []
