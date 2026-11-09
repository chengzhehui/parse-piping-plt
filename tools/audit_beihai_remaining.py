"""Recheck every residual against reference owners, current ports and paper collisions."""
from pathlib import Path
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor
import json,math,sys,os
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'profiles/beihai/parser'))
from beihai_geometry import load_model,load_page,beihai_candidates,resolve_pipe_interiors
from beihai_reference_recovery import identity_proposals
from beihai_topology_ports import native_ports
from render_complete_pdms import resolve_pipeline
from beihai_unit_profile import unit_config,configured_paths,remap_rows,reference_idf_path,hit_file
from audit_pdms_export import read_csv
from project_paths import WORKSPACE,AUDIT
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'

def run(job):
 c=job['config'];unit=job['unit'];line=job['line'];paths=configured_paths(c,unit);name=c.get('pipeline_aliases',{}).get(line,line)
 reference=reference_idf_path(c,unit,line);current=paths['idf_dir']/(name+'.idf')
 if reference and reference.is_file():old=load_model(reference,c.get('weld_reference_coordinate_offset_mm'))
 else:reference=current;old=load_model(current,c.get('idf_coordinate_offset_mm'))
 new=load_model(current,c.get('idf_coordinate_offset_mm'));pages={p.stem:load_page(p,hit_file(p,paths['hit_dir'])) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')};hits={h['ref'] for page in pages.values() for h in page['hits']}
 old_mapped,old_missing=resolve_pipeline(job['rows'],old,pages,False,beihai_candidates);resolve_pipe_interiors(old_mapped,old_missing,old,pages);oldby={t['source_row']:t for t in old_mapped};results=[]
 for entry in job['missing']:
  t=entry['target'];q=t['coordinate_mm'];owners=[co for co in old['components'] if co['code'] not in (110,115,120,150) and co['ref'] and any(math.dist(q,p)<=1 for p in co['ports'])];numeric=[co for co in owners if not co['ref'].startswith(('HSTU_','LSTU_'))];physical_hit=[co['ref'] for co in numeric if co['ref'] in hits]
  identity=identity_proposals(q,old,new,hits);old_target=oldby.get(t['source_row']);target=None
  if identity:
   row=dict(next(r for r in job['rows'] if r['_row']==t['source_row']),焊点位置=','.join(map(str,identity['coordinate_mm'])))
   mapped,missing=resolve_pipeline([row],new,pages,False,beihai_candidates);resolve_pipe_interiors(mapped,missing,new,pages)
   if len(mapped)==1:target=mapped[0]
  collision=[]
  if target:collision=[o['number'] for o in job['existing'] if o['page_stem']==target['page_stem'] and math.dist([o['x_mm'],o['y_mm']],[target['x_mm'],target['y_mm']])<.25]
  result={'target':t,'reference_idf':str(reference),'current_idf':str(current),'original_diagnosis':entry['diagnosis'],'source_owners':[{k:co[k] for k in ('code','skey','ref','line','ports')} for co in owners],
   'current_owner_evidence':[{'ref':co['ref'],'in_hit':co['ref'] in hits,'current_components':[{k:n[k] for k in ('code','skey','ref','line','ports')} for n in new['components'] if n['ref']==co['ref']]} for co in owners],
   'identity_proposal':identity,'reference_paper_target':old_target,'current_paper_target':target,'collides_with_marked':collision,'native_body_options':[]}
  for co in new['components']:
   if co['code'] in (35,130) and any(math.dist(q,p)<.11 for p in co['ports']):result['native_body_options'].append({'ref':co['ref'],'options':native_ports(co,new,pages)})
  if collision:reason='该来源接口在当前图纸中与已标焊口'+','.join(collision)+'落在同一点；不能据此再指定一个不同焊口号。';category='当前接口与其他编号重合'
  elif numeric and not physical_hit:reason='原表坐标对应的元件UCI '+','.join(co['ref'] for co in numeric)+'未在本批HIT出现；现有资料不能证明替代元件与原焊口编号的关系。';category='原接口实体未在本批HIT出现'
  elif owners and not any(e['current_components'] for e in result['current_owner_evidence']):reason='原接口归属UCI已不在本批IDF中，不能按邻近坐标转移原编号；请确认对应的设计变更或编号表。';category='原接口归属在当前模型失效'
  elif identity and old_target and target and (old_target['page_stem']!=target['page_stem'] or math.dist([old_target['x_mm'],old_target['y_mm']],[target['x_mm'],target['y_mm']])>.25):reason='参考IDF与当前IDF推导的图页或端口位置不一致；两种依据冲突，需要确认同期图表及接口。';category='新旧模型的图纸端口依据冲突'
  elif identity and old_target and target:reason='纸面候选已取得，待同批候选重复性检查。';category='待检查同点候选'
  elif entry['diagnosis']['category']=='编号表坐标未匹配本批IDF' and owners:reason='原表坐标能对应参考IDF，但当前元件归属、端口方向或分段关系已变化，未能建立唯一的同一接口关系；请确认版本或变更后的焊口对应。';category='图表版本接口关系不能唯一对应'
  else:reason=entry['diagnosis']['reason'];category=entry['diagnosis']['category']
  result.update(category=category,reason=reason);results.append(result)
 return results

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--unit',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--workers',type=int,default=4);parser.add_argument('--out-preflight',type=Path)
 args=parser.parse_args();c=unit_config(args.unit);pre=json.loads(args.preflight.read_text(encoding='utf-8'))
 assert pre['unit']==args.unit and pre['regression_passed'],'先完成无非预期变更的关联预检'
 rows=remap_rows(read_csv(WORKSPACE/'北海项目/焊口表.csv')[0],{**c.get('pipeline_aliases',{}),**c.get('table_pipeline_aliases',{})},c.get('weld_pipeline_transfers'));groups=defaultdict(list)
 for entry in pre['unresolved']:groups[entry['target']['pipeline']].append(entry)
 jobs=[{'unit':args.unit,'config':c,'line':line,'rows':[r for r in rows if r['管线号']==line],'missing':entries,'existing':[t for t in pre['mapped'] if t['pipeline']==line]} for line,entries in sorted(groups.items())];results=[]
 with ProcessPoolExecutor(max_workers=args.workers) as pool:
  for i,result in enumerate(pool.map(run,jobs),1):
   results.extend(result)
   if i%10==0 or i==len(jobs):print('AUDIT',i,'/',len(jobs),flush=True)
 candidates=[e for e in results if e['category']=='待检查同点候选']
 for entry in candidates:
  target=entry['current_paper_target'];duplicates=[o['target']['number'] for o in candidates if o is not entry and o['current_paper_target']['page_stem']==target['page_stem'] and math.dist([o['current_paper_target']['x_mm'],o['current_paper_target']['y_mm']],[target['x_mm'],target['y_mm']])<.25]
  if duplicates:entry.update(category='多个旧焊口合并为一个当前接口',reason='本条与旧焊口'+','.join(duplicates)+'均对应当前同一端口，无法唯一确定应保留的焊口号；请确认取消、合并或重新编号。',collides_with_unmarked=duplicates)
 summary={'remaining':len(results),'categories':dict(Counter(e['category'] for e in results)),'safe_unhandled_candidates':sum(e['category']=='待检查同点候选' for e in results)}
 folder=AUDIT/'all_units'/args.unit;folder.mkdir(parents=True,exist_ok=True)
 audit=folder/(pre['revision']+'_remaining_audit.json');audit.write_text(json.dumps({'summary':summary,'rows':results},ensure_ascii=False,indent=2),encoding='utf-8')
 if args.out_preflight:
  by_row={e['target']['source_row']:e for e in results};assert len(by_row)==len(pre['unresolved'])
  for entry in pre['unresolved']:
   result=by_row[entry['target']['source_row']];entry['diagnosis']={'category':result['category'],'reason':result['reason']};entry['exhaustive_audit']=result
  pre['association_preflight']=str(args.preflight.resolve());pre['revision']+='_audited';pre['residual_audit_summary']=summary;pre['residual_audit_file']=str(audit.resolve())
  args.out_preflight.write_text(json.dumps(pre,ensure_ascii=False,indent=2),encoding='utf-8')
 print('SUMMARY',summary,flush=True)
 raise SystemExit(2 if summary['safe_unhandled_candidates'] else 0)
