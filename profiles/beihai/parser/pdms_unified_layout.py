"""Adapt native PDMS geometry to Chengda's shared annotation layout solver."""
from __future__ import annotations

from dataclasses import replace
import itertools
import math
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

from project_paths import SHA_PARSER
if not SHA_PARSER.is_dir():
    raise FileNotFoundError(f'Chengda layout source is required: {SHA_PARSER}')
sys.path.insert(0,str(SHA_PARSER))
sys.path.insert(0,str(SHA_PARSER.parent/'workflow'))
from inject_sha_weld_callouts import (
    PointTarget,LayoutRegion,candidate_options,solve_page_layout,
    solve_page_layout_in_preferred_bands,candidate_conflict_reasons,
    nearest_segment_guide,leader_source_crossing_counts,leader_corridor_congestion,
    _build_segment_grid,_build_box_grid,_grid_indexes,_BEST_EFFORT_GRID_CACHE,
    WELD_CALLOUT_MARKER_RADIUS,WELD_CALLOUT_FONT_HEIGHT,
    CalloutPlacement,PlacementCandidate,marker_edge,boxes_overlap,segment_intersects_box,
    leader_clear_of_source,peer_root_direction_congestion,
)
from chengda_management_callouts import label_box,MANAGEMENT_FONT_FAMILY,SPOOL_FONT_HEIGHT
from sha_to_svg_prototype import SHEET_UNIT

from analyze_plt_bundle import svg_text
from pdms_weld_geometry import native_paths
from pdms_annotation_style import sheet_style
from pdms_text_metrics import text_metrics
from pdms_leader_policy import length_penalty,audit_length

UNITS_PER_MM=40.0


def obstacles(data):
    segments=[]
    left,bottom,right,top=data.get('drawing_bounds_mm',(181,22,data['width_mm'],data['height_mm']))
    for i,s in enumerate(data['segments']):
        a,b=s['a'],s['b']
        if max(a[0],b[0])<left*10 or max(a[1],b[1])<bottom*10 or min(a[0],b[0])>right*10 or min(a[1],b[1])>top*10:
            continue
        segments.append((a[0]*4/SHEET_UNIT,a[1]*4/SHEET_UNIT,
                         b[0]*4/SHEET_UNIT,b[1]*4/SHEET_UNIT,i,0))
    boxes=[]
    for path in native_paths(data):
        pts=path['points']
        left,right=min(p[0] for p in pts),max(p[0] for p in pts)
        bottom,top=min(p[1] for p in pts),max(p[1] for p in pts)
        w,h=right-left,top-bottom
        area=data.get('drawing_bounds_mm',(181,22,data['width_mm'],data['height_mm']))
        if left>area[0] and bottom>area[1] and right<area[2] and top<area[3] and .15<w<8 and .15<h<8 and len(pts)>=3:
            boxes.append((left*40,bottom*40,right*40,top*40))
    return segments,boxes


def dimensions(target,style):
    if target['kind']=='weld':
        r=style.weld_diameter_mm*40/2
        return r*2,r*2,r,'circle'
    if style.compact_frames:
        metrics=text_metrics(target['number'],style.font_height_mm)
        margin=style.text_padding_mm+(style.spool_inner_gap_mm if target['kind']=='spool' else 0)
        w=math.ceil((metrics['ink_width_mm']+2*margin)*10)/10*40
        h=math.ceil((metrics['ink_height_mm']+2*margin)*10)/10*40
        return w,h,max(w,h)/2,'rectangle'
    w,h=((style.spool_width_mm,style.spool_height_mm) if target['kind']=='spool'
         else (style.management_width_mm,style.management_height_mm))
    w,h=w*40,h*40
    return w,h,max(w,h)/2,'rectangle'


def layout(data,targets,heavy_segments,annotation_scale=2.0,font_height_mm=None,weld_diameter_mm=None,compact_frames=False):
    started=time.monotonic()
    style=sheet_style(data['width_mm'],data['height_mm'],annotation_scale,font_height_mm,weld_diameter_mm,compact_frames)
    segments,boxes=obstacles(data)
    region=LayoutRegion((5*40,5*40,(data['width_mm']-5)*40,(data['height_mm']-5)*40),
                        tuple(v*40 for v in data.get('drawing_bounds_mm',(184,24,data['width_mm']-6,data['height_mm']-6))),
                        'PDMS native plot frame and drawing/material division')
    points=[PointTarget(i+1,t['key'],t['x_mm']*40,t['y_mm']*40,1,
                        weld_number=t['number'],weld_type=t.get('weld_type',''))
            for i,t in enumerate(targets)]
    guides=[(s['a'][0]*40/SHEET_UNIT,s['a'][1]*40/SHEET_UNIT,
             s['b'][0]*40/SHEET_UNIT,s['b'][1]*40/SHEET_UNIT,i,0)
            for i,s in enumerate(heavy_segments)] or segments
    segment_grid=_build_segment_grid(segments)
    box_grid=_build_box_grid(boxes)
    options=[]
    inventory=[]
    for index,(point,target) in enumerate(zip(points,targets)):
        width,height,radius,shape=dimensions(target,style)
        normal=nearest_segment_guide(point,guides)[1]
        opts=candidate_options(point,segments,boxes,boxes,region,radius,
            60,normal,shape,
            max_candidates=160 if len(points)<=24 else 128,
            marker_width=None if shape=='circle' else width,
            marker_height=None if shape=='circle' else height,
            semantic_boxes=(),peer_points=tuple(points),best_effort=True,
            allow_fine_fallback=False,root_clearance=150)
        # The SHA fallback inventory starts at radius 700. Add the ordinary
        # 350--650-unit band for PDMS's dense short fittings, while retaining
        # the original compatibility solver, marker geometry and penalties.
        radial_inventory=((350,450,550,650,850,1000,1300,1700,2200,2800)
                          if style.annotation_scale>1 else (350,450,550,650,850,1000,1300,1700))
        for base_radial in radial_inventory:
            radial=base_radial*style.annotation_scale
            for degree in range(0,360,10):
                angle=math.radians(degree)
                cx=point.center_x+math.cos(angle)*radial
                cy=point.center_y+math.sin(angle)*radial
                gap=60
                box=(cx-width/2-gap,cy-height/2-gap,cx+width/2+gap,cy+height/2+gap)
                if box[0]<region.drawing[0] or box[1]<region.drawing[1] or box[2]>region.drawing[2] or box[3]>region.drawing[3]:
                    continue
                local_boxes=[boxes[k] for k in _grid_indexes(box_grid,box)]
                marker_overlap=any(boxes_overlap(box,b) for b in local_boxes)
                local_segments=[segments[k] for k in _grid_indexes(segment_grid,box)]
                geometry_overlap=any(segment_intersects_box(tuple(v*SHEET_UNIT for v in s[:4]),box) for s in local_segments)
                lx,ly=marker_edge(point.center_x,point.center_y,cx,cy,shape,radius,
                                  None if shape=='circle' else width,None if shape=='circle' else height)
                bounds=(min(point.center_x,lx),min(point.center_y,ly),max(point.center_x,lx),max(point.center_y,ly))
                leader_segments=[segments[k] for k in _grid_indexes(segment_grid,bounds)]
                leader_boxes=[boxes[k] for k in _grid_indexes(box_grid,bounds)]
                clear=leader_clear_of_source((point.center_x,point.center_y,lx,ly),leader_segments,leader_boxes,root_clearance=150)
                penalty=(2e6 if marker_overlap else 0)+(3e6 if geometry_overlap else 0)+(0 if clear else 4e6)
                penalty+=peer_root_direction_congestion(point,(math.cos(angle),math.sin(angle)),tuple(points))*140000
                opts.append(PlacementCandidate(CalloutPlacement(cx,cy,lx,ly,target['number'],
                                                radial+penalty,radius),box,clear))
        # Keep the source solver's spatially diverse inventory, then rank the
        # actual number of crossed native strokes and occupied pipe corridors.
        scored=[]
        for option in opts:
            p=option.placement
            leader=(point.center_x,point.center_y,p.leader_x,p.leader_y)
            bounds=(min(leader[0],leader[2])-50,min(leader[1],leader[3])-50,
                    max(leader[0],leader[2])+50,max(leader[1],leader[3])+50)
            local_segments=[segments[k] for k in _grid_indexes(segment_grid,bounds)]
            local_boxes=[boxes[k] for k in _grid_indexes(box_grid,bounds)]
            lines,texts=leader_source_crossing_counts(leader,local_segments,local_boxes,root_clearance=150)
            p.score+=lines*20000+texts*50000+leader_corridor_congestion(leader,local_segments)*18000
            actual_length=math.hypot(p.leader_x-point.center_x,p.leader_y-point.center_y)
            _,penalty=length_penalty(actual_length,target['kind'],style.sheet_scale)
            p.score+=penalty
            scored.append(replace(option,source_line_crossings=lines,source_text_crossings=texts))
        sorted_options=sorted(scored,key=lambda o:o.placement.score)
        # Retain both the best local positions and angular alternatives for
        # joint solving, so crowded peers can exchange lanes.
        cap=160 if len(points)<=24 else 128
        opts=[];seen=set();direction_counts={}
        for option in sorted_options:
            p=option.placement
            key=(round(p.center_x),round(p.center_y))
            sector=round(math.degrees(math.atan2(p.center_y-point.center_y,p.center_x-point.center_x))/15)
            if key in seen or (len(opts)>=cap//2 and direction_counts.get(sector,0)>=4):
                continue
            seen.add(key);direction_counts[sector]=direction_counts.get(sector,0)+1
            opts.append(option)
            if len(opts)>=cap:
                break
        if style.annotation_scale>1:
            # Large, fixed frames need options on several rings. Keeping only
            # the lowest-score nearby candidates can make the short-leader
            # band impossible even though blank space is available farther out.
            diverse={}
            for option in sorted_options:
                p=option.placement
                dx,dy=p.center_x-point.center_x,p.center_y-point.center_y
                key=(round(math.degrees(math.atan2(dy,dx))/30),int(math.hypot(dx,dy)//800))
                diverse.setdefault(key,option)
            by_ring={}
            for (sector,ring),option in diverse.items():
                by_ring.setdefault(ring,[]).append(option)
            for values in by_ring.values():values.sort(key=lambda o:o.placement.score)
            selected=list(sorted_options[:24]);seen={(round(o.placement.center_x),round(o.placement.center_y)) for o in selected}
            while len(selected)<cap and any(by_ring.values()):
                for ring in sorted(by_ring):
                    if not by_ring[ring]:continue
                    option=by_ring[ring].pop(0)
                    key=(round(option.placement.center_x),round(option.placement.center_y))
                    if key not in seen:selected.append(option);seen.add(key)
                    if len(selected)>=cap:break
            opts=sorted(selected,key=lambda o:o.placement.score)
        if not opts:
            raise ValueError(f'No placement candidates for {target["key"]}')
        options.append(opts)
        inventory.append(len(opts))
    audit={'solver_source':str(SHA_PARSER/'inject_sha_weld_callouts.py'),
           'scope':'weld-management-spool joint layout','units_per_mm':40,
           'annotation_style':style.as_dict(),
           'candidate_counts':inventory,'annotation_count':len(targets)}
    audit['leader_length_policy']={'enabled':True,'measurement':'root to visible frame edge',
        'stage_penalties':[0,12000,40000,120000,350000],
        'short_extensions_mm':[0,3.75,7.5,12.5],
        'long_extensions_mm':[0,6.25,16.25,35],
        'tail_penalty_per_mm':6000,'band_scale':'paper size only; independent of font magnification'}
    if not targets:
        return [],audit
    preferred=[tuple(v*style.sheet_scale for v in ((350,850) if t['kind']=='weld' else
               (450,1000) if t['kind']=='spool' else (400,900))) for t in targets]
    try:
        if style.annotation_scale>1:
            from pdms_large_frame_solver import solve
            placements,large_audit=solve(points,options)
            audit['large_frame_solver']=large_audit
            audit['leader_length_stage']='large-frame-wide-inventory'
        else:
            placements=solve_page_layout_in_preferred_bands(points,options,preferred,
                                                            node_limit=180000,layout_audit=audit)
        audit['layout_mode']='zero-annotation-conflict'
    except ValueError as exc:
        placements=solve_page_layout(points,options,node_limit=80000,allow_conflicts=True)
        audit['layout_mode']='best-effort'
        audit['strict_error']=str(exc)
    selected=[]
    for p,opts in zip(placements,options):
        selected.append(next(o for o in opts if o.placement is p or
                             (o.placement.center_x,o.placement.center_y)==(p.center_x,p.center_y)))
    conflicts=[]
    for i,j in itertools.combinations(range(len(points)),2):
        reasons=candidate_conflict_reasons(points[i],selected[i],points[j],selected[j])
        if reasons:
            conflicts.append({'first':targets[i]['key'],'second':targets[j]['key'],'reasons':reasons})
    audit['annotation_conflicts']=conflicts
    audit['source_line_crossings']=sum(o.source_line_crossings for o in selected)
    audit['source_text_crossings']=sum(o.source_text_crossings for o in selected)
    audit['elapsed_seconds']=round(time.monotonic()-started,2)
    result=[]
    for t,p,o in zip(targets,placements,selected):
        width,height,radius,shape=dimensions(t,style)
        result.append({'key':t['key'],'center_mm':[p.center_x/40,p.center_y/40],
                       'leader_end_mm':[p.leader_x/40,p.leader_y/40],
                       'marker_width_mm':width/40,'marker_height_mm':height/40,
                       'marker_shape':shape,'source_line_crossings':o.source_line_crossings,
                       'font_height_mm':style.font_height_mm,'stroke_width_mm':style.stroke_width_mm,
                       'spool_inner_gap_mm':style.spool_inner_gap_mm,
                       'compact_text_frame':style.compact_frames,
                       'leader_length':audit_length(math.hypot(p.leader_x-t['x_mm']*40,p.leader_y-t['y_mm']*40)/40,
                                                   t['kind'],style.sheet_scale),
                       'source_text_crossings':o.source_text_crossings,'score':p.score})
    lengths=sorted(p['leader_length']['length_mm'] for p in result)
    audit['leader_length_summary']={'min_mm':min(lengths),'median_mm':lengths[len(lengths)//2],
        'p90_mm':lengths[min(len(lengths)-1,int(len(lengths)*.9))],'max_mm':max(lengths),
        'stage_counts':{str(k):sum(p['leader_length']['penalty_stage']==k for p in result) for k in range(5)}}
    _BEST_EFFORT_GRID_CACHE.clear()
    return result,audit


def render_svg(data,targets,placements):
    root=ET.fromstring(svg_text(data))
    ns='{http://www.w3.org/2000/svg}'
    group=ET.SubElement(root,ns+'g',{'id':'pdms-unified-callouts'})
    by_key={p['key']:p for p in placements}
    page_height=data['height_mm']
    for t in targets:
        p=by_key[t['key']]
        cx,cy=p['center_mm']
        lx,ly=p['leader_end_mm']
        color='#ff0000' if t['kind'] in ('weld','spool') else '#0066ff'
        common={'stroke':color,'stroke-width':str(p['stroke_width_mm']),'fill':'none','data-key':t['key'],
                'data-kind':t['kind'],'data-number':t['number']}
        ET.SubElement(group,ns+'line',{'x1':str(t['x_mm']),'y1':str(page_height-t['y_mm']),
                                      'x2':str(lx),'y2':str(page_height-ly),**common})
        w,h=p['marker_width_mm'],p['marker_height_mm']
        if t['kind']=='weld':
            ET.SubElement(group,ns+'circle',{'cx':str(cx),'cy':str(page_height-cy),'r':str(w/2),**common})
        else:
            ET.SubElement(group,ns+'rect',{'x':str(cx-w/2),'y':str(page_height-cy-h/2),
                                          'width':str(w),'height':str(h),**common})
            if t['kind']=='spool':
                gap=p['spool_inner_gap_mm']
                ET.SubElement(group,ns+'rect',{'x':str(cx-w/2+gap),'y':str(page_height-cy-h/2+gap),
                                              'width':str(w-2*gap),'height':str(h-2*gap),**common})
        font_height=p['font_height_mm']
        text_x=cx
        text_y=page_height-cy
        if p.get('compact_text_frame'):
            metrics=text_metrics(t['number'],font_height)
            text_x-=metrics['ink_center_x_mm']-metrics['advance_mm']/2
            text_y+=metrics['ink_center_y_mm']
        text=ET.SubElement(group,ns+'text',{'x':str(text_x),'y':str(text_y),
                    'font-size':str(font_height),'font-family':MANAGEMENT_FONT_FAMILY,
                    'font-weight':'700','text-anchor':'middle',
                    'dominant-baseline':'alphabetic' if p.get('compact_text_frame') else 'central',
                    'fill':color,'data-key':t['key'],'data-kind':t['kind']})
        text.text=t['number']
    return ET.tostring(root,encoding='unicode')
