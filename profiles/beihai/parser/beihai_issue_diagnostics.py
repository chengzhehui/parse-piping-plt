"""Explain an unresolved model-to-paper association using inspectable evidence."""
import math
import re


def unmatched_coordinate_diagnosis(distance):
    return {'category':'编号表坐标未匹配本批IDF',
            'reason':f'焊口表坐标未匹配本批IDF端点或直管内部（最近端点距离{distance:.2f}mm）；请核对编号表与IDF版本及设计变更。',
            'nearest_model_port_mm':distance}


def paper_diagnosis(target,model,pages,candidate_resolver):
    query=target['coordinate_mm'];components=model['components']
    refs={c['ref'] for c in components};hits={h['ref'] for p in pages.values() for h in p['hits']}
    near=[c for c in components if any(math.dist(query,p)<1 for p in c['ports'])]
    for socket in components:
        if socket['code']!=126 or socket.get('skey')!='NRSC' or len(socket['ports'])!=2 or socket['ref'] not in hits:continue
        a,b=socket['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
        f=sum((query[k]-a[k])*v[k] for k in range(3))/n if n else -1
        if not 0<f<1 or math.dist(query,[a[k]+f*v[k] for k in range(3)])>.11:continue
        inserted=[c for c in near if c['code'] in (100,101) and len(c['ports'])==2 and
                  any(math.dist(p,s)<.11 for p in c['ports'] for s in socket['ports'])]
        if inserted:
            return {'category':'承插插入段端点缺少独立焊口依据',
                    'reason':'该编号位于IDF承插插入短管的内端，坐标处在相邻NRSC元件内部；原图可核定元件实际端部，但不能证明此处另有独立焊口。请核对插入段分段及焊口编号关系。',
                    'socket_ref':socket['ref'],'socket_idf_line':socket['line'],'pipe_refs':[c['ref'] for c in inserted]}
    missing=[c for c in near if c['code'] not in (100,101,150) and c['ref'] and c['ref'] not in hits]
    if missing:
        labels={105:'法兰',35:'弯头',40:'支管接口',45:'三通',130:'阀门'}
        names='、'.join(dict.fromkeys(labels.get(c['code'],'元件') for c in missing))
        return {'category':'IDF邻接元件UCI未在原图HIT中出现',
                'reason':f'IDF邻接{names}UCI未在本批HIT中出现（{missing[0]["ref"]}）；缺少唯一原图焊接端依据，请核对同期IDF/焊口表或确认是否省略该接口。',
                'missing_components':[{k:c[k] for k in ('code','ref','line','ports')} for c in missing]}
    for component in components:
        if component['code'] not in (100,101) or len(component['ports'])!=2:continue
        a,b=component['ports'];v=[b[k]-a[k] for k in range(3)];n=sum(x*x for x in v)
        fraction=sum((query[k]-a[k])*v[k] for k in range(3))/n if n else -1
        if not 0<fraction<1 or math.dist(query,[a[k]+fraction*v[k] for k in range(3)])>.1:continue
        bends=[h for page in pages.values() for h in page['hits'] if h['ref']==component['ref'] and re.match(r'^BEND\b',h['name'])]
        if bends:
            return {'category':'IDF直管与原图BEND类型不一致',
                    'reason':'该焊口坐标落在IDF直管内部，但同UCI在原图HIT中为BEND；当前IDF缺少实际曲线数据，不能按直线长度推定焊口。请补充同期弯管模型或人工核定。',
                    'pipe_ref':component['ref'],'idf_line':component['line'],'bend_hits':bends}
        ends=[candidate_resolver({'coordinate_mm':p},model,pages) for p in (a,b)]
        if all(ends):
            ca,cb=ends[0][0],ends[1][0]
            if ca['page_stem']!=cb['page_stem']:
                return {'category':'跨页直管缺少可核对的分图坐标',
                    'reason':'同一IDF直管的两端位于不同图页，当前IDF没有可核对的分图坐标；请提供对应split ATTA/同期分图数据，以确定焊口归属页和局部位置。',
                    'pipe_ref':component['ref'],'idf_line':component['line'],
                    'terminal_pages':[ca['page_stem'],cb['page_stem']],'idf_split_count':len(model['data']['splits'])}
            pa=(ca['x_mm'],ca['y_mm']);pb=(cb['x_mm'],cb['y_mm']);length=math.dist(pa,pb)
            if length<1:continue
            u=[(pb[k]-pa[k])/length for k in (0,1)];added=[]
            for hit in pages[ca['page_stem']]['hits']:
                d=(hit['x_mm']-pa[0],hit['y_mm']-pa[1]);along=d[0]*u[0]+d[1]*u[1]
                if hit['ref'] not in refs and re.match(r'^(?:FLANGE|VALVE|TEE|ELBOW|OLET|FBLIND)\b',hit['name']) and \
                   0<along<length and abs(d[0]*u[1]-d[1]*u[0])<.5:added.append(hit)
            if added:
                return {'category':'IDF直管在原图中被新增元件打断',
                    'reason':'原图在该IDF直管两端之间绘有IDF未包含的阀门/法兰组，不能沿整段直管插值；请同步模型与焊口表后确认本焊口。',
                    'pipe_ref':component['ref'],'idf_line':component['line'],
                    'page_stem':ca['page_stem'],'added_hit_components':added}
            from beihai_geometry import native_axis_covers
            axes=[]
            for first in ends[0]:
                for second in ends[1]:
                    if first['page_stem']!=second['page_stem']:continue
                    a2=(first['x_mm'],first['y_mm']);b2=(second['x_mm'],second['y_mm'])
                    if native_axis_covers(pages[first['page_stem']],a2,b2):axes.append([first,second])
            return {'category':'管内焊口缺少唯一连续管轴' if not axes else '管内焊口存在多组模型或端点依据',
                'reason':('IDF直管两端均有图纸候选，但候选之间未形成可核对的连续管线；请核对管端、虚线/断线符号及图模版本。' if not axes else
                          '存在可用管线候选，但当前模型或端点组合不能唯一确定本管内焊口；请核对重叠管子及分段位置。'),
                'pipe_ref':component['ref'],'idf_line':component['line'],
                'terminal_candidate_counts':[len(e) for e in ends],'native_axis_pairs':axes}
        return {'category':'直管缺少可靠的两端纸面控制点',
            'reason':'该管内焊口至少一端未取得可靠的图纸控制点；请核对端部元件UCI、端口符号及同批图模资料。',
            'pipe_ref':component['ref'],'idf_line':component['line'],
            'terminal_candidate_counts':[len(e) for e in ends]}
    distance=min((math.dist(query,p) for c in components for p in c['ports']),default=None)
    if distance is not None and distance>1:return unmatched_coordinate_diagnosis(distance)
    families={105:'法兰',107:'盲法兰',130:'阀门',126:'短节',95:'承插短节',40:'支管接口',45:'三通',35:'弯头'}
    for code,label in families.items():
        matched=[c for c in near if c['code']==code and c['ref'] in hits]
        if matched:
            c=matched[0]
            return {'category':label+'端口未能唯一还原',
                'reason':f'已找到{label}UCI {c["ref"]}（{c.get("skey","")}），但当前端口规则未取得唯一的原图焊接端依据；请核对实际连接端、图纸投影及图模版本，或人工核定位置。',
                'matched_components':[{k:c[k] for k in ('code','ref','line','ports','skey')} for c in matched]}
    if not hits:return {'category':'管线HIT无实体控制点',
        'reason':'本管线HIT没有可用实体记录，当前定位方法缺少模型与图纸的关联控制点；请结合原图坐标人工核定或补充同批索引。'}
    if any(c['code'] in (100,101,120) for c in near):return {'category':'管端缺少唯一图纸控制点',
        'reason':'模型中存在该管端，但未取得唯一的原图端点或连续管线依据；请结合原图管端坐标及同批图模核对，或人工核定。'}
    return {'category':'纸面依据不足','reason':'当前规则未找到唯一且有原图几何依据的纸面定位；请核对图模版本及对应图元。'}
