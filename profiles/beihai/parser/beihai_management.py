"""Resolve supplied management numbers by pipeline and complete UCI identity."""
from collections import defaultdict
import math
from pathlib import Path
import re
from audit_pdms_export import TABLES,read_csv,coordinate
from beihai_valve_geometry import valve_body_center

LABEL_NAMES={'weld':'焊口','spool':'管段','valve':'阀门','flange':'法兰','support':'支架'}


def surviving_coincident_support(rows,refs,index,by_ref):
    """Retain a number already present on a valid row of a duplicate group.

    This never substitutes a new UCI by coordinate. At least one original table
    UCI must still exist in both IDF and HIT. A changed model coordinate keeps
    the existing source identity and is separately reported for review.
    """
    if len(rows)<2 or any(not re.fullmatch(r'\d+/\d+',ref) for ref in refs):return None
    for row in rows:
        values=[s.strip().lstrip('=') for s in re.split('[;；]',row.get('UCI','')) if s.strip()]
        if not values or any(not re.fullmatch(r'\d+/\d+',value) for value in values):return None
    missing=[ref for ref in refs if not index.get(ref)];active=[ref for ref in refs if index.get(ref)]
    if not missing or not active or any(ref in by_ref for ref in missing):return None
    if any(len(index[ref])!=1 for ref in active):return None
    materials={(r.get('材料代码',''),r.get('支架规格','')) for r in rows}
    if len(materials)!=1 or any(not value for value in next(iter(materials))):return None
    xyz=[coordinate(r.get('支架坐标','')) for r in rows]
    if any(q is None for q in xyz) or any(math.dist(q,xyz[0])>.1 for q in xyz):return None
    residuals={}
    for ref in active:
        comp=by_ref.get(ref)
        if not comp or comp['code']!=150 or not comp['ports']:return None
        residuals[ref]=min(math.dist(xyz[0],p) for p in comp['ports'])
    hits=[index[ref][0] for ref in active]
    if len({h['page_stem'] for h in hits})!=1:return None
    if any(math.dist((h['x_mm'],h['y_mm']),(hits[0]['x_mm'],hits[0]['y_mm']))>.15 for h in hits):return None
    return {'active_source_refs':active,'inactive_duplicate_refs':missing,'shared_source_coordinate_mm':xyz[0],
            'active_model_coordinate_residual_mm':residuals,
            'source_rows':[r['_row'] for r in rows],'material_code':rows[0]['材料代码'],'support_spec':rows[0]['支架规格']}


def load_management_tables(folder,kinds=None,paths=None):
    paths=paths or {}
    return {kind:{'file':Path(paths[kind]).name if kind in paths else name,'column':column,'source_path':str(Path(paths.get(kind,Path(folder)/name)).resolve()),
                  'rows':read_csv(Path(paths.get(kind,Path(folder)/name)))[0]}
            for kind,name,column in TABLES if kinds is None or kind in kinds}


def resolve_management(tables,line,pages,model,unit):
    targets=[];issues=[];audit=[];review=[];counts=defaultdict(int)
    index=defaultdict(list)
    for stem,page in pages.items():
        for hit in page['hits']:
            dx,dy=page.get('hit_offset_mm',(0,0))
            index[hit['ref']].append(dict(hit,page_stem=stem,x_mm=hit['x_mm']+dx,y_mm=hit['y_mm']+dy))
    by_ref={c['ref']:c for c in model['components'] if c['ref']}
    for kind,table in tables.items():
        local=[r for r in table['rows'] if r['管线号']==line and (not unit or not r.get('单元号') or r['单元号']==unit)]
        counts['source_'+kind+'_rows']+=len(local)
        groups=defaultdict(list)
        for row in local:groups[row[table['column']]].append(row)
        for number,rows in groups.items():
            refs=[];reason='';matches=[];duplicate_evidence=None
            for row in rows:
                values=[s.strip().lstrip('=') for s in re.split('[;；]',row.get('UCI','')) if s.strip()]
                if not values or any(not re.fullmatch(r'\d+/\d+',s) for s in values):reason='UCI缺失或格式不受支持'
                refs.extend(values)
            refs=list(dict.fromkeys(refs))
            if not number:reason='管理编号为空，不能自行编造编号'
            for ref in refs:
                hits=index.get(ref,[])
                if len(hits)!=1:
                    reason=('UCI在当前HIT中缺失：'+ref+'；IDF有该元件但原图未输出对应法兰图元，不能按管轴插值代替实体法兰'
                            if not hits and ref in by_ref and kind=='flange' else
                            'UCI在当前HIT中缺失：'+ref if not hits else 'UCI对应多个HIT位置：'+ref)
                matches.extend(hits)
            if kind=='support' and reason.startswith('UCI在当前HIT中缺失：'):
                duplicate_evidence=surviving_coincident_support(rows,refs,index,by_ref)
                if duplicate_evidence:reason=''
            if not reason and len({h['page_stem'] for h in matches})!=1:reason='同一管理编号的UCI分布于不同图页，需确认标注归属'
            if not reason and len(rows)>1:
                gap=max((math.dist((a['x_mm'],a['y_mm']),(b['x_mm'],b['y_mm'])) for a in matches for b in matches),default=0)
                if gap>.15:reason='同一管理编号对应多个不同位置，需核对编号重复'
                # Coincident support names must also share the table coordinate.
                xyz=[coordinate(r.get('支架坐标','')) for r in rows]
                if kind=='support' and all(q is not None for q in xyz) and any(math.dist(q,xyz[0])>.1 for q in xyz):reason='同号支架的表坐标不一致，不能合并'
            if not reason and len(refs)>1 and len(rows)==1:
                gap=max((math.dist((a['x_mm'],a['y_mm']),(b['x_mm'],b['y_mm'])) for a in matches for b in matches),default=0)
                if gap>10:reason='同组UCI的纸面间距大于10mm，需确认是否为同一连接组'
            hit=None;method=''
            body=None
            if not reason and kind=='valve':
                try:
                    body=valve_body_center(by_ref.get(refs[0]),matches[0],pages[matches[0]['page_stem']])
                except ValueError as exc:reason=str(exc)
            if not reason:
                # A joined flange/PCOMPONENT row describes one management
                # group. Attach its one label to the actual flange locator.
                preferred=[h for h in matches if 'FLANGE' in h['name'].upper()]
                hit=(preferred or matches)[0]
                method=('coincident-support-UCI-rows-merged' if len(rows)>1 else
                        'grouped-UCI-native-flange-locator' if len(refs)>1 else 'unique-pipeline-UCI-HIT')
                if duplicate_evidence:method='coincident-support-surviving-UCI-merged'
                original_hit=(hit['x_mm'],hit['y_mm'])
                if body:
                    hit=dict(hit,x_mm=body['center'][0],y_mm=body['center'][1])
                    method='UCI-IDF-axis-native-valve-body-midpoint'
                target={'key':f'{line}:{kind}:{number}','kind':kind,'pipeline':line,'number':number,
                    'page_stem':hit['page_stem'],'x_mm':hit['x_mm'],'y_mm':hit['y_mm'],
                    'source_row':rows[0]['_row'],'source_rows':[r['_row'] for r in rows],
                    'source_file':table['file'],'ref':';'.join(refs),'mapping_method':method,
                    'coordinate_mm':coordinate(rows[0].get('支架坐标',''))}
                if body:target['valve_body_evidence']={'original_hit_mm':original_hit,**body}
                if duplicate_evidence:target['duplicate_support_evidence']=duplicate_evidence
                targets.append(target);counts['mapped_'+kind]+=1
                if len(rows)>1:counts['merged_'+kind+'_rows']+=len(rows)-1
                if len(refs)>1 or len(rows)>1:
                    review.append([hit['page_stem'],hit['page_stem'].rsplit('_Sht_',1)[1],LABEL_NAMES[kind],number,
                        method,';'.join(refs),'同号同坐标重复记录含失效UCI，已按组内有效UCI定位，请更新重复来源记录' if duplicate_evidence else
                        '同号同位置支架合并；来源行全部保留' if len(rows)>1 else '同组多个UCI共用一个编号，定位于其中的FLANGE元件'])
                if kind=='support':
                    for row in rows:
                        xyz=coordinate(row.get('支架坐标',''));comp=by_ref.get(row.get('UCI'))
                        if xyz is not None and comp and comp['ports'] and min(math.dist(xyz,p) for p in comp['ports'])>1:
                            review.append([hit['page_stem'],hit['page_stem'].rsplit('_Sht_',1)[1],LABEL_NAMES[kind],number,method,row['UCI'],
                                '表中支架坐标与IDF端点相差大于1mm；已按唯一UCI对应原图定位，请复核坐标'])
            else:
                counts['unresolved_'+kind]+=1
                for row in rows:issues.append([line,row.get('页码',''),LABEL_NAMES[kind],number,reason,row.get('支架坐标',''),row['_row']])
            for row in rows:
                audit.append([unit or row.get('单元号',''),line,row.get('页码',''),LABEL_NAMES[kind],number,table['file'],row['_row'],row.get('UCI',''),
                    hit['page_stem'] if hit else '', '同号同位置合并标注' if hit and len(rows)>1 else '已标注' if hit else '未标注',
                    method,('同号同坐标重复记录含失效UCI；已按组内有效UCI定位，来源行全部保留' if duplicate_evidence and hit else reason),hit['x_mm'] if hit else '',hit['y_mm'] if hit else ''])
    return targets,issues,audit,review,dict(counts)
