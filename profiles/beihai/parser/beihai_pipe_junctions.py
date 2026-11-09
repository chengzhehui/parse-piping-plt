"""Locate table welds at virtual boundaries between two collinear pipes."""
import math
import re


def resolve_pipe_junctions(mapped,unresolved,model,pages,chain_anchors,axis_covers):
    for target in list(unresolved):
        q=target['coordinate_mm']
        near=[c for c in model['components'] if c['code'] not in (110,115,120,150)
              and any(math.dist(q,p)<.11 for p in c['ports'])]
        if len(near)!=2 or any(c['code'] not in (100,101) or len(c['ports'])!=2 for c in near):continue
        if any(h['ref'] in {c['ref'] for c in near} and re.match(r'^BEND\b',h['name'])
               for page in pages.values() for h in page['hits']):continue
        others=[max(c['ports'],key=lambda p:math.dist(q,p)) for c in near]
        vectors=[[p[k]-q[k] for k in range(3)] for p in others]
        lengths=[math.sqrt(sum(v*v for v in d)) for d in vectors]
        if min(lengths)<.1 or sum(vectors[0][k]*vectors[1][k] for k in range(3))/(lengths[0]*lengths[1])>-.99999:continue
        controls=[chain_anchors(q,other,c,model,pages) for other,c in zip(others,near)];choices=[]
        for ca in controls[0]:
            for cb in controls[1]:
                if ca['page_stem']!=cb['page_stem']:continue
                a=ca.get('model_anchor_mm',others[0]);b=cb.get('model_anchor_mm',others[1]);v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
                fraction=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
                if not 0<fraction<1 or math.dist(q,[a[k]+fraction*v[k] for k in range(3)])>.11:continue
                pa=(ca['x_mm'],ca['y_mm']);pb=(cb['x_mm'],cb['y_mm']);length=math.dist(pa,pb)
                if length<2:continue
                page=pages[ca['page_stem']];breaks=[]
                if not axis_covers(page,pa,pb,breaks):continue
                u=[(pb[k]-pa[k])/length for k in (0,1)];blocked=False
                for hit in page['hits']:
                    if not re.match(r'^(BEND|ELBOW|TEE|VALVE|FLANGE|REDUCER|COUPLING|PCOMPONENT|OLET|FBLIND)\b',hit['name']):continue
                    d=[hit['x_mm']-pa[0],hit['y_mm']-pa[1]];distance=sum(d[k]*u[k] for k in (0,1))
                    if .5<distance<length-.5 and abs(d[0]*u[1]-d[1]*u[0])<.5:blocked=True
                if blocked:continue
                point=[pa[k]+fraction*(pb[k]-pa[k]) for k in (0,1)]
                choices.append({'page_stem':ca['page_stem'],'point':point,'fraction':fraction,'terminals':[ca,cb],'native_axis_breaks':breaks})
        unique={(c['page_stem'],round(c['point'][0],2),round(c['point'][1],2)):c for c in choices}
        if len(unique)!=1:continue
        result=next(iter(unique.values()));point=result['point']
        if any(t['page_stem']==result['page_stem'] and math.dist(point,[t['x_mm'],t['y_mm']])<.25 for t in mapped):continue
        target.update(page_stem=result['page_stem'],x_mm=point[0],y_mm=point[1],mapping_method='beihai-collinear-pipe-junction-interpolation',
            mapping_evidence={'pipe_refs':[c['ref'] for c in near],'pipe_idf_lines':[c['line'] for c in near],**result},
            review_notes=[{'reason':'共线管子虚拟分界按独立两端及模型长度插值；等轴图非比例绘制，请核对预制分段位置。'}])
        mapped.append(target);unresolved.remove(target)
