"""Keep actionable reviewer items public; persist technical evidence internally."""
import json
import math
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


def reviewer_workbook(wb,metadata=None):
    result=Workbook();missing=result.active;missing.title='未标注编号'
    missing.append(['单页图号','页码','编号类型','编号','未标注原因及处理建议','参考坐标','来源表行号'])
    identical_management_issues={}
    for row in list(wb['未标注编号'].values)[1:]:
        line,page,kind,number,reason,coordinate,source_row=row
        if kind=='焊口' and '回折' in str(reason):reason='末端管子回折32mm并与短节重叠，原图无独立管端；请确认坐标或是否取消该焊口。'
        elif kind=='法兰' and 'HIT' in str(reason):reason='未找到该法兰的可靠图纸位置；请确认是否漏出该元件，或核定位置后人工补标。'
        stem=line if '_Sht_' in str(line) else f'{line}_Sht_{page}' if str(page).isdigit() and int(page)>0 else line
        output=[stem,page,kind,number,reason,coordinate,source_row]
        if kind in ('支架','阀门','法兰'):
            identity=tuple(output[:6])
            if identity in identical_management_issues:
                cell=missing.cell(identical_management_issues[identity],7)
                cell.value=','.join(dict.fromkeys([*str(cell.value).split(','),str(source_row)]))
                continue
            identical_management_issues[identity]=missing.max_row+1
        missing.append(output)
    source_rows={}
    for r in list(wb['标注定位清单'].values)[1:]:
        source_rows[(r[0],r[1],str(r[2]))]=(r[10] if len(r)>10 else '焊口表.csv',
            r[11] if len(r)>11 and ',' in str(r[11]) else r[3])
    required=[];layouts=[];seen=set()
    for r in list(wb['自动匹配需审核'].values)[1:]:
        stem,page,kind,number,method,uci,note=r;action=None
        if kind=='布局':layouts.append([stem,page,number,note]);continue
        if str(note).startswith('['):
            for entry in json.loads(note):
                reason=entry.get('reason','')
                if '新旧IDF接口坐标不一致' in reason:
                    action='表与当前IDF接口坐标不一致；已按相同元件UCI的唯一接口标注，请核对版本及处理差异。'
                    if any(t['page_stem']==stem and str(t['number'])==str(number)
                           and not t['interface_identity_evidence']['native_weld_glyph']
                           for t in (metadata or {}).get('weld_interface_evidence',[])):
                        action+='原图无独立焊口符号，请重点核对接口落点。'
                elif '插值' in reason:action='管内分段焊口按模型坐标定位，请确认预制分段位置与现场计划一致。'
                elif '参考IDF与当前IDF端口独立定位一致' in reason:
                    action='已按原表元件归属及当前图纸端口标注，请核对IDF分段、坐标或版本差异。'
                    if any(t['page_stem']==stem and str(t['number'])==str(number)
                           and not t['reference_geometry_evidence']['native_weld_glyph']
                           for t in (metadata or {}).get('weld_reference_evidence',[])):
                        action+='原图无独立焊口符号，请重点核对落点。'
                elif '按原图完整元件两端及相邻管线校正' in reason:
                    action='已按原图元件两端及相邻管线确认接口；请核对等轴投影重合或支架定位点引起的端口误配修正。'
                elif 'HIT为空；按唯一模型管子' in reason:
                    action='HIT为空；已按唯一模型管子、原图唯一直管及一致投影方向标注自由端，请核对该单管端点。'
                elif 'disagree' in reason:action=f"相邻元件推导的焊口位置相差{entry.get('max_gap_mm',0):g}mm，请确认正确的焊口落点。"
        elif '坐标与IDF端点相差' in str(note):action='支架表坐标与设计模型不一致；已按UCI对应元件标注，请核对表坐标。'
        elif method=='coincident-support-surviving-UCI-merged':action='同号同坐标重复记录含失效UCI；已按组内有效元件标注，请清理或更新重复来源记录。'
        elif method=='partial-spool-membership':action='管段部分焊口未定位，请结合未标注清单确认该管段范围。'
        elif method=='pipeline-alias':
            drawing=str(stem).rsplit('_Sht_',1)[0]
            proofs=(metadata or {}).get('alias_evidence',[])
            normalized=any(p['drawing_pipeline']==drawing and p['source_pipeline'].replace('/','')==drawing
                           and p.get('idf_pipeline_identity')==[p['source_pipeline']] for p in proofs)
            normalized=normalized or any(p['drawing_pipeline']==drawing and p.get('identity_verified')
                and {drawing,p['source_pipeline'],p.get('idf_filename')}<=set(p.get('normalization_variants',[])) for p in proofs)
            if normalized:continue
            action=note
        if not action:continue
        key=(stem,kind,str(number),action)
        if key in seen:continue
        seen.add(key);source_file,source_row=source_rows.get((stem,kind,str(number)),('', ''))
        required.append([stem,page,kind,number,action,source_file,source_row])
    if (metadata or {}).get('report_coincident_welds'):
        groups={}
        for r in list(wb['标注定位清单'].values)[1:]:
            if r[1]=='焊口':groups.setdefault(r[0],[]).append(r)
        for stem,rows in groups.items():
            for r in rows:
                others=sorted({str(o[2]) for o in rows if str(o[2])!=str(r[2]) and math.dist(r[5:7],o[5:7])<.25})
                if not others:continue
                action='与焊口'+','.join(others)+'对应同一图纸位置，请确认是否重复编号、接口合并或图表版本不一致。'
                source_file,source_row=source_rows[(stem,'焊口',str(r[2]))]
                required.append([stem,stem.rsplit('_Sht_',1)[1],'焊口',r[2],action,source_file,source_row])
    if required:
        sheet=result.create_sheet('已标注需核对');sheet.append(['单页图号','页码','编号类型','编号','需核对事项','来源表','来源表行号'])
        for row in required:sheet.append(row)
    if layouts:
        sheet=result.create_sheet('布局需处理');sheet.append(['单页图号','页码','编号','需处理事项'])
        for row in layouts:sheet.append(row)
    return result
