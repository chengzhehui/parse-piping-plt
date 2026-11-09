"""Explicit unit settings and drawing-to-source pipeline identities."""
import json
import math
import re
from project_paths import REPOSITORY,WORKSPACE


def unit_config(unit):
    root=REPOSITORY/'profiles/beihai'
    config=json.loads((root/'config.json').read_text(encoding='utf-8'))
    path=root/'units'/(unit+'.json')
    if path.is_file():config.update(json.loads(path.read_text(encoding='utf-8')))
    return config


def remap_rows(rows,aliases,weld_transfers=None):
    reverse={source:drawing for drawing,source in aliases.items()}
    if len(reverse)!=len(aliases):raise ValueError('同一来源管线不能映射到多张不同管线图')
    existing={r['管线号'] for r in rows}
    for drawing,source in aliases.items():
        if drawing!=source and drawing in existing and source in existing and reverse.get(drawing,drawing)==drawing:
            raise ValueError(f'原表已有图号 {drawing}，请先复核并更新单元名称映射')
    transfers={int(t['source_row']):t for t in weld_transfers or []}
    if len(transfers)!=len(weld_transfers or []):raise ValueError('跨管线焊口来源行重复')
    result=[]
    for r in rows:
        mapped=dict(r,管线号=reverse.get(r['管线号'],r['管线号']))
        t=transfers.get(r.get('_row'))
        if t:
            from audit_pdms_export import coordinate
            kind=t.get('kind','weld')
            if kind not in ('weld','support'):raise ValueError('暂未核验该类管理编号跨管线迁移')
            number_field,coordinate_field=('焊点编号','焊点位置') if kind=='weld' else ('支架编号','支架坐标')
            q=coordinate(r.get(coordinate_field,''))
            if r['管线号']!=t['source_pipeline'] or r.get(number_field)!=str(t['number']) or q is None or math.dist(q,t['source_coordinate_mm'])>1e-6:
                raise ValueError(f'跨管线焊口来源行 {r.get("_row")} 的名称、编号或坐标已变化，需重新核验')
            if kind=='support' and r.get('UCI','').lstrip('=')!=t['ref']:raise ValueError('跨管线支架UCI已变化，需重新核验')
            mapped.update(管线号=t['drawing_pipeline'],_pipeline_transfer=dict(t))
        result.append(mapped)
    if set(transfers)-{r.get('_row') for r in rows}:raise ValueError('跨管线来源行缺失，需重新核验')
    return result


def configured_paths(config,unit):
    return {key:(WORKSPACE/config[pattern].format(unit=unit)).resolve() if config.get(pattern) else None
            for key,pattern in (('input_dir','input_pattern'),('idf_dir','idf_pattern'),('hit_dir','hit_pattern'))}


def hit_file(plt_path,hit_dir=None):
    return hit_dir/(plt_path.stem+'.hit') if hit_dir is not None else plt_path.with_suffix('.hit')


def reference_idf_path(config,unit,line):
    pattern=config.get('weld_reference_idf_pattern')
    if not pattern:return None
    name=config.get('weld_reference_pipeline_aliases',{}).get(line,config.get('pipeline_aliases',{}).get(line,line))
    return WORKSPACE/pattern.format(unit=unit)/(name+'.idf')


def validate_management_transfers(config,unit):
    """A moved support must retain its UCI and exact coordinate in both IDFs."""
    from beihai_geometry import load_model
    paths=configured_paths(config,unit);proofs=[]
    for t in config.get('management_pipeline_transfers',[]):
        if t.get('kind')!='support':raise ValueError('仅支持已核验的支架跨管线归属')
        line=t['drawing_pipeline'];reference=reference_idf_path(config,unit,line)
        if not reference or not reference.is_file():raise ValueError('跨管线支架缺少编号表对应的参考IDF')
        current=paths['idf_dir']/(config.get('pipeline_aliases',{}).get(line,line)+'.idf')
        for file,offset in [(reference,config.get('weld_reference_coordinate_offset_mm')),(current,config.get('idf_coordinate_offset_mm'))]:
            model=load_model(file,offset);matches=[c for c in model['components'] if c['code']==150 and c['ref']==t['ref']]
            if len(matches)!=1 or math.dist(matches[0]['ports'][0],t['source_coordinate_mm'])>.1:
                raise ValueError(f'跨管线支架 {t["ref"]} 未同时通过新旧IDF的UCI及坐标核验')
        proofs.append(dict(t,reference_idf=str(reference),current_idf=str(current)))
    return proofs


def validate_coordinate_frame(config,idf_dir,table_dir,unit):
    """Verify an explicitly configured translation using independent support UCIs.

    Never estimate a translation from nearest welds or silently correct outliers.
    At least three distinct anchors on two pipelines and 90% agreement required.
    """
    offset=config.get('idf_coordinate_offset_mm')
    if offset is None:return None
    from audit_pdms_export import read_csv,coordinate
    from beihai_geometry import load_model
    from pathlib import Path
    rows=remap_rows(read_csv(Path(table_dir)/'支架表.csv')[0],
                    {**config.get('pipeline_aliases',{}),**config.get('table_pipeline_aliases',{})})
    models={};anchors={}
    for row in rows:
        if row.get('单元号')!=unit:continue
        line=row['管线号'];ref=row.get('UCI','').lstrip('=');q=coordinate(row.get('支架坐标',''))
        path=Path(idf_dir)/(config.get('pipeline_aliases',{}).get(line,line)+'.idf')
        if not q or not re.fullmatch(r'\d+/\d+',ref) or not path.is_file():continue
        if line not in models:models[line]=load_model(path,offset)
        components=[c for c in models[line]['components'] if c['ref']==ref and c['code']==150]
        if len(components)!=1:continue
        key=(line,ref)
        if key in anchors and math.dist(q,anchors[key]['table_coordinate_mm'])>.1:
            raise ValueError('坐标转换校验遇到同UCI不同坐标：'+ref)
        gap=math.dist(q,components[0]['ports'][0])
        anchors[key]={'pipeline':line,'ref':ref,'table_coordinate_mm':q,'residual_mm':gap}
    valid=[a for a in anchors.values() if a['residual_mm']<=1]
    if len(valid)<3 or len({a['pipeline'] for a in valid})<2 or len(valid)<.9*len(anchors):
        raise ValueError(f'配置的IDF坐标平移未通过独立UCI校验：{len(valid)}/{len(anchors)}')
    return {'offset_mm':offset,'anchor_count':len(anchors),'agreeing_anchors':len(valid),
            'agreeing_pipelines':len({a['pipeline'] for a in valid}),'anchors':list(anchors.values())}


def verify_alias(drawing,source,model,pages,rows,require_idf_identity=False,expected_idf_identity=None,reference_model=None):
    """Accept only a configured alias corroborated by all entity UCIs and welds."""
    from audit_pdms_export import coordinate
    identity=[r['text'].strip().lstrip('/') for r in model['data']['logical_records'] if r['code']==-6]
    expected=expected_idf_identity or source
    if require_idf_identity and identity!=[expected]:
        raise ValueError(f'名称映射要求IDF内部管线号 {expected}，实际为：{identity}')
    entity_refs={c['ref'] for c in model['components'] if c['code'] not in (110,115) and re.fullmatch(r'\d+/\d+',c['ref'] or '')}
    hit_refs={h['ref'] for page in pages.values() for h in page['hits']}
    if not entity_refs or not entity_refs<=hit_refs:
        raise ValueError(f'名称映射 {drawing} -> {source} 的实体UCI未全部在HIT中匹配')
    ports=[p for c in model['components'] for p in c['ports']]
    maximum=0.
    for row in rows:
        query=coordinate(row['焊点位置'])
        if query is None:raise ValueError('名称映射来源焊口坐标缺失')
        gap=min(math.dist(query,p) for p in ports)
        for c in model['components']:
            if c['code'] not in (100,101) or len(c['ports'])!=2:continue
            a,b=c['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
            f=sum((query[k]-a[k])*v[k] for k in range(3))/n if n else -1
            if 0<f<1:gap=min(gap,math.dist(query,[a[k]+f*v[k] for k in range(3)]))
        maximum=max(maximum,gap)
        if gap>1:
            if reference_model is None:raise ValueError(f'名称映射来源焊口 {row["焊点编号"]} 距模型 {gap:g}mm，停止自动关联')
            reference_proof=verify_alias(drawing,source,reference_model,pages,rows,True)
            return {'drawing_pipeline':drawing,'source_pipeline':source,'entity_uci_count':len(entity_refs),
                    'idf_pipeline_identity':identity,'coordinate_identity_reference':reference_proof,
                    'method':'current-and-source-IDF-entities-all-in-HIT-source-IDF-all-weld-coordinates'}
    return {'drawing_pipeline':drawing,'source_pipeline':source,'entity_uci_count':len(entity_refs),
            'weld_rows_checked':len(rows),'maximum_model_distance_mm':maximum,
            'idf_pipeline_identity':identity,'excluded_auxiliary_codes':[110,115]}


def verify_configured_alias(config,unit,drawing,source,model,pages,rows):
    """Validate confirmed renames against both versions without waiving geometry checks."""
    reference=None
    confirmed=config.get('confirmed_pipeline_renames',{}).get(drawing)==source
    if confirmed:
        path=reference_idf_path(config,unit,drawing)
        if path and path.is_file():
            from beihai_geometry import load_model
            reference=load_model(path,config.get('weld_reference_coordinate_offset_mm'))
    return verify_alias(drawing,source,model,pages,rows,
                        require_idf_identity=drawing in config.get('table_pipeline_aliases',{}),
                        expected_idf_identity=drawing if confirmed else None,reference_model=reference)


def verify_filename_alias(drawing,source,model,idf_filename):
    """Verify slash-only filename substitutions from the IDF's own identity.

    This proves naming identity only. All weld coordinates and component UCIs
    still go through ordinary association; a version difference is not waived.
    """
    identity=[r['text'].strip().lstrip('/') for r in model['data']['logical_records'] if r['code']==-6]
    if len(identity)!=1 or '/' not in identity[0]:
        raise ValueError('文件名转换缺少唯一且含斜杠的IDF内部管线号')
    name=identity[0];variants={name,name.replace('/',''),name.replace('/','-')}
    if not {drawing,source,idf_filename}<=variants:
        raise ValueError(f'文件名转换超出斜杠替换规则：{drawing} / {source} / {idf_filename} / {name}')
    return {'drawing_pipeline':drawing,'source_pipeline':source,'idf_pipeline_identity':identity,
            'idf_filename':idf_filename,'identity_verified':True,'normalization_variants':sorted(variants),
            'method':'IDF-internal-identity-slash-only-filename-normalization'}
