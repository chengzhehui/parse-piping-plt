"""Export existing laid-out SVGs with embedded SimHei, without rerunning layout."""
import argparse
import json
from pathlib import Path
from project_paths import HISTORICAL_SAMPLES
import xml.etree.ElementTree as ET

import fitz
from fontTools.ttLib import TTFont
from pdms_text_metrics import text_metrics

MM_TO_PT=72/25.4


def export_pdf(out,png=False,font_file=Path('C:/Windows/Fonts/simhei.ttf'),single_pages=False,pdf_out=None,quiet=False):
    if not font_file.is_file():
        raise FileNotFoundError(f'Provide the Chengda SimHei font with --font-file: {font_file}')
    font=fitz.Font(fontfile=str(font_file))
    tt=TTFont(str(font_file),lazy=True)
    cmap=tt.getBestCmap()
    upem=tt['head'].unitsPerEm
    glyf=tt['glyf']
    bounds={}
    def text_y_center(text):
        if text not in bounds:
            glyphs=[glyf[cmap[ord(c)]] for c in text if ord(c) in cmap]
            ys=[(getattr(g,'yMin',0),getattr(g,'yMax',upem)) for g in glyphs]
            bounds[text]=(min(y[0] for y in ys)+max(y[1] for y in ys))/2/upem
        return bounds[text]
    destination=Path(pdf_out) if pdf_out else out
    destination.mkdir(parents=True,exist_ok=True)
    complete=fitz.open()
    lines={}
    bookmarks=[]
    ns='{http://www.w3.org/2000/svg}'
    files=sorted(out.glob('*_layout.json'))
    for path in files:
        stem=path.name.removesuffix('_layout.json')
        data=json.loads(path.read_text(encoding='utf-8'))
        targets=data['targets'];placements={p['key']:p for p in data['placements']}
        root=ET.parse(out/(stem+'.svg')).getroot()
        page_height=float(root.get('viewBox').split()[3])
        group=next(g for g in root.iter() if g.get('id')=='pdms-unified-callouts')
        for child in list(group):
            if child.tag==ns+'text':
                group.remove(child)
        native=ET.tostring(root,encoding='utf-8')
        with fitz.open('svg',native) as svg:
            pdf=fitz.open('pdf',svg.convert_to_pdf())
        page=pdf[0]
        for target in targets:
            p=placements[target['key']]
            cx,cy=p['center_mm']
            height=p.get('font_height_mm',1.6 if target['kind']=='spool' else 2.2)
            size=height*MM_TO_PT
            text=target['number']
            if p.get('compact_text_frame'):
                metrics=text_metrics(text,height,str(font_file))
                x=(cx-metrics['ink_center_x_mm'])*MM_TO_PT
                baseline=(page_height-cy+metrics['ink_center_y_mm'])*MM_TO_PT
            else:
                x=cx*MM_TO_PT-font.text_length(text,fontsize=size)/2
                baseline=(page_height-cy)*MM_TO_PT+text_y_center(text)*size
            color=(1,0,0) if target['kind'] in ('weld','spool') else (0,.4,1)
            page.insert_text((x,baseline),text,fontname='PDMS_SimHei',fontfile=str(font_file),
                             fontsize=size,color=color,render_mode=0,overlay=True)
        pdf.subset_fonts()
        if single_pages:
            pdf.save(destination/(stem+'.pdf'),deflate=True)
        if png:
            page.get_pixmap(matrix=fitz.Matrix(.9,.9)).save(str(out/(stem+'.png')))
        line=stem.rsplit('_Sht_',1)[0]
        if not single_pages and line not in lines:
            lines[line]=fitz.open()
            bookmarks.append([1,line,len(complete)+1])
        if not single_pages:
            complete.insert_pdf(pdf)
            lines[line].insert_pdf(pdf)
        pdf.close()
    if not single_pages:
        complete.set_toc(bookmarks)
        complete.save(out/'PDMS_完整标注.pdf',deflate=True)
    complete.close()
    for line,doc in lines.items():
        doc.save(out/(line+'_完整标注.pdf'),deflate=True)
        doc.close()
    tt.close()
    (out/'font_rendering.json').write_text(json.dumps({'font_file':str(font_file),
        'pdf_font':font.name,'embedded':True,
        'styles_by_page':{p.name.removesuffix('_layout.json'):json.loads(p.read_text(encoding='utf-8'))['audit'].get('annotation_style') for p in files},
        'frame_and_leader_stroke_width_mm':.2,
        'alignment':'actual glyph bounding box centred in circle/rectangle',
        'pdf_pages':len(files)},ensure_ascii=False,indent=2),encoding='utf-8')
    if not quiet:print('Exported',len(files),'pages with embedded',font.name,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--out-dir',type=Path,default=HISTORICAL_SAMPLES/'complete_output')
    ap.add_argument('--font-file',type=Path,default=Path('C:/Windows/Fonts/simhei.ttf'))
    ap.add_argument('--png',action='store_true')
    args=ap.parse_args()
    export_pdf(args.out_dir,args.png,args.font_file)
