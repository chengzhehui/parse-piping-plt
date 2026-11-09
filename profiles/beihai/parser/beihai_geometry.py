"""Beihai PDMS origin records and native page geometry (no business IDs inferred)."""
import math
import re
from audit_pdms_export import model_components
from analyze_plt_bundle import decode_plt,read_hit
from pdms_weld_geometry import (component_port_outlines,native_weld_dots,
                                heavy_straight_segments,projection,weld_candidates,native_paths)
from beihai_valve_geometry import native_valve_bodies,valve_body_center
from beihai_elbow_geometry import curved_elbow_candidates,boundary_elbow_candidates,extended_leg_elbow_candidates,equal_leg_elbow_endpoint_candidates
from beihai_flange_geometry import flange_pipe_candidates,flange_continuous_axis_candidates,flange_valve_interface_candidates,fabricated_pipe_slip_on_candidates
from beihai_tee_geometry import extended_tee_candidates,skew_tee_branch_candidates,zero_run_olet_body_candidates,tee_third_finite_arm_candidates
from beihai_socket_geometry import socket_outline_candidates
from beihai_singleton_geometry import singleton_pipe_candidates


def filled_polygon_welds(data):
    """PD60 butt glyph: six-sided closed outline plus independent scan lines.

    Require at least four horizontal fill strokes inside the outline. A mere
    polygon/nearby text vertex is not a weld. Centres come from the polygon,
    rather than from the end of the pipe's oscillating pen strokes.
    """
    result=[];paths=native_paths(data)
    left,bottom,right,top=data['drawing_bounds_mm']
    for i,path in enumerate(paths):
        pts=path['points'][:7]
        if len(pts)!=7 or pts[0]!=pts[-1] or len(set(pts))!=6:continue
        xs=[p[0] for p in pts[:-1]];ys=[p[1] for p in pts[:-1]]
        x0,x1=min(xs),max(xs);y0,y1=min(ys),max(ys)
        if not (.4<x1-x0<3.5 and .4<y1-y0<3.5):continue
        x,y=(x0+x1)/2,(y0+y1)/2
        if not (left<x<right and bottom<y<top):continue
        fills=[]
        for other in paths[i+1:i+24]:
            p=other['points']
            if len(p)==2 and abs(p[0][1]-p[1][1])<.01 and math.dist(*p)>.15 and all(x0-.02<=a<=x1+.02 and y0-.02<=b<=y1+.02 for a,b in p):
                fills.append(other['offsets'][0])
        if len(fills)<4:continue
        result.append({'x_mm':round(x,3),'y_mm':round(y,3),'offset':path['offsets'][0],
                       'glyph_points':pts,'fill_offsets':fills,'method':'native-six-sided-outline-and-independent-fill'})
    return result


def flow_arrow_axes(data):
    """Recognise the repeated triangular fill of FLOW, which interrupts a pipe.

    Native PD60 paths return to their base centre at point 25 and to the tip
    at point 26, then resume pipe strokes. This bridges only that symbol,
    never an arbitrary gap between collinear strokes.
    """
    result=[]
    for path in native_paths(data):
        pts=path['points']
        if len(pts)<27:continue
        a,b=pts[0],pts[2];length=math.dist(a,b)
        if not 6.1<length<6.8 or math.dist(a,pts[25])>.15 or math.dist(b,pts[26])>.15:continue
        u=((b[0]-a[0])/length,(b[1]-a[1])/length)
        side=[(p[0]-a[0])*u[1]-(p[1]-a[1])*u[0] for p in (pts[1],pts[3])]
        if not (side[0]*side[1]<-.7 and max(map(abs,side))<1.8):continue
        result.append({'a':a,'b':b,'offset':path['offsets'][0],'method':'native-FLOW-triangular-fill-gap'})
    return result


def load_model(path,coordinate_offset_mm=None):
    data,components=model_components(path)
    origins=[tuple(float(x)*1000 for x in re.findall(r'[+-]?\d+',r['text'])[:3])
             for r in data['logical_records'] if r['code']==300]
    if len(set(origins))!=1:
        raise ValueError('IDF 300 原点记录缺失或不唯一')
    source_origin=origins[0]
    offset=tuple(coordinate_offset_mm or (0,0,0))
    if len(offset)!=3 or not all(math.isfinite(x) for x in offset):
        raise ValueError('IDF坐标转换必须为三个有限数值')
    origin=tuple(source_origin[k]+offset[k] for k in range(3))
    for c in components:
        c['ports']=[tuple(p[k]+origin[k] for k in range(3)) for p in c['ports']]
        for s in c['segments']:
            for key in ('a','b'):
                s[key]=tuple(s[key][k]+origin[k] for k in range(3))
        center=(c['segments'][0]['b'] if c['code'] in (35,40,45)
                else tuple((c['segments'][0]['a'][k]+c['segments'][0]['b'][k])/2 for k in range(3)))
        if c['ref']:
            data['locations'][c['ref']]={'xyz_mm':center}
    return {'data':data,'components':components,'z_offset_mm':0,'origin_mm':origin,
            'idf_origin_mm':source_origin,'coordinate_offset_mm':offset}


def load_page(path,hit_path=None):
    data=decode_plt(path)
    if abs(data['width_mm']-594.2)>.2 or abs(data['height_mm']-420.2)>.2:
        raise ValueError('北海当前配置仅验证 A2 横向图幅')
    data['drawing_bounds_mm']=(27,27,402,409)
    outlines,vertices=component_port_outlines(data)
    return {'data':data,'hits':read_hit(hit_path if hit_path is not None else path.with_suffix('.hit')),
            'dots':native_weld_dots(data)+filled_polygon_welds(data),'port_outlines':outlines,'vertices':vertices,
            'heavy_segments':heavy_straight_segments(data),'flow_axes':flow_arrow_axes(data),
            'valve_bodies':native_valve_bodies(data),'hit_offset_mm':(0,0)}


def beihai_candidates(weld,model,pages,allow_pipe=True,allow_elbow=True):
    """Prefer actual connected native fitting legs over a fixed symbol length.

    FLWN / FLSW HIT locates IDF terminal B, not the IDF midpoint. Only accept
    terminal A offsets when corroborated by a decoded native vertex/pipe end.
    Unknown conventions fall back to the existing candidate audit inventory.
    """
    q=weld['coordinate_mm']
    strong=[]
    near=[c for c in model['components'] if any(math.dist(q,p)<=1 for p in c['ports'])]
    for c in near:
        for stem,page in pages.items():
            hit=next((h for h in page['hits'] if h['ref']==c['ref']),None)
            if not hit:continue
            root=(hit['x_mm'],hit['y_mm'])
            points=[];method='';confidence='native-geometry'
            if c['code']==105 and c['skey'] in ('FLWN','FLSW'):
                a,b=c['segments'][0]['a'],c['segments'][0]['b']
                if math.dist(q,b)<=1:
                    predicted=root
                else:
                    dx,dy=projection(tuple(a[k]-b[k] for k in range(3)))
                    length=math.hypot(dx,dy)
                    leg=4 if c['skey']=='FLWN' else .8
                    if length<.01:continue
                    predicted=(root[0]+dx/length*leg,root[1]+dy/length*leg)
                pool=([p for s in page['heavy_segments'] for p in (s['a'],s['b'])]
                      if c['skey']=='FLWN' else page['vertices'])
                close=[p for p in pool if math.dist(p,predicted)<.15]
                if close:points=[min(close,key=lambda p:math.dist(p,predicted))]
                method='beihai-flange-terminal-B-HIT-native-port'
            elif c['code'] in (40,45) and c['skey'] in ('TEBW','TESW'):
                center=c['segments'][0]['b']
                dx,dy=projection(tuple(q[k]-center[k] for k in range(3)))
                length=math.hypot(dx,dy)
                if length<.01:continue
                u=(dx/length,dy/length)
                for s in page['heavy_segments']:
                    for a,b in ((s['a'],s['b']),(s['b'],s['a'])):
                        vx,vy=b[0]-root[0],b[1]-root[1]
                        if math.dist(a,root)<.15 and 1<math.hypot(vx,vy)<20 and vx*u[0]+vy*u[1]>0 and abs(vx*u[1]-vy*u[0])<.12:
                            points.append(b)
                method='beihai-tee-connected-native-leg'
            elif c['code']==40 and c['skey']=='NONE':
                if math.dist(q,c['segments'][0]['b'])<1 and any(math.dist(root,p)<.15 for s in page['heavy_segments'] for p in (s['a'],s['b'])):
                    points=[root]
                method='beihai-zero-length-main-run-HIT-junction'
            elif c['code']==40 and c['skey']=='SKSW':
                a,b=c['segments'][0]['a'],c['segments'][0]['b']
                if math.dist(q,a)<1:
                    if any(math.dist(root,p)<.15 for s in page['heavy_segments'] for p in (s['a'],s['b'])):points=[root]
                    method='beihai-olet-branch-terminal-HIT-native-pipe-end'
                elif math.dist(q,b)<1:
                    dx,dy=projection(tuple(b[k]-a[k] for k in range(3)))
                    length=math.hypot(dx,dy)
                    if length>.01:
                        predicted=(root[0]+dx/length*3.9,root[1]+dy/length*3.9)
                        ends=[p for s in page['heavy_segments'] for p in (s['a'],s['b'])]
                        close=[p for p in ends if math.dist(p,predicted)<.15]
                        if close:points=[min(close,key=lambda p:math.dist(p,predicted))]
                    method='beihai-olet-native-main-run-junction'
            elif c['code']==150 and math.dist(q,c['ports'][0])<.11:
                for axis in page['heavy_segments']:
                    a,b=axis['a'],axis['b'];v=(b[0]-a[0],b[1]-a[1]);n=v[0]**2+v[1]**2
                    f=((root[0]-a[0])*v[0]+(root[1]-a[1])*v[1])/n if n else -1
                    if -.01<=f<=1.01 and math.dist(root,(a[0]+f*v[0],a[1]+f*v[1]))<.2:
                        points=[root];break
                method='beihai-support-HIT-native-axis-control-point'
            elif c['code']==130 and c['skey']=='VTSW':
                try:body=valve_body_center(c,hit,page)
                except ValueError:continue
                ports=[body['a'],body['b']]
                if not all(any(math.dist(p,(d['x_mm'],d['y_mm']))<.15 for d in page['dots']) for p in ports):continue
                direction=projection([c['ports'][1][k]-c['ports'][0][k] for k in range(3)])
                downstream=max(ports,key=lambda p:sum(p[k]*direction[k] for k in (0,1)))
                points=[downstream if math.dist(q,c['ports'][1])<.11 else next(p for p in ports if p!=downstream)]
                method='beihai-VTSW-native-socket-body-ports-HIT-terminal-B'
            elif c['code']==95 and c['skey']=='CHSW':
                a,b=c['ports'][0],c['ports'][-1]
                dx,dy=projection([a[k]-b[k] for k in range(3)]);length=math.hypot(dx,dy)
                if length<.01:continue
                u=(dx/length,dy/length)
                for dot in page['dots']:
                    if dot['method']!='native-socket-outline-and-hatch':continue
                    p=(dot['x_mm'],dot['y_mm']);v=(p[0]-root[0],p[1]-root[1])
                    along=v[0]*u[0]+v[1]*u[1];cross=abs(v[0]*u[1]-v[1]*u[0])
                    if (math.dist(q,b)<.11 and math.dist(p,root)<.15) or (math.dist(q,a)<.11 and 2.1<along<2.7 and cross<.15):points.append(p)
                method='beihai-compound-95-96-CHSW-native-socket-terminals'
            elif c['code']==55 and c['skey'] in ('REBW','RCBW'):
                # Eccentric reducers have model offsets that do not coincide
                # with the symbol's port ray. Locate both actual contour ports
                # first, then order them by the model's principal pipe axis.
                attached=set()
                for outline in page['port_outlines']:
                    polygon=outline['polygon']
                    if not 2<math.dist(*outline['ports'])<12:continue
                    if point_boundary_distance(root,polygon)>.2:continue
                    for dot in page['dots']:
                        p=(dot['x_mm'],dot['y_mm'])
                        if point_boundary_distance(p,polygon)<.2:attached.add(p)
                if len(attached)==2:
                    a,b=c['ports'];v=[a[k]-b[k] for k in range(3)];axis=max(range(3),key=lambda k:abs(v[k]))
                    principal=[v[k] if k==axis else 0 for k in range(3)];u=projection(principal)
                    ordered=sorted(attached,key=lambda p:p[0]*u[0]+p[1]*u[1])
                    if math.dist(*ordered)>1:
                        points=[ordered[-1] if math.dist(q,a)<1 else ordered[0]]
                method='beihai-eccentric-reducer-contour-attached-welds'
            elif c['code']==126 and c['skey']=='NRSC':
                a,b=c['ports'];dx,dy=projection([a[k]-b[k] for k in range(3)]);length=math.hypot(dx,dy)
                if math.dist(q,b)<.11:
                    # HIT here is the coordinate-note tip, ~1.15 mm beyond
                    # the actual outline. Never accept a text/leader vertex
                    # as physical proof of the fitting terminal.
                    body_ports=[]
                    for outline in page['port_outlines']:
                        if not 3<math.dist(*outline['ports'])<6:continue
                        port=min(outline['ports'],key=lambda p:math.dist(root,p))
                        opposite=max(outline['ports'],key=lambda p:math.dist(root,p))
                        socket_near=any(d['method']=='native-socket-outline-and-hatch' and math.dist(opposite,(d['x_mm'],d['y_mm']))<1.4 for d in page['dots'])
                        if math.dist(root,port)<1.5 and socket_near:body_ports.append(port)
                    if len(set(body_ports))==1:points=body_ports[:1]
                elif length>.01:
                    u=(dx/length,dy/length)
                    matches=[]
                    for dot in page['dots']:
                        if dot['method']!='native-socket-outline-and-hatch':continue
                        p=(dot['x_mm'],dot['y_mm']);v=(p[0]-root[0],p[1]-root[1]);along=v[0]*u[0]+v[1]*u[1]
                        if 4<along<8 and abs(v[0]*u[1]-v[1]*u[0])<.2:matches.append((along,p))
                    if matches:points=[min(matches)[1]]
                method='beihai-IDF126-NRSC-HIT-terminal-and-native-socket'
            for p in set(points):
                strong.append({'page_stem':stem,'x_mm':p[0],'y_mm':p[1],'score':-250,
                    'evidence':[{'ref':c['ref'],'code':c['code'],'idf_line':c['line'],
                                 'score':-150,'along_mm':math.dist(root,p),'cross_error_mm':0,'method':method}]})
    if strong:
        unique={}
        for item in strong:
            key=(item['page_stem'],round(item['x_mm'],2),round(item['y_mm'],2))
            if key in unique:unique[key]['evidence'].extend(item['evidence'])
            else:unique[key]=item
        return sorted(unique.values(),key=lambda r:-len(r['evidence']))
    basic=weld_candidates(weld,model,pages)
    if basic or not allow_pipe:return basic
    pipe=pipe_endpoint_candidates(weld,model,pages)
    if pipe:return pipe
    explicit=explicit_pipe_weld_candidates(weld,model,pages)
    if explicit:return explicit
    if not allow_elbow:return []
    curved=curved_elbow_candidates(weld,model,pages)
    if curved:return curved
    unlisted=elbow_connected_terminal(weld,model,pages)
    if unlisted:return unlisted
    boundary_elbow=boundary_elbow_candidates(weld,model,pages,beihai_candidates)
    if boundary_elbow:return boundary_elbow
    flange=flange_pipe_candidates(weld,model,pages,beihai_candidates)
    if flange:return flange
    # The same verified open end used for an interior cut's terminal can also
    # be the weld-table point itself. It needs a degree-one model pipe and a
    # unique uninterrupted native axis; no missing glyph is invented.
    boundary=[]
    for component in near:
        if component['code'] not in (100,101) or len(component['ports'])!=2:continue
        a,b=component['ports']
        if min(math.dist(q,a),math.dist(q,b))>.11:continue
        other=b if math.dist(q,a)<.11 else a
        boundary.extend(plain_pipe_terminal(q,other,component,model,pages))
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in boundary}
    if unique:return list(unique.values()) if len(unique)==1 else []
    extended=extended_leg_elbow_candidates(weld,model,pages)
    if extended:return extended
    tee=extended_tee_candidates(weld,model,pages,native_axis_covers,beihai_candidates)
    if tee:return tee
    skew=skew_tee_branch_candidates(weld,model,pages,native_axis_covers,beihai_candidates)
    if skew:return skew
    continuous=flange_continuous_axis_candidates(weld,model,pages,beihai_candidates,native_axis_covers,pipe_chain_anchors)
    if continuous:return continuous
    valve_flange=flange_valve_interface_candidates(weld,model,pages)
    if valve_flange:return valve_flange
    socket=socket_outline_candidates(weld,model,pages,beihai_candidates,native_axis_covers,pipe_chain_anchors,point_boundary_distance)
    if socket:return socket
    single=singleton_pipe_candidates(weld,model,pages,native_axis_covers)
    if single:return single
    olet=zero_run_olet_body_candidates(weld,model,pages,point_boundary_distance)
    if olet:return olet
    equal=equal_leg_elbow_endpoint_candidates(weld,model,pages,beihai_candidates)
    if equal:return equal
    fabricated=fabricated_pipe_slip_on_candidates(weld,model,pages,native_axis_covers)
    if fabricated:return fabricated
    third=tee_third_finite_arm_candidates(weld,model,pages,beihai_candidates)
    if third:return third
    return pipe_endpoint_candidates(weld,model,pages,allow_filled_controls=True) if allow_pipe else []


def point_boundary_distance(point,polygon):
    distances=[]
    for a,b in zip(polygon,polygon[1:]):
        v=(b[0]-a[0],b[1]-a[1]);n=v[0]**2+v[1]**2
        f=max(0,min(1,((point[0]-a[0])*v[0]+(point[1]-a[1])*v[1])/n)) if n else 0
        distances.append(math.dist(point,(a[0]+f*v[0],a[1]+f*v[1])))
    return min(distances,default=float('inf'))


def elbow_connected_terminal(weld,model,pages):
    """Recover an unlisted elbow from the other port and connected thick strokes.

    No fixed leg length is imposed: the printed elbow may have extended legs.
    Only repeated-pen paths are followed, with one uniquely reachable native
    weld glyph; dimension lines and text strokes are excluded by density.
    """
    q=weld['coordinate_mm'];choices=[]
    for c in model['components']:
        if c['code']!=35 or not any(math.dist(q,p)<.11 for p in c['ports']):continue
        if any(h['ref']==c['ref'] for page in pages.values() for h in page['hits']):continue
        a,b=c['ports'];other=b if math.dist(q,a)<.11 else a
        anchors=beihai_candidates({'coordinate_mm':other},model,pages,allow_elbow=False)
        if not anchors:continue
        anchor=anchors[0];stem=anchor['page_stem'];page=pages[stem];root=(anchor['x_mm'],anchor['y_mm'])
        paths=[]
        for path in native_paths(page['data']):
            pts=path['points']
            if len(pts)<10 or max(math.dist(p,root) for p in pts)>35:continue
            diagonal=math.hypot(max(p[0] for p in pts)-min(p[0] for p in pts),max(p[1] for p in pts)-min(p[1] for p in pts))
            travel=sum(math.dist(a,b) for a,b in zip(pts,pts[1:]))
            if diagonal>.5 and travel>3*diagonal:paths.append(path)
        reached={i for i,path in enumerate(paths) if min(math.dist(p,root) for p in path['points'])<.45}
        progress=True
        while progress:
            progress=False
            for i,path in enumerate(paths):
                if i in reached:continue
                if any(any(math.dist(p,t)<.45 for p in path['points'] for t in paths[j]['points']) for j in reached):
                    reached.add(i);progress=True
        points=[p for i in reached for p in paths[i]['points']]
        if not points:continue
        dots={(round(d['x_mm'],2),round(d['y_mm'],2)):d for d in page['dots'] if math.dist((d['x_mm'],d['y_mm']),root)>1 and min(math.dist(p,(d['x_mm'],d['y_mm'])) for p in points)<.45}
        if len(dots)!=1:continue
        p,dot=next(iter(dots.items()))
        choices.append({'page_stem':stem,'x_mm':p[0],'y_mm':p[1],'score':-180,
            'evidence':[{'ref':c['ref'],'code':35,'idf_line':c['line'],'score':-90,'cross_error_mm':0,
                'along_mm':math.dist(p,root),'method':'beihai-unlisted-elbow-connected-thick-paths',
                'opposite_terminal':anchor,'path_offsets':[paths[i]['offsets'][0] for i in sorted(reached)],'dot_offset':dot['offset']}]})
    return choices if len(choices)==1 else []


def pipe_endpoint_candidates(weld,model,pages,allow_filled_controls=False):
    """A degree-one pipe terminal can be traced from its anchored opposite end.

    Require the next native weld glyph on the projected ray and continuous
    thick pipe/FLOW geometry. Suppress overlapping-model-pipe cases rather
    than assuming that an old unplotted flange is present in the drawing.
    """
    q=weld['coordinate_mm'];near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    if not near or not any(c['code'] in (100,101) for c in near):return []
    choices=[]
    for comp in near:
        if comp['code'] not in (100,101) or len(comp['ports'])!=2:continue
        a,b=comp['ports'];other=b if math.dist(q,a)<.11 else a
        # A table point inside a second IDF pipe is not a free terminal.
        overlapping=False
        for c in model['components']:
            if c is comp or c['code'] not in (100,101) or len(c['ports'])!=2:continue
            x,y=c['ports'];v=[y[k]-x[k] for k in range(3)];n=sum(t*t for t in v)
            f=sum((q[k]-x[k])*v[k] for k in range(3))/n if n else -1
            if .00001<f<.99999 and math.dist(q,[x[k]+f*v[k] for k in range(3)])<.11:overlapping=True
        if overlapping:continue
        anchors=pipe_chain_anchors(q,other,comp,model,pages)
        if not anchors:anchors=curved_elbow_candidates({'coordinate_mm':other},model,pages)
        if not anchors:continue
        anchor=anchors[0];stem=anchor['page_stem'];page=pages[stem];root=(anchor['x_mm'],anchor['y_mm'])
        dx,dy=projection([q[k]-other[k] for k in range(3)]);length=math.hypot(dx,dy)
        if length<.01:continue
        u=(dx/length,dy/length);dots=[]
        for dot in page['dots']:
            vx,vy=dot['x_mm']-root[0],dot['y_mm']-root[1]
            along=vx*u[0]+vy*u[1];cross=abs(vx*u[1]-vy*u[0])
            if along>1 and cross<.2:dots.append((along,dot))
        if not dots:
            # A skewed pipe may not follow the standard isometric projection.
            # Only a model degree-one boundary can instead use a unique native
            # straight stroke from an independently proven curved-elbow port
            # to the next actual weld glyph. Never cross an intervening HIT.
            curved=any(e.get('method')=='beihai-curved-elbow-two-native-welded-ports'
                       for e in anchor.get('evidence',[]))
            if len(near)!=1 or not curved:continue
            native={}
            for axis in page['heavy_segments']:
                if axis.get('stroke_count',0)<3:continue
                for start,end in ((axis['a'],axis['b']),(axis['b'],axis['a'])):
                    if math.dist(start,root)>.15 or math.dist(root,end)<1:continue
                    symbols=[d for d in page['dots'] if math.dist(end,(d['x_mm'],d['y_mm']))<.15]
                    if not symbols:continue
                    v=[end[k]-root[k] for k in (0,1)];n=sum(x*x for x in v);blocked=False
                    for hit in page['hits']:
                        w=[hit['x_mm']-root[0],hit['y_mm']-root[1]]
                        f=sum(w[k]*v[k] for k in (0,1))/n
                        if .01<f<.99 and abs(w[0]*v[1]-w[1]*v[0])/math.sqrt(n)<1:blocked=True
                    if not blocked:native[tuple(end)]=(symbols[0],axis)
            if len(native)!=1:continue
            end,(dot,axis)=next(iter(native.items()))
            choices.append({'page_stem':stem,'x_mm':end[0],'y_mm':end[1],'score':-200,
                'evidence':[{'ref':comp['ref'],'code':comp['code'],'idf_line':comp['line'],'score':-100,
                    'along_mm':math.dist(root,end),'cross_error_mm':0,
                    'method':'beihai-free-pipe-native-axis-from-curved-port',
                    'opposite_terminal':anchor,'dot_offset':dot['offset'],'axis_offset':axis['offset']}]})
            continue
        _,dot=min(dots,key=lambda x:x[0]);p=(dot['x_mm'],dot['y_mm'])
        bridges=[]
        if not native_axis_covers(page,root,p,bridges,allow_filled_controls=allow_filled_controls):continue
        choices.append({'page_stem':stem,'x_mm':p[0],'y_mm':p[1],'score':-200,
            'evidence':[{'ref':comp['ref'],'code':comp['code'],'idf_line':comp['line'],'score':-100,
                'along_mm':math.dist(root,p),'cross_error_mm':0,'method':'beihai-pipe-terminal-native-axis-next-weld',
                'opposite_terminal':anchor,'dot_offset':dot['offset'],'native_axis_bridges':bridges}]})
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def pipe_chain_anchors(q,other,initial,model,pages):
    """Follow collinear IDF pipe subdivisions until a mapped fitting terminal.

    HSTU/LSTU may partition a single printed pipe at a support or model stub.
    Stop at any intervening fitting/weld, never walk through an unlocated one.
    """
    direction=[other[k]-q[k] for k in range(3)];length=math.sqrt(sum(v*v for v in direction))
    if length<.1:return []
    queue=[(other,{initial['line']},[initial['ref']])]
    for _ in range(64):
        if not queue:break
        point,seen,refs=queue.pop(0)
        anchors=beihai_candidates({'coordinate_mm':point},model,pages,allow_pipe=False)
        if anchors:
            return [dict(a,model_anchor_mm=point,pipe_chain_refs=refs) for a in anchors]
        touching=[c for c in model['components'] if any(math.dist(point,p)<.11 for p in c['ports'])]
        if any(c['code'] not in (100,101,150) for c in touching):continue
        next_steps=[]
        for c in touching:
            if c['line'] in seen or c['code'] not in (100,101) or len(c['ports'])!=2:continue
            a,b=c['ports'];far=b if math.dist(a,point)<.11 else a
            v=[far[k]-q[k] for k in range(3)];fraction=sum(v[k]*direction[k] for k in range(3))/length**2
            if fraction<=0 or math.dist(far,[q[k]+fraction*direction[k] for k in range(3)])>.11:continue
            next_steps.append((far,seen|{c['line']},refs+[c['ref']]))
        if len(next_steps)==1:queue.extend(next_steps)
    return []


def crossing_knockout(page,a,u,left,right):
    """A drawing-only pipe gap may hide a crossing, but never a fitting."""
    if not 1.5<right-left<9:return None
    for hit in page.get('hits',[]):
        v=(hit['x_mm']-a[0],hit['y_mm']-a[1])
        if left-.5<v[0]*u[0]+v[1]*u[1]<right+.5 and abs(v[0]*u[1]-v[1]*u[0])<2:return None
    choices=[]
    for segment in page['heavy_segments']:
        c,d=segment['a'],segment['b'];v=(d[0]-c[0],d[1]-c[1]);length=math.hypot(*v)
        denominator=u[0]*v[1]-u[1]*v[0]
        if length<15 or segment.get('stroke_count',0)<3 or abs(denominator)/length<.5:continue
        w=(c[0]-a[0],c[1]-a[1])
        along=(w[0]*v[1]-w[1]*v[0])/denominator
        fraction=(w[0]*u[1]-w[1]*u[0])/denominator
        if .1<fraction<.9 and abs(along-(left+right)/2)<1:
            choices.append({'method':'native-crossing-pipe-knockout','crossing_offset':segment['offset'],
                'gap_along_mm':[left,right],'crossing_along_mm':along,'crossing_segment':[c,d]})
    return choices[0] if len(choices)==1 else None


def native_axis_covers(page,a,b,break_evidence=None,allow_filled_controls=False):
    """Require a continuous, collinear native thick axis (allow stroke rounding)."""
    length=math.dist(a,b)
    if length<.1:return False
    u=tuple((b[k]-a[k])/length for k in (0,1))
    intervals=[]
    for segment in page['heavy_segments']+page.get('flow_axes',[]):
        points=(segment['a'],segment['b'])
        if any(abs((p[0]-a[0])*u[1]-(p[1]-a[1])*u[0])>.2 for p in points):continue
        v=sorted((p[0]-a[0])*u[0]+(p[1]-a[1])*u[1] for p in points)
        intervals.append(v)
    # Filled weld controls use the glyph centre; the pipe stroke terminates
    # at its outline. Bridge only the actual filled polygon on this axis.
    for dot in page.get('dots',[]) if allow_filled_controls else []:
        if not dot.get('fill_offsets') or min(math.dist((dot['x_mm'],dot['y_mm']),p) for p in (a,b))>.15:continue
        polygon=dot.get('glyph_points',[]);crossings=[]
        for p,q in zip(polygon,polygon[1:]):
            dp=[p[k]-a[k] for k in (0,1)];dq=[q[k]-a[k] for k in (0,1)]
            cp=dp[0]*u[1]-dp[1]*u[0];cq=dq[0]*u[1]-dq[1]*u[0]
            if cp*cq>0 or abs(cp-cq)<1e-9:continue
            f=cp/(cp-cq);crossings.append(sum((dp[k]+f*(dq[k]-dp[k]))*u[k] for k in (0,1)))
        if len(crossings)<2:continue
        left,right=min(crossings),max(crossings)
        centre=sum((dot[['x_mm','y_mm'][k]]-a[k])*u[k] for k in (0,1))
        if not left<=centre<=right or right-left>3:continue
        intervals.append([left,right])
        if break_evidence is not None:break_evidence.append({'method':'native-filled-weld-control-axis-bridge','dot_offset':dot['offset'],'axis_interval_mm':[left,right]})
    reach=0
    for left,right in sorted(intervals):
        if right<0:continue
        if left>reach+.35:
            proof=crossing_knockout(page,a,u,reach,left)
            if proof is None:break
            if break_evidence is not None:break_evidence.append(proof)
        reach=max(reach,right)
    return reach>=length-.2


def explicit_pipe_weld_candidates(weld,model,pages):
    """An IDF120 free pipe end needs an actual native weld glyph and pipe axis.

    Try independent fitting controls as well as a support control. A support's
    HIT may lie on a different elbow leg even when its IDF point is coincident.
    """
    q=weld['coordinate_mm']
    near=[c for c in model['components'] if any(math.dist(q,p)<.11 for p in c['ports'])]
    welds=[c for c in near if c['code']==120];physical=[c for c in near if c['code']!=120]
    if not welds or len(physical)!=1 or physical[0]['code'] not in (100,101):return []
    pipe=physical[0];a,b=pipe['ports'];other=b if math.dist(q,a)<.11 else a
    anchors=beihai_candidates({'coordinate_mm':other},model,pages,allow_pipe=False,allow_elbow=False)
    anchors+=weld_candidates({'coordinate_mm':other},model,pages)
    anchors+=curved_elbow_candidates({'coordinate_mm':other},model,pages)
    v=projection([q[k]-other[k] for k in range(3)]);length=math.hypot(*v)
    if length<.01:return []
    u=[x/length for x in v];choices=[];by_ref={c['ref']:c['code'] for c in model['components']}
    for anchor in anchors:
        stem=anchor['page_stem'];page=pages[stem];root=(anchor['x_mm'],anchor['y_mm']);dots=[]
        for dot in page['dots']:
            p=(dot['x_mm'],dot['y_mm']);d=[p[k]-root[k] for k in (0,1)]
            along=sum(d[k]*u[k] for k in (0,1));cross=abs(d[0]*u[1]-d[1]*u[0])
            if along>1 and cross<.2 and native_axis_covers(page,root,p):dots.append((along,p,dot))
        if not dots:continue
        distance,p,dot=min(dots,key=lambda x:x[0]);blocked=False
        for hit in page['hits']:
            d=[hit['x_mm']-root[0],hit['y_mm']-root[1]];along=sum(d[k]*u[k] for k in (0,1))
            if not .15<along<distance-.15 or abs(d[0]*u[1]-d[1]*u[0])>=1:continue
            if by_ref.get(hit['ref']) in (100,101,150):continue
            if any(by_ref.get(prefix+hit['ref']) in (100,101) for prefix in ('HSTU_','LSTU_')):continue
            blocked=True;break
        if blocked:continue
        choices.append({'page_stem':stem,'x_mm':p[0],'y_mm':p[1],'score':-205,
            'evidence':[{'ref':pipe['ref'],'code':pipe['code'],'idf_line':pipe['line'],'score':-105,
                'along_mm':distance,'cross_error_mm':0,'method':'beihai-IDF120-free-end-independent-fitting-native-weld',
                'idf_weld_lines':[c['line'] for c in welds],'opposite_terminal':anchor,
                'dot_offset':dot['offset'],'native_weld_method':dot['method']}]})
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    return list(unique.values()) if len(unique)==1 else []


def plain_pipe_terminal(port,other,component,model,pages,_expanded=False):
    """A degree-one model boundary can use a unique drawn open-pipe end."""
    touching=[c for c in model['components'] if (not _expanded or c['code']!=120) and any(math.dist(port,p)<.11 for p in c['ports'])]
    if len(touching)!=1 or touching[0]['code'] not in (100,101):
        return plain_pipe_terminal(port,other,component,model,pages,True) if not _expanded else []
    anchors=beihai_candidates({'coordinate_mm':other},model,pages,allow_pipe=False,allow_elbow=False)
    if _expanded:
        anchors+=weld_candidates({'coordinate_mm':other},model,pages)
        anchors+=curved_elbow_candidates({'coordinate_mm':other},model,pages)
    direction=projection([port[k]-other[k] for k in range(3)]);length=math.hypot(*direction)
    if length<.1:return []
    u=[v/length for v in direction];choices=[];by_ref={c['ref']:c['code'] for c in model['components']}
    for anchor in anchors:
        stem=anchor['page_stem'];page=pages[stem];root=(anchor['x_mm'],anchor['y_mm'])
        def along(p):return sum((p[k]-root[k])*u[k] for k in (0,1))
        def cross(p):return abs((p[0]-root[0])*u[1]-(p[1]-root[1])*u[0])
        intervals=[]
        for segment in page['heavy_segments']+(page.get('flow_axes',[]) if _expanded else []):
            if max(cross(segment['a']),cross(segment['b']))>.2:continue
            left,right=sorted((along(segment['a']),along(segment['b'])))
            if right>0:intervals.append((left,right,segment))
        reach=0;used=[]
        for left,right,segment in sorted(intervals,key=lambda x:x[:2]):
            if left>reach+.35:
                if crossing_knockout(page,root,u,reach,left) is None:break
            if right>reach:used.append(segment);reach=right
        if reach<8 or not used:continue
        end=max((used[-1]['a'],used[-1]['b']),key=along)
        # A filled FLOW arrow is an interior pipe graphic, never a free end.
        # Derive the guard from the native path even if cached axes are absent.
        flow_axes=page.get('flow_axes') or flow_arrow_axes(page['data'])
        if any(min(math.dist(end,f['a']),math.dist(end,f['b']))<.4 for f in flow_axes):continue
        left,bottom,right,top=page['data']['drawing_bounds_mm']
        if not (left+3<end[0]<right-3 and bottom+3<end[1]<top-3):continue
        if not native_axis_covers(page,root,end):continue
        blocked=False
        for hit in page['hits']:
            p=(hit['x_mm'],hit['y_mm'])
            if not (0<along(p)<reach+2 and cross(p)<1):continue
            if by_ref.get(hit['ref']) in (100,101,150):continue
            if re.fullmatch(r'/[^/]+0{3,}\d+',hit['name']):continue
            blocked=True;break
        if blocked:continue
        if any(min(math.dist(end,s['a']),math.dist(end,s['b']))<.4 and
               abs((s['b'][0]-s['a'][0])*u[1]-(s['b'][1]-s['a'][1])*u[0])>.5 for s in page['heavy_segments']):continue
        curve=False
        for path in native_paths(page['data']):
            points=path['points']
            if _expanded:points=[p for p in points if math.dist(p,end)<4]
            if len(points)>10 and min(math.dist(end,p) for p in points)<.4 and max(cross(p) for p in points)>.6:
                diagonal=math.hypot(max(p[0] for p in points)-min(p[0] for p in points),max(p[1] for p in points)-min(p[1] for p in points))
                if sum(math.dist(a,b) for a,b in zip(points,points[1:]))>3*diagonal:curve=True;break
        if curve:continue
        choices.append({'page_stem':stem,'x_mm':end[0],'y_mm':end[1],'score':-190,
            'evidence':[{'ref':component['ref'],'code':component['code'],'idf_line':component['line'],'score':-90,
                'cross_error_mm':cross(end),'along_mm':reach,'method':'beihai-model-degree-one-native-open-pipe-end',
                'model_endpoint_mm':port,'opposite_terminal':anchor,'axis_offsets':[s['offset'] for s in used]}]})
    unique={(c['page_stem'],round(c['x_mm'],2),round(c['y_mm'],2)):c for c in choices}
    if not unique and not _expanded:return plain_pipe_terminal(port,other,component,model,pages,True)
    return list(unique.values()) if len(unique)==1 else []


def resolve_pipe_interiors(mapped,unresolved,model,pages):
    """Interpolate additional cuts using independently mapped IDF pipe terminals.

    Printed isometrics are distorted: interpolate only inside a single pipe
    whose two terminals are independently established on a native straight axis.
    Keep these inferred positions on the manual-review list.
    """
    cache={}
    chain_cache={}
    def terminals(q):
        key=tuple(q)
        if key not in cache:
            candidates=beihai_candidates({'coordinate_mm':q},model,pages)
            best=candidates[:1]
            if len(candidates)>1 and math.dist((candidates[0]['x_mm'],candidates[0]['y_mm']),
                                              (candidates[1]['x_mm'],candidates[1]['y_mm']))>1:
                # Preserve the alternatives until both ends are checked on a
                # native continuous pipe axis. A fitting face and its welded
                # port can differ by >1mm; only one joins the actual pipe.
                best=candidates
            cache[key]=best
        return cache[key]
    for target in list(unresolved):
        q=target['coordinate_mm'];choices=[]
        for c in model['components']:
            if c['code'] not in (100,101) or len(c['ports'])!=2:continue
            a,b=c['ports'];v=tuple(b[k]-a[k] for k in range(3));n=sum(x*x for x in v)
            t=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if not 0<t<1 or math.dist(q,tuple(a[k]+t*v[k] for k in range(3)))>.1:continue
            def anchored(port):
                direct=terminals(port)
                if direct:return direct
                key=(c['line'],tuple(port))
                if key not in chain_cache:
                    found=pipe_chain_anchors(q,port,c,model,pages)
                    if not found:found=plain_pipe_terminal(port,b if port==a else a,c,model,pages)
                    points={(x['page_stem'],round(x['x_mm'],2),round(x['y_mm'],2)) for x in found}
                    chain_cache[key]=found[:1] if len(points)==1 else []
                return chain_cache[key]
            for ca in anchored(a):
                for cb in anchored(b):
                    if ca['page_stem']!=cb['page_stem']:continue
                    model_a=ca.get('model_anchor_mm',a);model_b=cb.get('model_anchor_mm',b)
                    direction=[model_b[k]-model_a[k] for k in range(3)];length2=sum(v*v for v in direction)
                    fraction=sum((q[k]-model_a[k])*direction[k] for k in range(3))/length2 if length2 else -1
                    if not 0<fraction<1 or math.dist(q,[model_a[k]+fraction*direction[k] for k in range(3)])>.1:continue
                    pa=(ca['x_mm'],ca['y_mm']);pb=(cb['x_mm'],cb['y_mm'])
                    breaks=[]
                    if not native_axis_covers(pages[ca['page_stem']],pa,pb,breaks):continue
                    if breaks:ca=dict(ca,native_axis_breaks=breaks)
                    p=tuple(pa[k]+fraction*(pb[k]-pa[k]) for k in (0,1))
                    choices.append((ca['page_stem'],p,c['ref'],fraction,ca,cb))
        unique={(s,round(p[0],2),round(p[1],2)):(s,p,ref,t,ca,cb) for s,p,ref,t,ca,cb in choices}
        if len(unique)!=1:continue
        stem,p,ref,t,ca,cb=next(iter(unique.values()))
        target.update(page_stem=stem,x_mm=p[0],y_mm=p[1],mapping_method='beihai-independent-pipe-terminals-interpolation',
            mapping_evidence={'pipe_ref':ref,'fraction':t,'terminals':[ca,cb]},
            review_notes=[{'reason':'管内附加焊口按两端定位及原图直线插值；等轴图非比例绘制，请复核实际预制分段位置'}])
        mapped.append(target);unresolved.remove(target)
    from beihai_pipe_junctions import resolve_pipe_junctions
    resolve_pipe_junctions(mapped,unresolved,model,pages,pipe_chain_anchors,native_axis_covers)


def unresolved_diagnosis(target,model,pages=None):
    q=target['coordinate_mm']
    for pipe in model['components']:
        if pipe['code'] not in (100,101) or len(pipe['ports'])!=2 or not any(math.dist(q,p)<.11 for p in pipe['ports']):continue
        for fitting in model['components']:
            if fitting['code']!=126 or len(fitting['ports'])!=2:continue
            a,b=fitting['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
            f=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if not 0<f<1 or math.dist(q,[a[k]+f*v[k] for k in range(3)])>.1:continue
            if not any(math.dist(p,b)<.11 for p in pipe['ports']):continue
            length=math.dist(*pipe['ports'])
            return {'category':'源数据回折重叠，原图无独立管端',
                'reason':f"IDF第{pipe['line']}行管子从短节B端回折{length:.2f}mm，终点位于第{fitting['line']}行NRSC短节内部；原图未找到独立管端/焊口图元，需设计确认末端坐标或是否应保留此编号",
                'pipe_ref':pipe['ref'],'fitting_ref':fitting['ref'],'pipe_line':pipe['line'],
                'fitting_line':fitting['line'],'pipe_ports':pipe['ports'],'fitting_ports':fitting['ports']}
    if pages is not None:
        from beihai_issue_diagnostics import paper_diagnosis
        return paper_diagnosis(target,model,pages,beihai_candidates)
    return {'category':'纸面依据不足','reason':'IDF坐标可核对，但缺少唯一且有原图几何依据的纸面定位；未猜测绘制'}
