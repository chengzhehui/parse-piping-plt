"""Spool roots at the middle of a verified neighbouring component stroke."""
import math
from pdms_weld_geometry import native_paths,projection
from render_complete_pdms import nearest_point


def _adjacent(component,q):
    if any(math.dist(q,p)<1 for p in component['ports']):return True
    if component['code'] in (100,101) and len(component['ports'])==2:
        a,b=component['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
        f=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
        return 0<f<1 and math.dist(q,[a[k]+f*v[k] for k in range(3)])<.11
    return False


def _directions(component,q):
    if component['code'] in (100,101):points=component['ports']
    elif component['code'] in (35,40,45):points=[component['segments'][0]['b']]
    else:points=component['ports']
    result=[]
    for p in points:
        dx,dy=projection([p[k]-q[k] for k in range(3)]);n=math.hypot(dx,dy)
        if n>.1:result.append((dx/n,dy/n))
    return result


def _stroke_midpoint(page,axis,root,welds):
    """Clip at other welds, then use an actual PLT stroke, not a box centre."""
    a,b=axis['a'],axis['b'];length=math.dist(a,b)
    if length<1.4:return None
    u=((b[0]-a[0])/length,(b[1]-a[1])/length)
    projected,dist,f=nearest_point(root,a,b)
    if dist>.9:return None
    start=max(0,min(length,f*length));choices=[]
    paths=page.get('_spool_paths')
    if paths is None:
        paths={p['offsets'][0]:p for p in native_paths(page['data']) if p['offsets']}
        page['_spool_paths']=paths
    path=paths.get(axis['offset'])
    if not path:return None
    cuts=[0.,length]
    for w in welds:
        point=(w['x_mm'],w['y_mm'])
        _,d,t=nearest_point(point,a,b)
        if d<.25 and .005<t<.995:cuts.append(t*length)
    left=max([p for p in cuts if p<start-.5],default=0)
    right=min([p for p in cuts if p>start+.5],default=length)
    # A weld strictly inside a native axis divides it into two component pieces.
    intervals=[(left,start),(start,right)] if .5<start<length-.5 else [(0,right)] if start<=.5 else [(left,length)]
    for lo,hi in intervals:
        if hi-lo<1.4:continue
        centre=(lo+hi)/2
        direction=(u[0],u[1]) if centre>start else (-u[0],-u[1])
        for i,(p,q) in enumerate(zip(path['points'],path['points'][1:])):
            span=math.dist(p,q)
            if span<1.4:continue
            if abs((q[0]-p[0])*u[1]-(q[1]-p[1])*u[0])/span>.015:continue
            normal=abs((p[0]-a[0])*u[1]-(p[1]-a[1])*u[0])
            if normal>.5:continue
            pa=(p[0]-a[0])*u[0]+(p[1]-a[1])*u[1];pb=(q[0]-a[0])*u[0]+(q[1]-a[1])*u[1]
            x0=max(lo,min(pa,pb));x1=min(hi,max(pa,pb))
            if x1-x0<1.4:continue
            def on(value):
                t=(value-pa)/(pb-pa)
                return (p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1]))
            ends=(on(x0),on(x1));point=tuple((ends[0][k]+ends[1][k])/2 for k in (0,1))
            choices.append((normal,-(x1-x0),point,direction,ends,{'a':p,'b':q,'offset':path['offsets'][i]}))
    # Retain one actual stroke for each side, preferring its centre-most pen.
    best={}
    for c in sorted(choices,key=lambda c:c[:2]):
        side=c[3];best.setdefault(side,c)
    return list(best.values())


def component_midpoint_anchor(members,page,model,all_welds):
    options=[]
    def physical_root(weld):
        point=(weld['x_mm'],weld['y_mm'])
        # A legacy weld solution can be a polygon vertex. For locating the
        # attached component only, corroborate its actual filled-symbol centre.
        centres=[(d['x_mm'],d['y_mm']) for d in page['dots']
                 if d['method']=='native-six-sided-outline-and-independent-fill'
                 and min(math.dist(point,p) for p in d['glyph_points'])<.15
                 and math.dist(point,(d['x_mm'],d['y_mm']))<1.5]
        return centres[0] if len(centres)==1 else point
    for member in sorted(members,key=lambda w:(w['weld_type']!='S',w['source_row'])):
        q=member['coordinate_mm'];root=physical_root(member)
        adjacent=[c for c in model['components'] if c['code'] not in (110,115,120,150) and _adjacent(c,q)]
        for axis in page['heavy_segments']:
            strokes=_stroke_midpoint(page,axis,root,all_welds)
            if not strokes:continue
            for _,negative_length,point,direction,ends,stroke in strokes:
                for comp in adjacent:
                    ownership='projected-neighbour-direction'
                    aligned=any(direction[0]*u[0]+direction[1]*u[1]>.995 for u in _directions(comp,q))
                    if not aligned and comp['code'] in (100,101):
                        ends_by_port=[[physical_root(w) for w in all_welds if math.dist(w['coordinate_mm'],port)<1] for port in comp['ports']]
                        for port,controls in zip(comp['ports'],ends_by_port):
                            support_refs={c['ref'] for c in model['components'] if c['code']==150 and any(math.dist(port,p)<.11 for p in c['ports'])}
                            controls.extend((h['x_mm'],h['y_mm']) for h in page['hits'] if h['ref'] in support_refs)
                        for aa in ends_by_port[0]:
                            for bb in ends_by_port[1]:
                                if math.dist(aa,bb)>1 and nearest_point(aa,axis['a'],axis['b'])[1]<.3 and nearest_point(bb,axis['a'],axis['b'])[1]<.3 and nearest_point(point,aa,bb)[1]<.5:
                                    aligned=True;ownership='two-mapped-IDF-pipe-ports'
                    if not aligned:continue
                    rank=0 if comp['code'] in (100,101) else 1
                    proof={'component_ref':comp['ref'],'component_code':comp['code'],'idf_line':comp['line'],
                        'component_ports_mm':comp['ports'],'related_weld':member['key'],'model_weld_mm':q,
                        'native_stroke':stroke,'usable_segment_mm':ends,'anchor_mm':point,
                        'method':'IDF-adjacent-component-native-stroke-midpoint','ownership_rule':ownership,
                        'component_port_root_mm':root}
                    options.append(((member['weld_type']!='S',rank,negative_length,member['source_row'],stroke['offset']),point,member,proof))
        # A thin flange or short assembly can have no repeated-pen pipe axis.
        # Its UCI-owned contour still provides real component lines.
        for comp in adjacent:
            if comp['code']!=105:continue
            hit=next((h for h in page['hits'] if h['ref']==comp['ref']),None)
            if not hit:continue
            h=(hit['x_mm'],hit['y_mm'])
            for outline in page['port_outlines']:
                if math.dist(outline['center'],h)>1.4 or math.dist(*outline['ports'])>1.5:continue
                for a,b in zip(outline['polygon'],outline['polygon'][1:]):
                    length=math.dist(a,b)
                    if length<1.4:continue
                    point=tuple((a[k]+b[k])/2 for k in (0,1))
                    # Find the actual decoded segment, preserving byte evidence.
                    segment=next((s for s in page['data']['segments'] if
                        math.dist(a,[v/10 for v in s['a']])<.01 and math.dist(b,[v/10 for v in s['b']])<.01),None)
                    if segment is None:continue
                    proof={'component_ref':comp['ref'],'component_code':comp['code'],'idf_line':comp['line'],
                        'component_ports_mm':comp['ports'],'related_weld':member['key'],'model_weld_mm':q,
                        'native_stroke':{'a':a,'b':b,'offset':segment['offset']},'usable_segment_mm':(a,b),
                        'anchor_mm':point,'method':'UCI-owned-flange-contour-stroke-midpoint'}
                    options.append(((member['weld_type']!='S',2,-length,member['source_row'],segment['offset']),point,member,proof))
    if not options:raise ValueError('未找到可证明属于该管段的元件线条中点')
    _,point,member,proof=min(options,key=lambda x:x[0])
    return point,member,proof
