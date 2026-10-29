"""Locate valve body centres; a HIT locator is not necessarily a body centre."""
import math
from pdms_weld_geometry import native_paths,projection


def crossing(a,b,c,d):
    def orient(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return orient(a,b,c)*orient(a,b,d)<-1e-7 and orient(c,d,a)*orient(c,d,b)<-1e-7


def native_valve_bodies(data):
    bodies=[]
    for path in native_paths(data):
        p=path['points'];shape=None
        if len(p)==6 and p[0]==p[-1] and len(set(p))==5 and crossing(p[1],p[2],p[3],p[4]):
            a=p[0];b=tuple((p[2][k]+p[3][k])/2 for k in (0,1))
            if math.dist(a,tuple((p[1][k]+p[4][k])/2 for k in (0,1)))>.15:continue
            shape='bowtie-valve'
        elif len(p)==10 and p[0]==p[9] and p[2]==p[7] and p[0]!=p[2]:
            a,b=p[0],p[2];shape='check-valve-disc-and-seat'
        if shape and 3<math.dist(a,b)<14:
            bodies.append({'a':a,'b':b,'center':tuple((a[k]+b[k])/2 for k in (0,1)),
                           'shape':shape,'offset':path['offsets'][0]})
    return bodies


def valve_body_center(component,hit,page):
    if not component or component['code']!=130 or len(component['ports'])!=2:
        raise ValueError('缺少阀门IDF两端，无法校验原图阀体中心')
    expected={'VBFL':'bowtie-valve','CKFL':'check-valve-disc-and-seat','CKSW':'check-valve-disc-and-seat'}.get(component['skey'])
    if not expected:raise ValueError('尚未适配阀门符号：'+component['skey'])
    a,b=component['ports'];dx,dy=projection([b[k]-a[k] for k in range(3)]);length=math.hypot(dx,dy)
    if length<.01:raise ValueError('阀门投影轴退化，无法校验阀体中心')
    u=(dx/length,dy/length);root=(hit['x_mm'],hit['y_mm']);options=[]
    for body in page.get('valve_bodies',[]):
        if body['shape']!=expected:continue
        v=(body['b'][0]-body['a'][0],body['b'][1]-body['a'][1]);span=math.hypot(*v)
        if abs(v[0]*u[1]-v[1]*u[0])/span>.035:continue
        # Select the downstream body terminal using the IDF direction. This
        # disambiguates adjacent inline valves sharing the same flange region.
        terminal=max((body['a'],body['b']),key=lambda p:p[0]*u[0]+p[1]*u[1])
        error=math.dist(root,terminal)
        if error<1.6:options.append((error,body))
    options.sort(key=lambda x:x[0])
    if not options:raise ValueError('HIT附近未找到与IDF方向一致的阀体两端，需人工定位阀体中心')
    if len(options)>1 and abs(options[0][0]-options[1][0])<.2:
        raise ValueError('HIT附近存在多个等价阀体，无法唯一确定阀体中心')
    return options[0][1]
