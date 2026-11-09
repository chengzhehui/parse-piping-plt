"""Export the original unmarked rows, verified recoveries and residual evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'profiles/beihai/parser'))
from project_paths import REPOSITORY,WORKSPACE,AUDIT
from beihai_management import LABEL_NAMES,load_management_tables
from beihai_geometry import load_model
from beihai_unit_profile import unit_config,configured_paths
from openpyxl import Workbook
from openpyxl.styles import Alignment,Font,PatternFill


def key(line,kind,number):return line.rsplit('_Sht_',1)[0],kind,str(number)


def management_pending_diagnosis(kind,reason,components):
    if 'HIT中缺失' in reason:
        category=kind+'UCI未在原图HIT中出现'
        note=('本批IDF中存在该来源UCI；请核对原图导出范围及整组编号关联。' if components else
              '本批IDF中也未找到该来源UCI；请核对编号表版本及管线归属。')
        return {'category':category,'reason':reason+'；'+note}
    return {'category':kind+'编号关联需核对','reason':reason}


def recovery_rule(target):
    if target.get('native_topology_evidence'):return '完整元件两端及相邻管线拓扑校核'
    if target.get('reference_geometry_evidence'):return '参考元件归属与当前原图端口独立核对'
    if target.get('interface_identity_evidence'):return '新旧IDF稳定元件的唯一公共接口'
    text=json.dumps(target.get('mapping_evidence',{}),ensure_ascii=False)
    if 'curved-elbow' in target['mapping_method']:return '圆弧弯头真实焊接端口'
    if 'native-open-pipe-end' in text:return '模型自由端与原图管端'
    if 'native-crossing-pipe-knockout' in text:return '管线交叉留白'
    if 'pipe_chain_refs' in text:return '穿过未绘支架的共线管子'
    return target['mapping_method']


def evidence_refs(value):
    lines=set();refs=set()
    def visit(v):
        if isinstance(v,dict):
            if v.get('idf_line'):lines.add(str(v['idf_line']))
            for name in ('ref','pipe_ref','component_ref'):
                if v.get(name):refs.add(str(v[name]))
            for item in v.values():visit(item)
        elif isinstance(v,list):
            for item in v:visit(item)
    visit(value)
    return ','.join(sorted(lines,key=int)), ';'.join(sorted(refs))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit',required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--preflight',type=Path,required=True)
    args=parser.parse_args()
    before=json.loads(args.baseline.read_text(encoding='utf-8'))
    final=json.loads(args.preflight.read_text(encoding='utf-8'))
    assert final['unit']==args.unit
    assert final['regression_passed'],'最终预检仍有未核验的变更或丢失'
    for name in ('lost_previous','management_changed_previous','management_lost_previous','unexpected_previous_changes'):
        assert final['summary'].get(name,0)==0,(name,final['summary'].get(name))
    mapped={key(t['pipeline'],LABEL_NAMES[t['kind']],t['number']):t
            for t in final['mapped']+final.get('management_mapped',[])}
    mapped_source={(LABEL_NAMES[t['kind']],int(n)):t for t in mapped.values() for n in t.get('source_rows',[t['source_row']])}
    missing={key(e['target']['pipeline'],'焊口',e['target']['number']):e for e in final['unresolved']}
    missing_source={e['target']['source_row']:e for e in final['unresolved']}
    config=unit_config(args.unit);aliases=config.get('pipeline_aliases',{});paths_config=configured_paths(config,args.unit)
    kinds=[k for k in before['metadata'].get('annotation_kinds',[]) if k not in ('weld','spool')]
    tables=load_management_tables(WORKSPACE/'北海项目',kinds);models={}
    recovered_round={}
    round_files=sorted([*AUDIT.glob(f'preflight_{args.unit}_R*.json'),*AUDIT.glob(f'preflight_{args.unit}_I*.json'),*AUDIT.glob(f'preflight_{args.unit}_J*.json')],key=lambda p:p.stat().st_mtime)
    round_files+= [p for p in AUDIT.glob('preflight_*_G*.json') if json.loads(p.read_text(encoding='utf-8')).get('unit')==args.unit]
    round_files=sorted(set(round_files),key=lambda p:p.stat().st_mtime)
    for path in round_files:
        item=json.loads(path.read_text(encoding='utf-8'))
        if item.get('publication_accepted') is False:continue
        if not item.get('regression_passed',False):continue
        for target in item['mapped']:
            recovered_round.setdefault(key(target['pipeline'],'焊口',target['number']),item['revision'])
    rows=[];proofs=[]
    for original in before['sheets']['未标注编号'][1:]:
        line,kind,number=key(original[0],original[2],original[3]);identity=(line,kind,number)
        source_row=original[6];target=mapped_source.get((kind,int(source_row)))
        if target:
            rule=recovery_rule(target)
            if identity in recovered_round:rule=recovered_round[identity]+'；'+rule
            idf_lines,refs=evidence_refs(target.get('mapping_evidence',{}))
            explanation='原图几何与模型拓扑证据匹配';next_step='已进入转换标注；插值类位置仍按原规则保留审核'
            if target.get('reference_geometry_evidence'):
                e=target['reference_geometry_evidence'];explanation=f"原表坐标{e['source_coordinate_mm']}；当前接口{e['model_query_mm']}；新旧模型独立定位一致"
                next_step='核对IDF分段、坐标或版本差异；原表坐标保留'
            if target.get('native_topology_evidence'):
                e=target['native_topology_evidence'];refs=e['component_ref'];explanation='按完整元件的真实两端及相邻管线确认端口，避免等轴投影重合误配'
                next_step='原图完整元件两端及连通轴线证据已核对'
            if target.get('interface_identity_evidence'):
                migration=target['interface_identity_evidence']
                refs=';'.join(sorted({ref for e in migration['interfaces'] for ref in e['refs']}))
                idf_lines=','.join(str(n) for e in migration['interfaces'] for n in e['current_idf_lines'])
                explanation=f"原表坐标{migration['source_coordinate_mm']}；当前接口{migration['model_query_mm']}；"+('原图焊口符号已核对' if migration['native_weld_glyph'] else '依靠元件端口/轴线证据，无独立焊口符号')
                next_step='核对表与图纸版本及IDF处理差异；原表坐标未改写'
            if target.get('duplicate_support_evidence'):
                duplicate=target['duplicate_support_evidence']
                refs='有效UCI：'+';'.join(duplicate['active_source_refs'])+'；失效重复UCI：'+';'.join(duplicate['inactive_duplicate_refs'])
                explanation='同号同坐标来源组仍有有效原表UCI，编号已按有效实体标注；失效UCI并未恢复，来源记录需更新'
                next_step='清理失效重复记录；有效实体坐标变化已列入审核'
            if target['pipeline']!=line:explanation+='；来源管线 '+line+'，现按已核验元件归属标注在 '+target['pipeline']
            row=[line,kind,number,'已适配找回',rule,explanation,target['page_stem'],
                 round(target['x_mm'],4),round(target['y_mm'],4),source_row,idf_lines,refs,next_step]
            proof={'identity':identity,'status':'recovered','rule':rule,'target':target}
        elif kind=='焊口':
            entry=missing_source[int(source_row)];diagnosis=entry['diagnosis']
            idf_lines=','.join(str(c['line']) for c in entry['near_components'])
            refs=';'.join(c['ref'] for c in entry['near_components'] if c['ref'])
            if not idf_lines:
                idf_lines=','.join(str(c['line']) for c in entry['pipe_interiors'])
                refs=';'.join(c['ref'] for c in entry['pipe_interiors'])
            row=[line,kind,number,'仍需处理',diagnosis['category'],diagnosis['reason'],'','','',source_row,idf_lines,refs,'核对同期模型/图纸、分图或实际接口']
            proof={'identity':identity,'status':'pending','diagnosis':diagnosis,'model_evidence':entry['near_components'],'exhaustive_audit':entry.get('exhaustive_audit')}
        else:
            table=next(t for k,t in tables.items() if LABEL_NAMES[k]==kind)
            sources=[r for r in table['rows'] if r['_row']==int(source_row)]
            refs=';'.join(r['UCI'] for r in sources)
            if line not in models:models[line]=load_model(paths_config['idf_dir']/(aliases.get(line,line)+'.idf'),config.get('idf_coordinate_offset_mm'))
            components=[c for c in models[line]['components'] if c['ref'] in refs.split(';')]
            idf_lines=','.join(str(c['line']) for c in components)
            actual=[r for r in final.get('management_unresolved',[]) if key(r[0],r[2],r[3])==identity and int(r[6])==int(source_row)]
            reason=str(actual[0][4]) if actual else str(original[4])
            diagnosis=management_pending_diagnosis(kind,reason,components)
            row=[line,kind,number,'仍需处理',diagnosis['category'],diagnosis['reason'],'','','',source_row,idf_lines,refs,'确认实体元件、整组编号及同期编号表']
            proof={'identity':identity,'status':'pending','diagnosis':diagnosis,
                   'components':[{k:c[k] for k in ('code','ref','line','ports')} for c in components]}
        rows.append(row);proofs.append(proof)
    recovered=[r for r in rows if r[3]=='已适配找回'];pending=[r for r in rows if r[3]=='仍需处理']
    assert len(rows)==len(recovered)+len(pending)
    book=Workbook();summary=book.active;summary.title='核对汇总';summary.append(['项目','数量','说明'])
    summary.append(['原未标注来源记录',len(rows),'固定首版审计与问题清单，避免重跑改变比较基准'])
    summary.append(['适配恢复来源记录',len(recovered),'固定基准全量预检；已有落点的有据校正单独列出，其他标注无非预期变化或丢失'])
    summary.append(['适配恢复编号',len({tuple(r[:3]) for r in recovered}),'按管线、编号类型和编号去重'])
    summary.append(['仍需处理来源记录',len(pending),'逐行证据保留全部原表行；简明问题清单合并完全相同的管理编号问题'])
    summary.append(['仍需处理编号',len({tuple(r[:3]) for r in pending}),'按管线、编号类型和编号去重'])
    for category,count in Counter(r[4] for r in pending).items():summary.append([category,count,''])
    header=['管线号','编号类型','编号','结论','原因分类或恢复轮次','核对说明','恢复图页','纸面Xmm','纸面Ymm','原表行号','IDF行号','UCI/管子引用','后续处理']
    for name,subset in [('原未标注逐行核对',rows),('已适配恢复',recovered),('仍需处理',pending)]:
        sheet=book.create_sheet(name);sheet.append(header)
        for row in subset:sheet.append(row)
    original_source={int(r[2]) for r in before['sheets'].get('焊口坐标核对',[])[1:]}
    additions=book.create_sheet('新增纳入来源');additions.append(['当前管线号','焊口号','来源行号','结果','图页或未标注原因'])
    for t in final['mapped']:
        if t['source_row'] not in original_source:additions.append([t['pipeline'],t['number'],t['source_row'],'已标注',t['page_stem']])
    for e in final['unresolved']:
        t=e['target']
        if t['source_row'] not in original_source:additions.append([t['pipeline'],t['number'],t['source_row'],'未标注',e['diagnosis']['reason']])
    summary.append(['新增纳入焊口来源行',additions.max_row-1,'按UCI及新旧IDF核实的名称映射补入；与原未标注恢复数分开统计'])
    corrections=book.create_sheet('已标落点校正');corrections.append(['管线号','焊口号','来源行号','原图页','原Xmm','原Ymm','新图页','新Xmm','新Ymm','元件UCI','依据'])
    changes={c['new']['source_row']:c for c in final.get('verified_previous_changes',[])}
    original_positions={int(r[3]):r for r in before['sheets']['标注定位清单'][1:] if r[1]=='焊口'}
    for t in final['mapped']:
        old=original_positions.get(t['source_row'])
        if old and (old[0]!=t['page_stem'] or abs(old[5]-t['x_mm'])>1e-6 or abs(old[6]-t['y_mm'])>1e-6):
            assert t.get('native_topology_evidence'),'原始基准落点变化缺少拓扑校正证据'
            changes[t['source_row']]={'new':t,'old':{'page_stem':old[0],'x_mm':old[5],'y_mm':old[6]}}
    for change in changes.values():
        t=change['new'];old=change['old'];corrections.append([t['pipeline'],t['number'],t['source_row'],old['page_stem'],old['x_mm'],old['y_mm'],t['page_stem'],t['x_mm'],t['y_mm'],t['native_topology_evidence']['component_ref'],'完整元件真实两端＋相邻管线独立控制点'])
    rounds=book.create_sheet('每轮预检');rounds.append(['轮次','已定位焊口','本轮新增','累计恢复','未定位焊口','原焊口变化','原焊口丢失','已定位管理编号','未定位管理来源记录','原管理编号变化','原管理编号丢失','回归检查通过'])
    prior=None;round_data=[]
    for path in round_files:
        item=json.loads(path.read_text(encoding='utf-8'));s=item['summary'];round_data.append({'revision':item['revision'],**s})
        passed=item.get('publication_accepted') is not False and item.get('regression_passed',False)
        rounds.append([item['revision'],s['mapped'],s['mapped']-prior if prior is not None else 0,s['newly_resolved'],s['unresolved'],s['changed_previous'],s['lost_previous'],s['management_mapped'],s['management_unresolved'],s['management_changed_previous'],s['management_lost_previous'],'是' if passed else '否，试验结果未采用']);prior=s['mapped']
    for sheet in book:
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='1F4E78')
        for column,width in zip('ABCDEFGHIJKLM',(36,12,10,16,40,85,43,14,14,14,24,48,55)):sheet.column_dimensions[column].width=width
        for cells in sheet.iter_rows(min_row=2):
            sheet.row_dimensions[cells[0].row].height=48
            for cell in cells:cell.alignment=Alignment(vertical='top',wrap_text=True)
    destination=WORKSPACE/'北海项目/PLT文件转换'/args.unit/f'北海{args.unit}_未标注逐行核对.xlsx';book.save(destination)
    folder=AUDIT/'reconciliation'/args.unit;folder.mkdir(parents=True,exist_ok=True)
    report={'unit':args.unit,'original':len(rows),'recovered':len(recovered),'pending':len(pending),
            'remaining_categories':dict(Counter(r[4] for r in pending)),
            'recovery_rules':dict(Counter(r[4] for r in recovered)),'rounds':round_data,'rows':proofs}
    (folder/'逐行核对证据.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('unit','original','recovered','pending','remaining_categories','recovery_rules')},ensure_ascii=False))
    print(destination)


if __name__=='__main__':main()
