"""Keep actionable reviewer items public; persist technical evidence internally."""
import json
from pathlib import Path
from openpyxl import Workbook

from project_paths import AUDIT
BASE=AUDIT/'render_records'


def audit_path(unit,pipeline=None):
    return BASE/((unit+('__'+pipeline if pipeline else ''))+'.json')


def save_internal_audit(wb,unit,pipeline,valve_centres,metadata,spool_roots=None,page_stats=None):
    path=audit_path(unit,pipeline);path.parent.mkdir(parents=True,exist_ok=True)
    data={'metadata':metadata,'sheets':{s.title:[list(r) for r in s.values] for s in wb},'valve_centres':valve_centres}
    if spool_roots is not None:data['spool_roots']=spool_roots
    if page_stats is not None:data['page_stats']=page_stats
    path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')


def reviewer_workbook(wb):
    result=Workbook();missing=result.active;missing.title='未标注编号'
    missing.append(['单页图号','页码','编号类型','编号','未标注原因及处理建议','参考坐标','来源表行号'])
    for row in list(wb['未标注编号'].values)[1:]:
        line,page,kind,number,reason,coordinate,source_row=row
        if kind=='焊口' and '回折' in str(reason):reason='末端管子回折32mm并与短节重叠，原图无独立管端；请确认坐标或是否取消该焊口。'
        elif kind=='法兰' and 'HIT' in str(reason):reason='未找到该法兰的可靠图纸位置；请确认是否漏出该元件，或核定位置后人工补标。'
        stem=line if '_Sht_' in str(line) else f'{line}_Sht_{page}' if str(page).isdigit() and int(page)>0 else line
        missing.append([stem,page,kind,number,reason,coordinate,source_row])
    source_rows={}
    for r in list(wb['标注定位清单'].values)[1:]:source_rows[(r[0],r[1],str(r[2]))]=(r[10] if len(r)>10 else '焊口表.csv',r[3])
    required=[];layouts=[];seen=set()
    for r in list(wb['自动匹配需审核'].values)[1:]:
        stem,page,kind,number,method,uci,note=r;action=None
        if kind=='布局':layouts.append([stem,page,number,note]);continue
        if str(note).startswith('['):
            for entry in json.loads(note):
                reason=entry.get('reason','')
                if '插值' in reason:action='管内分段焊口按模型坐标定位，请确认预制分段位置与现场计划一致。'
                elif 'disagree' in reason:action=f"相邻元件推导的焊口位置相差{entry.get('max_gap_mm',0):g}mm，请确认正确的焊口落点。"
        elif '坐标与IDF端点相差' in str(note):action='支架表坐标与设计模型不一致；已按UCI对应元件标注，请核对表坐标。'
        elif method=='partial-spool-membership':action='管段部分焊口未定位，请结合未标注清单确认该管段范围。'
        if not action:continue
        key=(stem,kind,str(number),action)
        if key in seen:continue
        seen.add(key);source_file,source_row=source_rows.get((stem,kind,str(number)),('', ''))
        required.append([stem,page,kind,number,action,source_file,source_row])
    if required:
        sheet=result.create_sheet('已标注需核对');sheet.append(['单页图号','页码','编号类型','编号','需核对事项','来源表','来源表行号'])
        for row in required:sheet.append(row)
    if layouts:
        sheet=result.create_sheet('布局需处理');sheet.append(['单页图号','页码','编号','需处理事项'])
        for row in layouts:sheet.append(row)
    return result
