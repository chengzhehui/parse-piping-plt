"""Attach the inspected PD60 row history and staged preflight results to Excel."""
from collections import defaultdict
import json
import math
from pathlib import Path
from openpyxl import load_workbook

from project_paths import ARCHIVE
BASE=ARCHIVE/'beihai_audit'
CLASSIFICATIONS={
    'R1':'缺少闭合六边形＋独立填充线的焊口识别',
    'R2':'缺少原图管端追踪／FLOW箭头连通处理',
    'R3':'缺少HSTU/LSTU连续管子分段追踪',
    'R4':'缺少支架HIT管轴控制点及管内新增焊口插值',
    'R5':'缺少95/96组合元件解析，引用归属错误',
    'R6':'缺少轮廓附着焊口识别／填充笔画续接处理',
    'R7':'缺少126元件解析／相邻管端拓扑定位',
    'R8':'缺少无HIT弯头的粗线连通追踪',
    'R9':'NRSC实体轮廓端口与HIT坐标引线尖存在偏移，按实体端口定位'}


def evidence_text(target):
    refs=set();lines=set();offsets=set()
    def visit(value):
        if isinstance(value,dict):
            if value.get('ref'):refs.add(str(value['ref']))
            if value.get('idf_line'):lines.add(str(value['idf_line']))
            if value.get('dot_offset') is not None:offsets.add(str(value['dot_offset']))
            for v in value.get('path_offsets',[]):offsets.add(str(v))
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(target.get('mapping_evidence',[]))
    return 'UCI: '+','.join(sorted(refs))+'; IDF行: '+','.join(sorted(lines,key=int))+'; PLT字节: '+','.join(sorted(offsets,key=int))


def append_reconciliation(wb,unit):
    baseline=BASE/'baseline_before_reconciliation.xlsx'
    if unit!='PD60' or not baseline.exists():return
    paths=sorted(BASE.glob('preflight_R[1-9]_*.json'))
    if not paths:return
    rounds=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    final=rounds[-1];final_by_key={(t['pipeline'],t['number']):t for t in final['mapped']}
    old=load_workbook(baseline,read_only=True)
    original=list(old['未标注编号'].values)[1:];old.close()
    current=list(wb['标注定位清单'].values)[1:]
    mapped={(r[0].rsplit('_Sht_',1)[0],str(r[2])):r for r in current if r[1]=='焊口'}
    spools=defaultdict(list)
    for r in current:
        if r[1]=='管段':spools[(r[0].rsplit('_Sht_',1)[0],str(r[2]))].append(r[0])
    first={}
    for revision in rounds:
        for t in revision['newly_resolved']:first.setdefault((t['pipeline'],t['number']),revision['revision'])
    for name in ('原未标注逐行核对','规则修改预检记录','原已标注位置修正'):
        if name in wb:del wb[name]
    s=wb.create_sheet('原未标注逐行核对')
    s.append(['管线号','原表页码','编号类型','编号','来源表行号','核对结论','原因分类','首次通过预检',
              '定位PLT及PDF单页图号','纸面坐标mm','IDF及PLT证据','说明'])
    unresolved={(r[0],str(r[3])):r for r in list(wb['未标注编号'].values)[1:] if r[2]=='焊口'}
    for r in original:
        line,page,kind,number,reason,coordinate,source_row=r;key=(line,str(number))
        if kind=='管段':
            sheets=spools.get(key,[])
            s.append([line,page,kind,number,source_row,'已恢复' if sheets else '仍未标注','随所属焊口定位恢复','',','.join(sheets),'','',
                      '原表管段编号未变；按管线/实际图页去重'])
            continue
        t=final_by_key.get(key);position=mapped.get(key)
        if t and position and t['page_stem']==position[0] and math.dist((t['x_mm'],t['y_mm']),(position[5],position[6]))<.2:
            revision=first.get(key,'');category=CLASSIFICATIONS.get(revision.split('_')[0],'可由现有原图几何定位')
            s.append([line,page,kind,number,source_row,'原逻辑缺失，已补充并标注',category,revision,t['page_stem'],
                f"{t['x_mm']:.3f}, {t['y_mm']:.3f}",evidence_text(t),
                '管内新增焊口为有约束插值，仍需审核实际预制分段位置' if 'interpolation' in t['mapping_method'] else '定位点已与原PDF局部图和PLT图元核对'])
        elif key in unresolved:
            row=unresolved[key]
            s.append([line,page,kind,number,source_row,'保留未标注，需源数据确认','短节内部回折重叠，无独立原图管端','',line+'_Sht_1','',
                'IDF第134行126/NRSC；第136行100管子，X=49143→49111；UCI 31181/441 / LSTU_31181/441',row[4]])
        else:s.append([line,page,kind,number,source_row,'历史核对与当前结果不同，请重新预检','','','','','',''])
    s=wb.create_sheet('规则修改预检记录');s.append(['轮次','修改内容','已定位焊口','未定位焊口','累计找回原未标注焊口','与原交付版位置差异数','丢失原已标注数'])
    s.append(['原交付版','初始状态',415,57,0,0,0])
    for r in rounds:
        c=r['summary'];s.append([r['revision'],CLASSIFICATIONS.get(r['revision'].split('_')[0],''),c['mapped'],c['unresolved'],c['newly_resolved'],c['changed_previous'],c['lost_previous']])
    s=wb.create_sheet('原已标注位置修正');s.append(['管线号','焊口号','原图页','原纸面Xmm','原纸面Ymm','修正图页','修正Xmm','修正Ymm','原因'])
    for r in final['changed_previous']:
        a,b=r['old'],r['new'];s.append([r['pipeline'],r['number'],a['page_stem'],a['x_mm'],a['y_mm'],b['page_stem'],b['x_mm'],b['y_mm'],
            '原解析器跳过95/96，导致组合元件UCI错误归给前一个120焊口；按真实两端承插符号修正'])
