"""Independent deliverable checks plus a real-pipe additional-cut regression."""
import argparse
from collections import Counter
import itertools
import json
import math
from pathlib import Path
from project_paths import HISTORICAL_SAMPLES
import xml.etree.ElementTree as ET

import fitz

from audit_pdms_export import read_csv,model_components
from analyze_plt_bundle import decode_plt,read_hit
from pdms_weld_geometry import native_weld_dots,component_port_outlines,heavy_straight_segments
from render_complete_pdms import resolve_pipeline
from pdms_text_metrics import text_metrics
from pdms_leader_policy import audit_length,length_penalty,preferred_band


def intersects(a,b,c,d):
    def orient(p,q,r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return orient(a,b,c)*orient(a,b,d)<-1e-7 and orient(c,d,a)*orient(c,d,b)<-1e-7


def crosses_box(a,b,box):
    lower,upper=0.,1.
    for axis in (0,1):
        delta=b[axis]-a[axis]
        lo,hi=box[axis]+.01,box[axis+2]-.01
        if abs(delta)<1e-10:
            if a[axis]<lo or a[axis]>hi:return False
        else:
            t0,t1=sorted(((lo-a[axis])/delta,(hi-a[axis])/delta))
            lower,upper=max(lower,t0),min(upper,t1)
            if upper<lower:return False
    return True


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out-dir',type=Path,default=HISTORICAL_SAMPLES/'complete_output')
    args=ap.parse_args()
    base=HISTORICAL_SAMPLES
    out=args.out_dir
    mapping=json.loads((out/'annotation_mapping.json').read_text(encoding='utf-8'))
    targets=mapping['targets']
    actual=Counter(t['kind'] for t in targets)
    assert actual==Counter({'weld':258,'valve':31,'flange':66,'support':4,'spool':73}),actual
    assert len({t['key'] for t in targets})==len(targets)
    source_welds,_=read_csv(base/'PDMS_Export/焊口表.csv')
    expected={(w['管线号'],w['焊点编号']) for w in source_welds}
    assert {(t['pipeline'],t['number']) for t in targets if t['kind']=='weld'}==expected
    assert not mapping['unresolved_welds']
    pdf=fitz.open(out/'PDMS_完整标注.pdf')
    assert len(pdf)==24
    report={'counts':dict(actual),'pages':[],'review_welds':mapping['review_welds']}
    weld_sizes_by_digits={}
    files=sorted(out.glob('*_layout.json'))
    assert len(files)==24
    ns='{http://www.w3.org/2000/svg}'
    for i,path in enumerate(files):
        stem=path.name.removesuffix('_layout.json')
        d=json.loads(path.read_text(encoding='utf-8'))
        ts=d['targets']; ps=d['placements']
        style=d['audit'].get('annotation_style')
        expected_fonts=({style['font_height_mm']} if style else {1.6,2.2})
        assert len(ts)==len(ps)
        root=ET.parse(out/(stem+'.svg')).getroot()
        group=next(g for g in root.iter() if g.get('id')=='pdms-unified-callouts')
        texts=[e for e in group if e.tag==ns+'text']
        assert Counter(e.text for e in texts)==Counter(t['number'] for t in ts)
        circles=[e for e in group if e.tag==ns+'circle']
        assert len(circles)==sum(t['kind']=='weld' for t in ts)
        assert not [e for e in group if e.tag==ns+'ellipse']
        for el in group:
            if el.tag==ns+'text':
                expected_height=(style['font_height_mm'] if style else (1.6 if el.get('data-kind')=='spool' else 2.2))
                assert abs(float(el.get('font-size'))-expected_height)<1e-6
            else:
                assert abs(float(el.get('stroke-width'))-.2)<1e-6
        # Separate physical-box check, without using the solver's candidate
        # margins or conflict routines.
        boxes=[];leaders=[]
        for t,p in zip(ts,ps):
            cx,cy=p['center_mm'];w,h=p['marker_width_mm'],p['marker_height_mm']
            boxes.append((cx-w/2,cy-h/2,cx+w/2,cy+h/2))
            leaders.append(((t['x_mm'],t['y_mm']),tuple(p['leader_end_mm'])))
        overlaps=[];crosses=[];frame_crosses=[]
        for a,b in itertools.combinations(range(len(ts)),2):
            ba,bb=boxes[a],boxes[b]
            if min(ba[2],bb[2])-max(ba[0],bb[0])>1e-6 and min(ba[3],bb[3])-max(ba[1],bb[1])>1e-6:
                overlaps.append((ts[a]['key'],ts[b]['key']))
            if math.dist(leaders[a][0],leaders[b][0])>.025 and intersects(*leaders[a],*leaders[b]):
                crosses.append((ts[a]['key'],ts[b]['key']))
            if crosses_box(*leaders[a],bb) or crosses_box(*leaders[b],ba):
                frame_crosses.append((ts[a]['key'],ts[b]['key']))
        assert not overlaps,(stem,overlaps)
        assert not crosses,(stem,crosses)
        assert not frame_crosses,(stem,frame_crosses)
        # Original PLT text is strokes: searchable PDF strings should contain
        # exactly the added annotation numbers, including repeated numbers.
        strings=Counter(pdf[i].get_text().split())
        assert strings==Counter(t['number'] for t in ts),(stem,strings,Counter(t['number'] for t in ts))
        assert all('SimHei' in font[3] for font in pdf[i].get_fonts()),stem
        colors=Counter()
        for block in pdf[i].get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    assert 'SimHei' in span['font'],span
                    assert min(abs(span['size']-mm*72/25.4) for mm in expected_fonts)<.005,span
                    colors[span['color']]+=len(span['text'].split())
        assert colors[0xff0000]==sum(t['kind'] in ('weld','spool') for t in ts),(stem,colors)
        assert colors[0x0066ff]==sum(t['kind'] not in ('weld','spool') for t in ts),(stem,colors)
        if style:
            sizes={}
            for t,p in zip(ts,ps):
                family='weld' if t['kind']=='weld' else 'spool' if t['kind']=='spool' else 'management'
                sizes.setdefault(family,set()).add((p['marker_width_mm'],p['marker_height_mm']))
                if family=='weld':
                    assert abs(p['marker_width_mm']-style['weld_diameter_mm'])<1e-6
                    weld_sizes_by_digits.setdefault(len(t['number']),set()).add(round(p['marker_width_mm'],6))
                if style.get('compact_frames'):
                    metrics=text_metrics(t['number'],style['font_height_mm'])
                    padding=style['text_padding_mm']+(style['spool_inner_gap_mm'] if family=='spool' else 0)
                    if family!='weld':
                        assert metrics['ink_width_mm']+2*padding-1e-6<=p['marker_width_mm']<metrics['ink_width_mm']+2*padding+.101
                        assert metrics['ink_height_mm']+2*padding-1e-6<=p['marker_height_mm']<metrics['ink_height_mm']+2*padding+.101
                if p.get('leader_length'):
                    measured=math.dist((t['x_mm'],t['y_mm']),tuple(p['leader_end_mm']))
                    expected_length=audit_length(measured,t['kind'],style['sheet_scale'])
                    assert abs(expected_length['length_mm']-p['leader_length']['length_mm'])<1e-6
                    assert expected_length['penalty_stage']==p['leader_length']['penalty_stage']
                    assert abs(expected_length['penalty_score']-p['leader_length']['penalty_score'])<1e-6
            assert all(len(v)==1 for k,v in sizes.items() if k=='weld' or not style.get('compact_frames')),(stem,sizes)
        report['pages'].append({'page_stem':stem,'labels':len(ts),'circle_welds':len(circles),
                                'physical_box_overlaps':len(overlaps),'leader_crossings':len(crosses),
                                'leaders_crossing_other_frames':len(frame_crosses)})
    pdf.close()
    if weld_sizes_by_digits:
        assert len(set.union(*weld_sizes_by_digits.values()))==1,weld_sizes_by_digits
        report['fixed_weld_diameter_mm_by_digits']={str(k):sorted(v) for k,v in weld_sizes_by_digits.items()}
    # Additional weld inside an actual pipe, absent from the input IDF ports.
    ex=base/'PDMS_Export/export'
    data,components=model_components(ex/'100-B-8.idf')
    pages={}
    for p in ex.glob('100-B-8_Sht_*.plt'):
        d=decode_plt(p);o,v=component_port_outlines(d)
        pages[p.stem]={'hits':read_hit(p.with_suffix('.hit')),'dots':native_weld_dots(d),
                       'port_outlines':o,'vertices':v,'heavy_segments':heavy_straight_segments(d)}
    rows=[w for w in source_welds if w['管线号']=='100-B-8']
    extra=dict(rows[0])
    extra.update({'焊点编号':'TEST-CUT','焊点位置':'9630,8855.79,5766.55',
                  '管段编号':'','焊点类型':'F','_row':999999})
    resolved=resolve_pipeline(rows+[extra],{'data':data,'components':components},pages)
    cut=next(w for w in resolved if w['number']=='TEST-CUT')
    assert cut['mapping_method']=='straight-pipe-extra-cut-interpolation',cut
    assert math.dist((cut['x_mm'],cut['y_mm']),(510,212.4))<.01,cut
    report['additional_cut_regression']={'passed':True,'anchor_mm':[cut['x_mm'],cut['y_mm']],
                                         'method':cut['mapping_method'],'synthetic_row_in_production_pdf':False}
    scale=420.2/297
    lower,upper=preferred_band('weld',scale)
    long_costs=[length_penalty(upper+delta*40,'weld',scale) for delta in (0,5,10,25,40)]
    short_costs=[length_penalty(lower-delta*40,'weld',scale) for delta in (0,1,5,10)]
    assert [stage for stage,cost in long_costs]==[0,1,2,3,4],long_costs
    assert [stage for stage,cost in short_costs]==[0,1,2,3],short_costs
    assert all(a[1]<b[1] for a,b in zip(long_costs,long_costs[1:]))
    assert all(a[1]<b[1] for a,b in zip(short_costs,short_costs[1:]))
    report['leader_length_policy_regression']={'passed':True,'long_costs':long_costs,'short_costs':short_costs}
    report['passed']=True
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Verified: 24 pages, 258 welds, 101 management labels, 73 spool labels; additional-cut regression passed')


if __name__=='__main__':
    main()
