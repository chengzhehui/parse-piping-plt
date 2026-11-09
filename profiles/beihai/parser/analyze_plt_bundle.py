"""Sample-scoped PDMS binary PLT / HIT / IDF investigation.

Reconstruction reads PLT only. The reference PDF is optional visual QA input.
Unknown commands stop decoding; this is not a universal PDMS format reader.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from project_paths import HISTORICAL_SAMPLES
import re
import struct
import xml.etree.ElementTree as ET


def decode_plt(path: Path):
    raw = path.read_bytes()
    if len(raw) < 22 or len(raw) % 2:
        raise ValueError("Invalid sample PLT length")
    words = struct.unpack(f">{(len(raw)-16)//2}H", raw[16:])
    x = y = 0
    width = height = None
    segments, records = [], []
    counts = Counter()
    i = 0
    ended = False
    while i < len(words):
        start = i
        op = words[i]
        i += 1
        old = (x, y)
        draw = False
        if op == 11:
            height, width = words[i:i+2]
            i += 2
            kind = "paper"
        elif op == 7:
            args = words[i:i+2]
            i += 2
            if args != (0, 0):
                raise ValueError(f"Unverified command 7 arguments {args}")
            kind = "setup_7_zero"
        elif op in (0, 10):
            kind = f"setup_{op}"
        elif op == 2 and records and records[-1]['kind'] == 'setup_7_zero':
            # Observed attribute state: 7,0,0,2 (normally 7,0,0,10).
            # It has no coordinate operands. Retain its byte offset and do
            # not move the pen; decode all following geometry as usual.
            kind = 'setup_2_after_7_zero'
        elif op in (3, 4):
            x, y = words[i:i+2]
            i += 2
            draw = op == 4
            kind = "draw_absolute" if draw else "move_absolute"
        elif op in (5, 6):
            if op == 5:
                x = words[i]
            else:
                y = words[i]
            i += 1
            draw = True
            kind = "draw_horizontal" if op == 5 else "draw_vertical"
        elif op == 1:
            kind = "end"
            ended = True
        elif 10201 <= op <= 30602:
            # Observed zero move is 15301; zero draw is 25502.
            # 101-wide packed signed deltas, in 0.1 mm units.
            draw = op >= 20402
            delta = op - (25502 if draw else 15301)
            dx = (delta + 50) // 101
            dy = delta - dx * 101
            x += dx
            y += dy
            kind = "draw_relative" if draw else "move_relative"
        else:
            raise ValueError(f"Unknown command {op} at byte {16+2*start}")
        counts[kind] += 1
        record = {"offset": 16+2*start, "word": op, "kind": kind,
                  "raw_words": list(words[start:i]), "from": old, "to": (x,y)}
        records.append(record)
        if draw and old != (x,y):
            segments.append({"a": old, "b": (x,y), "offset": record["offset"]})
        if ended:
            break
    if not ended or width is None:
        raise ValueError("Missing end or paper command")
    padding = words[i:]
    if any(w != 15301 for w in padding):
        raise ValueError("Unverified trailing data")
    outside = [s for s in segments if any(not (0 <= p[0] <= width and 0 <= p[1] <= height)
                                         for p in (s['a'],s['b']))]
    return {"source": path.name, "header": raw[:16].decode("ascii"),
            "width_mm": width/10, "height_mm": height/10,
            "sha256": hashlib.sha256(raw).hexdigest(), "command_counts": dict(counts),
            "padding_words": len(padding), "outside_paper_segments": len(outside),
            "segments": segments, "records": records}


def read_export_text(path):
    raw = path.read_bytes()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('gb18030')


def read_hit(path):
    result = []
    for n,line in enumerate(read_export_text(path).splitlines(),1):
        m = re.fullmatch(r"\s*([\d.-]+)\s+([\d.-]+)\s+=(\d+/\d+)\s+'(.*)'",line)
        if not m:
            raise ValueError(f"Unknown HIT row {path}:{n}")
        result.append({"line":n,"x_mm":float(m[1]),"y_mm":float(m[2]),
                       "ref":m[3],"name":m[4]})
    return result


def read_idf(path):
    logical = []
    for n,line in enumerate(read_export_text(path).splitlines(),1):
        m = re.match(r"\s*(-?\d+)\s(.*)",line)
        if not m:
            continue
        code = int(m[1])
        if code == -1 and logical:
            logical[-1]["text"] += m[2]
            logical[-1]["last_line"] = n
        else:
            logical.append({"line":n,"last_line":n,"code":code,"text":m[2]})
    refs, locations, splits = {}, {}, []
    component = None
    location = None
    for i,r in enumerate(logical):
        if r["code"] in (35,36,45,46,47,55,100,105,110,130,150,148):
            component = r
        if r["code"] == -39:
            refs[r["text"].strip()] = {"ref_line":r["line"],"component":component}
        if r["code"] == 149:
            location = r
        if r["code"] == -73 and location is not None:
            m = re.match(r"##=(\d+/\d+)\s+'(.*)'",r['text'].strip())
            if m:
                xyz = [int(v)/100 for v in location['text'].split()[:3]]
                locations[m[1]] = {"location_line":location['line'],"label_line":r['line'],
                                   "xyz_mm":xyz,"name":m[2]}
        if r["code"] == -38:
            splits.append({"marker":r,"preceding_records":logical[max(0,i-3):i],
                           "following_records":logical[i+1:i+4]})
    return {"refs":refs,"locations":locations,"splits":splits,"logical_records":logical}


def svg_text(data, hits=()):
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("",ns)
    root = ET.Element(f"{{{ns}}}svg", {"viewBox":f"0 0 {data['width_mm']} {data['height_mm']}",
                                     "width":f"{data['width_mm']}mm", "height":f"{data['height_mm']}mm"})
    ET.SubElement(root,"rect",{"width":"100%","height":"100%","fill":"white"})
    g = ET.SubElement(root,"g",{"transform":f"translate(0 {data['height_mm']}) scale(0.1 -0.1)",
                               "fill":"none","stroke":"black","stroke-width":"0.8"})
    d = ' '.join(f"M{s['a'][0]} {s['a'][1]}L{s['b'][0]} {s['b'][1]}" for s in data['segments'])
    ET.SubElement(g,"path",{"d":d})
    for h in hits:
        # HIT is a component locator, never asserted to be a weld position.
        x,y = h['x_mm'],data['height_mm']-h['y_mm']
        ET.SubElement(root,"circle",{"cx":str(x),"cy":str(y),"r":"1.4","fill":"none","stroke":"red","stroke-width":"0.3"})
        t=ET.SubElement(root,"text",{"x":str(x+2),"y":str(y-2),"font-size":"2.4","fill":"red"})
        t.text=h['ref']
    return ET.tostring(root,encoding="unicode")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=HISTORICAL_SAMPLES)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--render", action="store_true", help="Also export PNG previews and two-page vector PDFs using PyMuPDF")
    args=ap.parse_args()
    base=args.input_dir
    out=args.out_dir or base/'analysis'
    out.mkdir(parents=True,exist_ok=True)
    idf=read_idf(base/'100-B-2.idf')
    summary={"scope":"100-B-2 sample only; native reconstruction; no weld table supplied", "pages":[],"idf":idf}
    for path in sorted(base.glob('*.plt')):
        data=decode_plt(path)
        hits=read_hit(path.with_suffix('.hit'))
        for h in hits:
            h['idf_match']=idf['refs'].get(h['ref'])
            h['idf_location']=idf['locations'].get(h['ref'])
        (out/f'{path.stem}.svg').write_text(svg_text(data),encoding='utf-8')
        (out/f'{path.stem}_hit_overlay.svg').write_text(svg_text(data,hits),encoding='utf-8')
        (out/f'{path.stem}_trace.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        summary['pages'].append({k:v for k,v in data.items() if k not in ('segments','records')} | {
            "segment_count":len(data['segments']),"hits":hits,"idf_matched_hits":sum(h['idf_match'] is not None for h in hits)})
    import xlrd
    with (out/'xls_read.log').open('w',encoding='utf-8') as log:
        book=xlrd.open_workbook(str(base/'ATTA.xls'),logfile=log)
    sheet=book.sheet_by_index(0)
    summary['atta']=[dict(zip(sheet.row_values(0),sheet.row_values(i))) for i in range(1,sheet.nrows)]
    # Distances are measured, deliberately not accepted using a global snap tolerance.
    import math
    summary['split_checks']=[]
    for a in summary['atta']:
        if a['ATTY'] != 'XXXX':
            continue
        m=re.fullmatch(r'E ([\d.-]+)mm N ([\d.-]+)mm U ([\d.-]+)mm',a['POS'])
        if not m:
            raise ValueError(f"Unverified ATTA coordinate syntax: {a['POS']}")
        xyz=list(map(float,m.groups()))
        for split in idf['splits']:
            pipes=[r for r in split['preceding_records'] if r['code']==100]
            following=[r for r in split['following_records'] if r['code'] in (35,45,55,100,105,130)]
            if pipes and following:
                end=[int(v)/100 for v in pipes[-1]['text'].split()[3:6]]
                start=[int(v)/100 for v in following[0]['text'].split()[:3]]
                summary['split_checks'].append({"atta_name":a['Name'],"atta_xyz_mm":xyz,
                    "preceding_end_mm":end,"following_start_mm":start,
                    "distance_to_preceding_end_mm":math.dist(xyz,end),
                    "distance_to_following_start_mm":math.dist(xyz,start),
                    "marker_line":split['marker']['line'],"preceding_component_line":pipes[-1]['line'],
                    "following_component_line":following[0]['line']})
    (out/'evidence.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.render:
        import fitz
        for suffix,label in [('', 'reconstructed'),('_hit_overlay','hit_locator_overlay')]:
            combined=fitz.open()
            for p in summary['pages']:
                stem=Path(p['source']).stem+suffix
                with fitz.open(out/f'{stem}.svg') as doc:
                    doc[0].get_pixmap(matrix=fitz.Matrix(.8,.8)).save(str(out/f'{stem}.png'))
                    with fitz.open('pdf',doc.convert_to_pdf()) as pdf:
                        combined.insert_pdf(pdf)
            combined.save(out/f'100-B-2_{label}.pdf',deflate=True)
            combined.close()
    print(json.dumps({"pages":[{k:v for k,v in p.items() if k!='hits'} for p in summary['pages']],"atta":summary['atta'],"splits":idf['splits']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
