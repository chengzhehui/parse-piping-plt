"""Batch evidence audit and management labels from PDMS PLT/HIT + EP3D CSV.

The management-only execution deliberately does not open IDF, DXF or weld CSV.
No weld callout is drawn without a verified paper-space interface.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
from project_paths import HISTORICAL_SAMPLES
import re
import xml.etree.ElementTree as ET

from analyze_plt_bundle import decode_plt, read_hit, read_idf, svg_text


TABLES=[('valve','阀门表.csv','阀门号'),('flange','法兰表.csv','法兰编号'),('support','支架表.csv','支架编号')]


def read_csv(path):
    raw=path.read_bytes()
    try:
        text=raw.decode('utf-8-sig')
        encoding='utf-8-sig'
    except UnicodeDecodeError:
        text=raw.decode('gb18030')
        encoding='gb18030'
    parsed=list(csv.reader(text.splitlines()))
    header=[h.strip() for h in parsed[0]]
    result=[]
    for n,values in enumerate(parsed[1:],2):
        if not any(v.strip() for v in values):
            continue
        r=dict(zip(header,(v.strip() for v in values)))
        r['_row']=n
        r['_extra']=values[len(header):]
        r['_missing_columns']=max(0,len(header)-len(values))
        result.append(r)
    return result,{'encoding':encoding,'columns':header,'rows':len(result),
                   'rows_with_extra_fields':sum(bool(r['_extra']) for r in result)}


def coordinate(text):
    values=re.findall(r'[+-]?\d+(?:\.\d+)?',text)
    return tuple(map(float,values)) if len(values)==3 else None


def model_components(path):
    data=read_idf(path)
    result=[]
    current=None
    seen_metadata=False
    # These continuation records belong to the preceding multi-port component.
    continuations={36,41,42,46,47,91,92,93,94,96}
    starts={35,40,45,50,55,60,65,70,75,80,85,90,95,100,101,102,105,107,110,115,120,125,126,130,135,140,145,150}
    for r in data['logical_records']:
        code=r['code']
        if code<0:
            seen_metadata=True
        if not seen_metadata:
            continue
        if code==999:
            break
        if code in starts or code in continuations:
            values=re.findall(r'[+-]?\d+(?:\.\d+)?',r['text'].split(',')[0])
            if len(values)<8:
                continue
            a=tuple(float(v)/100 for v in values[:3])
            b=tuple(float(v)/100 for v in values[3:6])
            if code in starts:
                fields=r['text'].split(',')
                current={'code':code,'line':r['line'],'ref':None,'segments':[], 'raw_points':[],
                         'skey':fields[-2].strip() if len(fields)>=5 else ''}
                result.append(current)
            elif code in continuations:
                parent_codes=({35} if code==36 else {40} if code in (41,42)
                              else {45} if code in (46,47) else {95} if code==96 else {90})
                # A branch leg can be serialized after an entire other branch;
                # attach it to the matching centre, not the last read component.
                parents=[c for c in result if c['code'] in parent_codes and
                         c['segments'] and math.dist(c['segments'][0]['b'],a)<=.1]
                if len(parents)==1:
                    current=parents[0]
            if current is not None:
                current['raw_points'].extend([a,b])
                current['segments'].append({'code':code,'a':a,'b':b})
        if code==-39 and current is not None:
            current['ref']=r['text'].strip()
    for c in result:
        pts=c['raw_points']
        if c['code'] in (35,95):
            ports=[pts[0],pts[-1]]
        elif c['code'] in (40,45):
            ports=[s['b'] if s['code'] in continuations else s['a'] for s in c['segments']]
        elif c['code']==150:
            ports=[pts[0]]
        elif c['code']==115:
            ports=[]
        else:
            ports=[pts[0],pts[1]]
        c['ports']=list(dict.fromkeys(ports))
    return data,result


def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def annotate(data,targets):
    root=ET.fromstring(svg_text(data))
    ns='{http://www.w3.org/2000/svg}'
    group=ET.SubElement(root,ns+'g',{'data-layer':'pdms-management-labels','font-family':'Arial, sans-serif'})
    used=[]
    placements=[]
    height=data['height_mm']
    width=data['width_mm']
    # Coarse sampling of source linework is sufficient for label avoidance;
    # it is never used to change a target's independently established anchor.
    occupancy=[]
    for s in data['segments']:
        a=(s['a'][0]/10,height-s['a'][1]/10)
        b=(s['b'][0]/10,height-s['b'][1]/10)
        occupancy.extend((a,b,((a[0]+b[0])/2,(a[1]+b[1])/2)))
    for t in sorted(targets,key=lambda t:(-t['y_mm'],t['x_mm'],t['kind'])):
        x,y=t['x_mm'],height-t['y_mm']
        bw=max(7,len(t['number'])*2+2)
        bh=4.5
        choices=[]
        for radius in (9,15,22,30,40):
            for dx,dy in ((1,-1),(-1,-1),(1,1),(-1,1),(1,0),(-1,0),(0,-1),(0,1)):
                cx,cy=x+dx*radius,y+dy*radius
                box=(cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2)
                if box[0]<3 or box[1]<3 or box[2]>width-3 or box[3]>height-3:
                    continue
                collisions=sum(overlap(box,b)>0 for b in used)
                blocked=sum(box[0]-1<px<box[2]+1 and box[1]-1<py<box[3]+1 for px,py in occupancy)
                score=collisions*100000+blocked*8+math.hypot(cx-x,cy-y)
                choices.append((score,box))
        if not choices:
            raise ValueError('No valid callout position')
        _,box=min(choices)
        used.append(box)
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        dx,dy=x-cx,y-cy
        scale=min((bw/2)/abs(dx) if dx else float('inf'),(bh/2)/abs(dy) if dy else float('inf'))
        edge=(cx+scale*dx,cy+scale*dy)
        color='#ff0000' if t['kind']=='weld' else '#0066ff'
        common={'stroke':color,'stroke-width':'0.22','fill':'none',
                'data-kind':t['kind'],'data-uci':t['ref'],'data-source-row':str(t['source_row'])}
        ET.SubElement(group,ns+'line',{'x1':str(x),'y1':str(y),'x2':str(edge[0]),'y2':str(edge[1]),**common})
        ET.SubElement(group,ns+'circle',{'cx':str(x),'cy':str(y),'r':'0.45',**common})
        if t['kind']=='weld':
            ET.SubElement(group,ns+'ellipse',{'cx':str(cx),'cy':str(cy),'rx':str(bw/2),'ry':str(bh/2),**common})
        else:
            ET.SubElement(group,ns+'rect',{'x':str(box[0]),'y':str(box[1]),'width':str(bw),'height':str(bh),**common})
        el=ET.SubElement(group,ns+'text',{'x':str(cx),'y':str(cy+.9),'font-size':'2.8','text-anchor':'middle','fill':color})
        el.text=t['number']
        placements.append({'key':t['key'],'anchor_svg_mm':[x,y],'box_mm':box})
    return ET.tostring(root,encoding='unicode'),placements


def audit_welds(base,hit_index):
    welds,metadata=read_csv(base/'焊口表.csv')
    grouped=defaultdict(list)
    for w in welds:
        grouped[w['管线号']].append(w)
    models={}
    for p in (base/'export').glob('*.idf'):
        if p.stem=='transfer':
            continue
        d,c=model_components(p)
        models[p.stem]={'data':d,'components':c}
    records=[]
    offset_scores={}
    for line,rows in grouped.items():
        components=models[line]['components']
        ports=[(pt,c) for c in components for pt in c['ports']]
        scores=[]
        for dz in (0,1000,-1000):
            distances=[]
            for w in rows:
                point=coordinate(w['焊点位置'])
                if point:
                    query=(point[0],point[1],point[2]-dz)
                    distances.append(min(math.dist(query,p) for p,c in ports))
            scores.append({'z_added_to_idf_mm':dz,'within_0_1_mm':sum(d<=.1 for d in distances),
                           'within_1_mm':sum(d<=1 for d in distances),
                           'max_nearest_port_distance_mm':max(distances,default=None)})
        offset_scores[line]=scores
        # Offset candidates are evaluated independently for every weld. This is
        # an audit hypothesis, never an automatically accepted frame transform.
        for w in rows:
            point=coordinate(w['焊点位置'])
            hypotheses=[]
            for dz in (0,1000,-1000):
                query=(point[0],point[1],point[2]-dz)
                near=[{'ref':c['ref'],'code':c['code'],'idf_line':c['line'],
                       'distance_mm':math.dist(query,p),'port_mm':p,
                       'hit_pages':[h['page_stem'] for h in hit_index.get((line,c['ref']),[])]}
                      for p,c in ports if math.dist(query,p)<=1]
                if near:
                    hypotheses.append({'z_added_to_idf_mm':dz,'model_query_mm':query,'near_ports':near})
            records.append({'source_row':w['_row'],'pipeline':line,'number':w['焊点编号'],
                            'table_page':w['页码'],'weld_type':w['焊点类型'],'coordinate_mm':point,
                            'hypotheses':hypotheses,'status':'model-port-candidate-only' if hypotheses else 'no-port-within-1mm',
                            'paper_anchor':None})
    return {'table_metadata':metadata,'offset_hypotheses_by_pipeline':offset_scores,'records':records,
            'summary':dict(Counter(r['status'] for r in records)),
            'note':'No weld paper anchors have been validated; coordinate offsets are hypotheses only.'},models


def audit_dxf(base):
    import ezdxf
    results=[]
    for p in sorted((base/'export').glob('*.dxf')):
        doc=ezdxf.readfile(p)
        entities=list(doc.modelspace())
        results.append({'file':p.name,'types':dict(Counter(e.dxftype() for e in entities)),
                        'entities_with_xdata':sum(e.xdata is not None for e in entities),
                        'appids':[a.dxf.name for a in doc.appids],
                        'blocks':[(b.name,len(b)) for b in doc.blocks],
                        'text_count':sum(e.dxftype()=='TEXT' for e in entities)})
    return results


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-dir',type=Path,default=HISTORICAL_SAMPLES/'PDMS_Export')
    ap.add_argument('--out-dir',type=Path,default=HISTORICAL_SAMPLES/'bundle_analysis')
    ap.add_argument('--management-only',action='store_true')
    args=ap.parse_args()
    out=args.out_dir
    out.mkdir(parents=True,exist_ok=True)
    pages={}
    hit_index=defaultdict(list)
    for p in sorted((args.input_dir/'export').glob('*.plt')):
        line,page=p.stem.rsplit('_Sht_',1)
        data=decode_plt(p)
        hits=read_hit(p.with_suffix('.hit'))
        pages[p.stem]={'pipeline':line,'page':int(page),'data':data,'hits':hits,'targets':[]}
        for h in hits:
            hit_index[(line,h['ref'])].append(h|{'page_stem':p.stem,'page':int(page)})
    tables={}
    targets=[]
    for kind,name,column in TABLES:
        rows,meta=read_csv(args.input_dir/name)
        tables[kind]=meta
        for r in rows:
            refs=[v.strip() for v in re.split('[;；]',r['UCI']) if v.strip()]
            matches=[h for ref in refs for h in hit_index.get((r['管线号'],ref),[])]
            target={'key':f"{r['管线号']}:{kind}:{r[column]}:{r['_row']}",
                    'kind':kind,'pipeline':r['管线号'],'number':r[column],'source_file':name,
                    'source_row':r['_row'],'table_page':r['页码'],'refs':refs,'match_count':len(matches)}
            if len(refs)==1 and len(matches)==1:
                h=matches[0]
                target|={'status':'unique-hit-reference','ref':h['ref'],'page_stem':h['page_stem'],
                         'page':h['page'],'x_mm':h['x_mm'],'y_mm':h['y_mm']}
                pages[h['page_stem']]['targets'].append(target)
            else:
                target['status']='unresolved-or-multiple'
            targets.append(target)
    import fitz
    combined=fitz.open()
    for stem,p in pages.items():
        svg,placements=annotate(p['data'],p['targets'])
        (out/f'{stem}_management.svg').write_text(svg,encoding='utf-8')
        p['placements']=placements
        with fitz.open('svg',svg.encode('utf-8')) as doc:
            doc[0].get_pixmap(matrix=fitz.Matrix(.65,.65)).save(str(out/f'{stem}_management.png'))
            with fitz.open('pdf',doc.convert_to_pdf()) as pdf:
                combined.insert_pdf(pdf)
    combined.save(out/'PDMS_management_labels.pdf',deflate=True)
    combined.close()
    evidence={'input_dir':str(args.input_dir),'management_only':args.management_only,'tables':tables,
              'targets':targets,'summary':{'pages':len(pages),'pipelines':len(set(p['pipeline'] for p in pages.values())),
              'hit_rows':sum(len(p['hits']) for p in pages.values()),'management_status':dict(Counter(t['status'] for t in targets)),
              'management_by_kind':dict(Counter(t['kind'] for t in targets))},
              'pages':[{k:v for k,v in p.items() if k not in ('data','targets')}|{'stem':stem,
                       'segment_count':len(p['data']['segments']),'management_targets':len(p['targets'])}
                       for stem,p in pages.items()]}
    if not args.management_only:
        weld_audit,models=audit_welds(args.input_dir,hit_index)
        (out/'weld_model_audit.json').write_text(json.dumps(weld_audit,ensure_ascii=False,indent=2),encoding='utf-8')
        evidence['weld_summary']=weld_audit['summary']
        evidence['dxf_audit']=audit_dxf(args.input_dir)
        supports,_=read_csv(args.input_dir/'支架表.csv')
        checks=[]
        for s in supports:
            loc=models[s['管线号']]['data']['locations'].get(s['UCI'])
            table_xyz=coordinate(s['支架坐标'])
            checks.append({'pipeline':s['管线号'],'ref':s['UCI'],'number':s['支架编号'],
                           'table_xyz':table_xyz,'idf_location':loc,
                           'delta_mm':[table_xyz[i]-loc['xyz_mm'][i] for i in range(3)] if loc else None})
        evidence['support_coordinate_checks']=checks
    (out/'bundle_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'management_mapping.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['pipeline','kind','number','source_row','table_page','status','ref','page','page_stem','x_mm','y_mm']
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(targets)
    print(json.dumps(evidence['summary']|{'weld_summary':evidence.get('weld_summary')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
