"""Independent, process-safe layout and PDF work for one physical sheet."""
from collections import Counter
import itertools
import json
import math
import os
from pathlib import Path
import time
import fitz
import psutil
from analyze_plt_bundle import decode_plt
from pdms_weld_geometry import heavy_straight_segments
from pdms_unified_layout import layout,render_svg
from export_complete_pdms_pdf import export_pdf
from verify_complete_pdms import crosses_box,intersects


def physical_conflicts(targets,placements):
    boxes=[];leaders=[];conflicts=[]
    for t,p in zip(targets,placements):
        x,y=p['center_mm'];w,h=p['marker_width_mm'],p['marker_height_mm']
        boxes.append((x-w/2,y-h/2,x+w/2,y+h/2))
        leaders.append(((t['x_mm'],t['y_mm']),tuple(p['leader_end_mm'])))
    for a,b in itertools.combinations(range(len(targets)),2):
        ba,bb=boxes[a],boxes[b];reasons=[]
        if min(ba[2],bb[2])-max(ba[0],bb[0])>1e-6 and min(ba[3],bb[3])-max(ba[1],bb[1])>1e-6:reasons.append('边框重叠')
        if math.dist(leaders[a][0],leaders[b][0])>.025 and intersects(*leaders[a],*leaders[b]):reasons.append('引线交叉')
        if crosses_box(*leaders[a],bb) or crosses_box(*leaders[b],ba):reasons.append('引线穿过其他编号框')
        if reasons:conflicts.append({'first':targets[a]['key'],'second':targets[b]['key'],'reasons':reasons})
    return conflicts


def render_page_job(job):
    started=time.monotonic();cpu_started=time.process_time()
    path=Path(job['plt_path']);stem=path.stem;config=job['config'];targets=job['targets']
    work=Path(job['stage'])/stem;work.mkdir(parents=True,exist_ok=True)
    data=decode_plt(path);data['drawing_bounds_mm']=config['drawing_bounds_mm']
    heavy=heavy_straight_segments(data);decode_seconds=time.monotonic()-started
    placement_started=time.monotonic()
    placed,audit=layout(data,targets,heavy,2.,config['font_height_mm'],config['weld_diameter_mm'],config['compact_frames'])
    conflicts=audit.get('annotation_conflicts',[])+physical_conflicts(targets,placed)
    layout_seconds=time.monotonic()-placement_started
    (work/(stem+'_layout.json')).write_text(json.dumps({'targets':targets,'placements':placed,'audit':audit},ensure_ascii=False),encoding='utf-8')
    (work/(stem+'.svg')).write_text(render_svg(data,targets,placed),encoding='utf-8')
    export_started=time.monotonic()
    export_pdf(work,single_pages=True,pdf_out=Path(job['stage'])/'pdfs',quiet=True)
    with fitz.open(Path(job['stage'])/'pdfs'/(stem+'.pdf')) as pdf:
        okay=len(pdf)==1 and Counter(pdf[0].get_text().split())==Counter(str(t['number']) for t in targets)
        okay=okay and abs(pdf[0].rect.width/72*25.4-594.2)<.1 and abs(pdf[0].rect.height/72*25.4-420.2)<.1
    export_seconds=time.monotonic()-export_started
    memory=psutil.Process().memory_info()
    return {'stem':stem,'pid':os.getpid(),'elapsed_seconds':round(time.monotonic()-started,3),
            'cpu_seconds':round(time.process_time()-cpu_started,3),'decode_seconds':round(decode_seconds,3),
            'layout_seconds':round(layout_seconds,3),'export_seconds':round(export_seconds,3),
            'process_rss_bytes':memory.rss,'process_peak_rss_bytes':getattr(memory,'peak_wset',memory.rss),
            'process_private_bytes':getattr(memory,'private',memory.rss),
            'mode':audit.get('layout_mode','无标注原图'),'conflicts':conflicts,'pdf_verified':okay,
            'counts':dict(Counter(t['kind'] for t in targets))}
