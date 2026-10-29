"""Read-only Beihai export preflight; write a designer-facing issue workbook."""
import argparse
from collections import Counter
import math
from pathlib import Path
import re

from project_paths import WORKSPACE
from openpyxl import Workbook
from openpyxl.styles import Alignment,Font,PatternFill
from analyze_plt_bundle import decode_plt,read_export_text,read_hit
from audit_pdms_export import read_csv,coordinate
from beihai_geometry import load_model


def main(argv=None,save=True):
    root=WORKSPACE/'北海项目'
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-dir',type=Path,default=root/'PLT文件转换/PD60')
    ap.add_argument('--idf-dir',type=Path,default=root/'IDF/PD60')
    ap.add_argument('--weld-table',type=Path,default=root/'焊口表.csv')
    args=ap.parse_args(argv)
    files=sorted(args.input_dir.rglob('*.plt'))
    lines=sorted({p.stem.rsplit('_Sht_',1)[0] for p in files})
    all_rows,_=read_csv(args.weld_table)
    rows=[r for r in all_rows if r['管线号'] in lines]
    wb=Workbook();summary=wb.active;summary.title='检查结论'
    summary.append(['检查项','结果','说明'])
    pages=wb.create_sheet('文件配套');pages.append(['单页图号','PLT解析','HIT记录数','IDF存在','说明'])
    errors=[];empty=[]
    for p in files:
        line=p.stem.rsplit('_Sht_',1)[0]
        try:
            decode_plt(p)
            hit_count=len(read_hit(p.with_suffix('.hit')))
            if not hit_count:empty.append(p.stem)
            pages.append([p.stem,'通过',hit_count,(args.idf_dir/(line+'.idf')).is_file(),
                          'HIT为空；可能为材料续页，不能仅据此认定导出失败' if not hit_count else ''])
        except Exception as exc:
            errors.append(p.stem);pages.append([p.stem,'失败','','',str(exc)])
    coords=wb.create_sheet('焊口坐标核对')
    coords.append(['管线号','焊口号','来源表行号','坐标','核对结果','最近端点距离mm','IDF原点偏移mm'])
    counts=Counter()
    for line in lines:
        local=[r for r in rows if r['管线号']==line]
        try:
            model=load_model(args.idf_dir/(line+'.idf'))
        except Exception as exc:
            counts['IDF读取失败']+=len(local)
            coords.append([line,'','','',str(exc)])
            continue
        ports=[p for c in model['components'] for p in c['ports']]
        for r in local:
            q=coordinate(r['焊点位置'])
            distance=min(math.dist(q,p) for p in ports)
            state='端点匹配' if distance<=1 else '坐标未匹配'
            if state=='坐标未匹配':
                for c in model['components']:
                    if c['code'] not in (100,101) or len(c['ports'])!=2:continue
                    a,b=c['ports'];v=tuple(b[k]-a[k] for k in range(3));n=sum(x*x for x in v)
                    t=sum((q[k]-a[k])*v[k] for k in range(3))/n if n else -1
                    if 0<t<1 and math.dist(q,tuple(a[k]+t*v[k] for k in range(3)))<=.1:
                        state='管子内部附加焊口';break
            counts[state]+=1
            coords.append([line,r['焊点编号'],r['_row'],r['焊点位置'],state,round(distance,4),str(model['origin_mm'])])
    log=wb.create_sheet('PDMS导出问题')
    log.append(['日志文件','原始行号','管线号或上下文','消息代码','问题','处理建议'])
    codes=Counter()
    advice={
        '35:1099':'原有注释未定位；请设计核对注释坐标、IDF原点及注释设置。此项不是本工具新标焊口的失败记录。',
        '35:1057':'支架无法按给定坐标定位；即使不标支架管理编号，也需设计核对原图支架是否缺失或错位。',
        '33:432':'请设计运行分图 DESIGN 宏并确认 split ATTA 已保存，避免后续出图分图不稳定。',
        '33:447':'请设计检查指定三通关联的分图 ATTA 创建失败原因。',
        '33:478':'请设计确认管口连接关系，判断缺失连接法兰是否符合设计意图。',
        '33:479':'请设计确认设备口/法兰连接与螺栓选配设置。',
        '33:252':'请设计确认材料代码提取 XX 的配置是否适用本项目。',
        '33:123':'请设计核对材料代码长度限制及截断影响。',
        '33:235':'请设计确认混合管道等级下短材料代码可唯一识别。'}
    for path in sorted(args.input_dir.rglob('mess')):
        context='';ls=read_export_text(path).splitlines()
        for i,text in enumerate(ls):
            m=re.search(r'(?:Starting to detail PIPE /|ERROR detected in pipe /)(.*)',text)
            if m:context=m[1].strip()
            m=re.search(r'\((\d+:\d+)\)',text)
            if not m or m[1] not in advice:continue
            code=m[1];codes[code]+=1
            tail=[]
            for following in ls[i+1:i+4]:
                if re.search(r'\(\d+:\d+\)',following) or 'ERROR detected' in following or not following.strip():break
                tail.append(following.strip())
            # Final split messages explicitly identify their own pipeline.
            pipe=re.search(r'Pipe /(\S+)',text)
            label=pipe[1] if pipe else ('' if code=='33:447' else context)
            log.append([str(path.relative_to(args.input_dir)),i+1,label,code,' '.join([text.strip(),*tail]),advice[code]])
    missing=sorted(set(lines)-{r['管线号'] for r in rows})
    no_table=wb.create_sheet('无焊口表记录管线');no_table.append(['管线号','说明'])
    for line in missing:no_table.append([line,'当前焊口表无记录；需确认是否本来无焊口，不可自行生成编号。'])
    for key,value,note in [
        ('总体结论','图形可解析；导出日志有问题待设计确认','尚未完成本批纸面定位及最终标注验证，不能以坐标核对代替纸面定位验证。'),
        ('管线数量',len(lines),''),('PLT页数',len(files),''),('PLT或HIT读取失败',len(errors),''),
        ('空HIT页数',len(empty),'可能为材料续页，需结合图纸内容判断'),
        ('匹配焊口表记录数',len(rows),''),('IDF端点匹配',counts['端点匹配'],'容差1mm；已加IDF 300原点'),
        ('管子内部附加焊口',counts['管子内部附加焊口'],'线段内点容差0.1mm'),
        ('坐标未匹配',counts['坐标未匹配'],''),('无焊口表记录管线',len(missing),'详见专页'),
        *[(code,n,advice[code]) for code,n in codes.items()]]:
        summary.append([key,value,note])
    for sheet in wb:
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:cell.fill=PatternFill('solid',fgColor='1F4E78');cell.font=Font(color='FFFFFF',bold=True)
        for column in sheet.columns:
            width=min(85,max(16,max(len(str(c.value or '')) for c in list(column)[:100])+2))
            sheet.column_dimensions[column[0].column_letter].width=width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:cell.alignment=Alignment(vertical='top',wrap_text=True)
    output=args.input_dir/'北海PD60_导出文件预检问题清单.xlsx'
    if save:wb.save(output)
    print({'pages':len(files),'pipelines':len(lines),'welds':len(rows),'coordinates':dict(counts),
           'log_codes':dict(codes),'report':str(output)},flush=True)
    return wb


if __name__=='__main__':main()
