"""Resolve supplied management numbers by pipeline and complete UCI identity."""
from collections import defaultdict
import math
from pathlib import Path
import re
from audit_pdms_export import TABLES,read_csv,coordinate
from beihai_valve_geometry import valve_body_center

LABEL_NAMES={'weld':'焊口','spool':'管段','valve':'阀门','flange':'法兰','support':'支架'}


def load_management_tables(folder):
    return {kind:{'file':name,'column':column,'rows':read_csv(Path(folder)/name)[0]}
            for kind,name,column in TABLES}


def resolve_management(tables,line,pages,model,unit):
    targets=[];issues=[];audit=[];review=[];counts=defaultdict(int)
    index=defaultdict(list)
    for stem,page in pages.items():
        for hit in page['hits']:
            dx,dy=page.get('hit_offset_mm',(0,0))
            index[hit['ref']].append(dict(hit,page_stem=stem,x_mm=hit['x_mm']+dx,y_mm=hit['y_mm']+dy))
    by_ref={c['ref']:c for c in model['components'] if c['ref']}
    for kind,table in tables.items():
        local=[r for r in table['rows'] if r['管线号']==line and (not r.get('单元号') or r['单元号']==unit)]
        counts['source_'+kind+'_rows']+=len(local)
        groups=defaultdict(list)
        for row in local:groups[row[table['column']]].append(row)
        for number,rows in groups.items():
            refs=[];reason='';matches=[]
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
                targets.append(target);counts['mapped_'+kind]+=1
                if len(rows)>1:counts['merged_'+kind+'_rows']+=len(rows)-1
                if len(refs)>1 or len(rows)>1:
                    review.append([hit['page_stem'],hit['page_stem'].rsplit('_Sht_',1)[1],LABEL_NAMES[kind],number,
                        method,';'.join(refs),'同号同位置支架合并；来源行全部保留' if len(rows)>1 else '同组多个UCI共用一个编号，定位于其中的FLANGE元件'])
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
                audit.append([unit,line,row.get('页码',''),LABEL_NAMES[kind],number,table['file'],row['_row'],row.get('UCI',''),
                    hit['page_stem'] if hit else '', '同号同位置合并标注' if hit and len(rows)>1 else '已标注' if hit else '未标注',
                    method,reason,hit['x_mm'] if hit else '',hit['y_mm'] if hit else ''])
    return targets,issues,audit,review,dict(counts)
