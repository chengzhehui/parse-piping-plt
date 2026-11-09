"""A single model pipe and a single native axis can identify a free end."""
import math
from pdms_weld_geometry import projection


def singleton_pipe_candidates(weld,model,pages,axis_covers):
    if len(pages)!=1 or any(p['hits'] for p in pages.values()):return []
    physical=[c for c in model['components'] if c['code'] not in (110,115,120,150)]
    if len(physical)!=1 or physical[0]['code'] not in (100,101) or len(physical[0]['ports'])!=2:return []
    pipe=physical[0];q=weld['coordinate_mm'];index=min(range(2),key=lambda i:math.dist(q,pipe['ports'][i]))
    if math.dist(q,pipe['ports'][index])>.11:return []
    attached=[c for c in model['components'] if c['code'] not in (115,120,150) and any(math.dist(q,p)<.11 for p in c['ports'])]
    if len(attached)!=1:return []
    vector=projection([pipe['ports'][1][k]-pipe['ports'][0][k] for k in range(3)]);length=math.hypot(*vector)
    if length<1:return []
    u=[v/length for v in vector];stem,page=next(iter(pages.items()));left,bottom,right,top=page['data']['drawing_bounds_mm']
    if page['dots'] or page['valve_bodies']:return []
    axes=[s for s in page['heavy_segments'] if s.get('stroke_count',0)>=3 and math.dist(s['a'],s['b'])>10
          and all(left<p[0]<right and bottom<p[1]<top for p in (s['a'],s['b']))]
    if not axes:return []
    start=axes[0]['a'];points=[p for s in axes for p in (s['a'],s['b'])]
    if any(abs((p[0]-start[0])*u[1]-(p[1]-start[1])*u[0])>.25 for p in points):return []
    ends=[min(points,key=lambda p:sum(p[k]*u[k] for k in (0,1))),max(points,key=lambda p:sum(p[k]*u[k] for k in (0,1)))]
    if not axis_covers(page,*ends):return []
    for p in ends:
        degree=sum(min(math.dist(p,s['a']),math.dist(p,s['b']))<.25 for s in page['heavy_segments'])
        if degree!=1:return []
    point=ends[index]
    return [{'page_stem':stem,'x_mm':point[0],'y_mm':point[1],'score':-220,
        'evidence':[{'ref':pipe['ref'],'code':pipe['code'],'idf_line':pipe['line'],'score':-120,
            'cross_error_mm':0,'along_mm':math.dist(*ends),'method':'beihai-single-pipe-single-native-axis-free-end',
            'model_pipe_ports':pipe['ports'],'model_port_index':index,'native_axis_ends':ends,'axis_offsets':[s['offset'] for s in axes]}]}]
