"""Recover native weld-symbol centres and associate IDF interfaces with PLT/HIT."""
from collections import Counter, defaultdict
import math
from statistics import median


def projection(v):
    return (.8660254037844386*(v[0]-v[1]),.5*(v[0]+v[1])+v[2])


def native_paths(data):
    paths=[]
    points=[]
    offsets=[]
    for r in data['records']:
        if r['kind'].startswith('move'):
            if len(points)>1:
                paths.append({'points':points,'offsets':offsets})
            points=[tuple(x/10 for x in r['to'])]
            offsets=[]
        elif r['kind'].startswith('draw'):
            if not points:
                points=[tuple(x/10 for x in r['from'])]
            points.append(tuple(x/10 for x in r['to']))
            offsets.append(r['offset'])
    if len(points)>1:
        paths.append({'points':points,'offsets':offsets})
    return paths


def native_weld_dots(data):
    result={}
    left,bottom,right,top=data.get('drawing_bounds_mm',(180,20,data['width_mm'],data['height_mm']))
    paths=native_paths(data)
    for path_index,path in enumerate(paths):
        pts=path['points']
        for j in range(len(pts)-13):
            window=pts[j:j+14]
            w=max(p[0] for p in window)-min(p[0] for p in window)
            h=max(p[1] for p in window)-min(p[1] for p in window)
            if (window[0]!=window[-1] or len(set(window))!=7 or
                    not (.4<w<3.5 and .4<h<3.5)):
                continue
            # PLT origin is +0.9 mm in X relative to HIT in this batch.
            # Keep the physical PLT root, and transform HIT anchors instead.
            x,y=window[0]
            if not (left<=x<=right and bottom<=y<=top):
                continue
            result[(x,y)]={'x_mm':x,'y_mm':y,'offset':path['offsets'][j],
                           'glyph_points':window,'method':'native-13-stroke-weld-symbol'}
        # Socket-weld symbols are a four-corner outline starting at the
        # midpoint of one edge, followed by an 18-vertex hatch path.
        for j in range(len(pts)-5):
            window=pts[j:j+6]
            if window[0]!=window[-1] or len(set(window))!=5:
                continue
            if math.dist(window[0],tuple((window[1][k]+window[4][k])/2 for k in (0,1)))>.12:
                continue
            w=max(p[0] for p in window)-min(p[0] for p in window)
            h=max(p[1] for p in window)-min(p[1] for p in window)
            if not (.4<w<5.5 and .4<h<5.5) or path_index+1>=len(paths):
                continue
            hatch=paths[path_index+1]['points']
            if len(hatch)<18 or math.dist(hatch[0],window[1])>.15 or math.dist(hatch[17],window[2])>.15:
                continue
            x,y=window[0]
            if not (left<=x<=right and bottom<=y<=top):
                continue
            result[(x,y)]={'x_mm':x,'y_mm':y,'offset':path['offsets'][j],
                           'glyph_points':window,'method':'native-socket-outline-and-hatch'}
    return list(result.values())


def weld_candidates(weld,model,pages):
    point=weld['coordinate_mm']
    query=(point[0],point[1],point[2]-model.get('z_offset_mm',1000))
    data=model['data']
    components=model['components']
    near=[c for c in components if any(math.dist(query,p)<=1 for p in c['ports'])]
    candidates={}
    evidence=[]
    for c in near:
        loc=data['locations'].get(c['ref'])
        if not loc or c['code'] in (100,102,110,115,150):
            continue
        for stem,page in pages.items():
            hit=next((h for h in page['hits'] if h['ref']==c['ref']),None)
            if hit is None:
                continue
            dx_hit,dy_hit=page.get('hit_offset_mm',(.9,0))
            hx,hy=hit['x_mm']+dx_hit,hit['y_mm']+dy_hit
            if c['code']==120:
                direction=None
            else:
                center=loc['xyz_mm']
                v=tuple(query[k]-center[k] for k in range(3))
                dx,dy=projection(v)
                length=math.hypot(dx,dy)
                direction=(dx/length,dy/length) if length>=.05 else None
            local_geometry=[]
            if c['code']==105 and c.get('skey')=='FLSW':
                for outline in page.get('port_outlines',[]):
                    span=math.dist(*outline['ports'])
                    if .55<span<1.05 and math.dist(outline['center'],(hx,hy))<1.35:
                        port=min(outline['ports'],key=lambda p:math.dist(p,(hx,hy)))
                        local_geometry.append((port,-35+math.dist(port,(hx,hy)),
                                               'socket-flange-thin-face-pipe-port',outline['offset']))
            if c['code'] in (55,101,130):
                for outline in page.get('port_outlines',[]):
                    if math.dist(outline['center'],(hx,hy))>.22:
                        continue
                    for port in outline['ports']:
                        vx,vy=port[0]-hx,port[1]-hy
                        dot=vx*direction[0]+vy*direction[1] if direction else 0
                        cross=abs(vx*direction[1]-vy*direction[0]) if direction else 0
                        if dot>.1 and cross<1.6:
                            local_geometry.append((port,-25+cross,'native-component-outline-port',outline['offset']))
            if c['code']==120:
                local_geometry.append(((hx,hy),-30,'explicit-IDF120-HIT-transform',None))
            elif c['code'] in (35,40,45,55) and direction:
                leg=2.8 if c['code']==55 else 9
                predicted=(hx+direction[0]*leg,hy+direction[1]*leg)
                vertices=page.get('vertices',[])
                if vertices:
                    error,vertex=min((math.dist(predicted,p),p) for p in vertices)
                    if error<.23:
                        local_geometry.append((vertex,-12+error,'HIT-local-leg-and-native-vertex',None))
            for port,score,method,offset in local_geometry:
                key=(stem,round(port[0],3),round(port[1],3))
                ev={'ref':c['ref'],'code':c['code'],'idf_line':c['line'],
                    'cross_error_mm':0,'along_mm':math.dist(port,(hx,hy)),'score':score,'method':method}
                candidates.setdefault(key,{'page_stem':stem,'x_mm':key[1],'y_mm':key[2],
                                           'dot_offset':offset,'evidence':[]})['evidence'].append(ev)
            for dot in page['dots']:
                vx,vy=dot['x_mm']-hx,dot['y_mm']-hy
                radius=math.hypot(vx,vy)
                if direction is None:
                    if radius>.2:
                        continue
                    error=radius
                    along=0
                    cross=radius
                else:
                    along=vx*direction[0]+vy*direction[1]
                    cross=abs(vx*direction[1]-vy*direction[0])
                    if along<.2 or along>20 or cross>(1.6 if c['code'] in (35,55) else .65):
                        continue
                    expected={35:9,40:9,45:9,105:2,55:4.5,130:4.5,101:5}.get(c['code'],5)
                    error=cross*8+abs(along-expected)*.35
                key=(stem,dot['x_mm'],dot['y_mm'])
                ev={'ref':c['ref'],'code':c['code'],'idf_line':c['line'],
                    'cross_error_mm':cross,'along_mm':along,'score':error}
                if key not in candidates:
                    candidates[key]={'page_stem':stem,'x_mm':dot['x_mm'],'y_mm':dot['y_mm'],
                                     'dot_offset':dot['offset'],'evidence':[]}
                candidates[key]['evidence'].append(ev)
    result=[]
    for candidate in candidates.values():
        ev=candidate['evidence']
        def ranked_score(e):
            # A socket weld is marked at the fitting mouth. Plain fixed-pipe
            # outlines describe the inserted pipe end, which can be displaced
            # by the 1.2 mm drawing insertion convention.
            code=e['code']
            bias=-100 if code==120 else -40 if code==130 else 15 if code==101 else 0
            return e['score']+bias
        candidate['score']=min(ranked_score(e) for e in ev)-4*(len({e['ref'] for e in ev})-1)
        result.append(candidate)
    return sorted(result,key=lambda r:r['score'])


def component_port_outlines(data):
    outlines=[]
    vertices=set()
    for path in native_paths(data):
        pts=path['points']
        vertices.update(pts)
        for j in range(len(pts)-5):
            w=pts[j:j+6]
            if w[0]!=w[-1] or len(set(w))!=5:
                continue
            if math.dist(w[0],tuple((w[1][k]+w[4][k])/2 for k in (0,1)))>.12:
                continue
            other=tuple((w[2][k]+w[3][k])/2 for k in (0,1))
            if .2<math.dist(w[0],other)<20:
                outlines.append({'center':tuple((w[0][k]+other[k])/2 for k in (0,1)),
                                 'ports':[w[0],other],'offset':path['offsets'][j],'polygon':w})
    return outlines,list(vertices)


def heavy_straight_segments(data):
    """Centre axes of native multi-stroke pipes, fitting legs and short tubes."""
    result={}
    for path in native_paths(data):
        pts=path['points']
        edges=[(a,b,math.dist(a,b)) for a,b in zip(pts,pts[1:]) if math.dist(a,b)>.45]
        if len(edges)<4:
            continue
        longest=max(edges,key=lambda e:e[2])
        u=tuple((longest[1][k]-longest[0][k])/longest[2] for k in (0,1))
        selected=[e for e in edges if e[2]>=longest[2]*.75 and
                  abs(((e[1][0]-e[0][0])*u[0]+(e[1][1]-e[0][1])*u[1])/e[2])>.999]
        if len(selected)<4:
            continue
        # Thick-line oscillations have six long strokes in a <=1.2 mm band.
        normals=[p[0]*u[1]-p[1]*u[0] for a,b,l in selected for p in (a,b)]
        if max(normals)-min(normals)>1.25:
            continue
        groups=[[],[]]
        for a,b,l in selected:
            if a[0]*u[0]+a[1]*u[1]>b[0]*u[0]+b[1]*u[1]:
                a,b=b,a
            groups[0].append(a)
            groups[1].append(b)
        a,b=[tuple(round(median(p[k] for p in g),3) for k in (0,1)) for g in groups]
        if math.dist(a,b)>.45:
            key=tuple(sorted((a,b)))
            result[key]={'a':a,'b':b,'offset':path['offsets'][0],'stroke_count':len(selected)}
    return list(result.values())
