"""Publish verified weld recoveries; preserve every existing PDF root and source."""
from pathlib import Path
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import copy,hashlib,json,math,os,shutil,sys,tempfile,time
from openpyxl import Workbook
from openpyxl.styles import Alignment
REPO=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(REPO/'profiles/beihai/parser'),str(REPO/'profiles/beihai/workflow')]
from project_paths import AUDIT
from beihai_unit_profile import unit_config,configured_paths,remap_rows,hit_file,verify_configured_alias,verify_filename_alias
from beihai_geometry import load_model,load_page
from audit_pdms_export import read_csv
from audit_beihai_inputs import main as input_audit
from beihai_page_jobs import render_page_job
from beihai_resource_monitor import ResourceMonitor
from beihai_review_report import reviewer_workbook,save_internal_audit,audit_path
from convert_beihai_plt_to_pdf import style_workbook
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
 import argparse
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--unit',required=True);ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--preflight',type=Path,required=True);ap.add_argument('--evidence-dir',type=Path,required=True);args=ap.parse_args()
 started=time.monotonic();folder=args.evidence_dir.resolve();folder.mkdir(parents=True,exist_ok=True);unit=args.unit;config=unit_config(unit);paths=configured_paths(config,unit)
 baseline_path=args.baseline.resolve();base=json.loads(baseline_path.read_text(encoding='utf-8'))
 preflight_path=args.preflight.resolve();current=json.loads(preflight_path.read_text(encoding='utf-8'))
 assert base['metadata']['complete'] and current['regression_passed']
 assert current.get('publication_accepted') is not False,'试验轮语义审核未通过，禁止发布'
 assert base['metadata']['annotation_kinds']==['weld','support'] and config['management_kinds']==['support'] and not config['spool_annotations']
 assert config['page_workers']==8 and config['font_height_mm']==6 and config['weld_diameter_mm']==12
 all_targets=current['mapped']+current['management_mapped'];by_page=defaultdict(list)
 for t in all_targets:by_page[t['page_stem']].append(t)
 baseline_positions={(r[0],r[1],str(r[2])):(r[5],r[6]) for r in base['sheets']['标注定位清单'][1:]}
 positions={(t['page_stem'],'焊口' if t['kind']=='weld' else '支架',str(t['number'])):(t['x_mm'],t['y_mm']) for t in all_targets}
 verified={(c['new']['page_stem'],'焊口',str(c['new']['number'])):c for c in current.get('verified_previous_changes',[])}
 assert not current.get('unexpected_previous_changes') and not current.get('unused_verified_corrections')
 for k,v in baseline_positions.items():
  assert k in positions
  if math.dist(v,positions[k])<1e-6:continue
  assert k in verified and math.dist(v,[verified[k]['old']['x_mm'],verified[k]['old']['y_mm']])<1e-6
  assert math.dist(positions[k],[verified[k]['new']['x_mm'],verified[k]['new']['y_mm']])<1e-6
 original_rows={r[3] for r in base['sheets']['标注定位清单'][1:] if r[1]=='焊口'}
 recovered=[t for t in current['mapped'] if t['source_row'] not in original_rows]
 recovered_support=[t for t in current['management_mapped'] if (t['page_stem'],'支架',str(t['number'])) not in baseline_positions]
 assert not recovered_support or current.get('management_audit'),'新增支架缺少完整逐行核对记录'
 corrected=[c['new'] for c in current.get('verified_previous_changes',[])
            if math.dist(baseline_positions[(c['new']['page_stem'],'焊口',str(c['new']['number']))],
                         [c['new']['x_mm'],c['new']['y_mm']])>1e-6]
 changed={t['page_stem'] for t in recovered+recovered_support+corrected}
 plts={p.stem:p for p in paths['input_dir'].rglob('*.plt')};assert len(plts)==len(base['page_stats'])
 out=Path(base['metadata']['pdf_dir']);assert {p.stem for p in out.glob('*.pdf')}==set(plts)
 original_hashes={stem:sha(out/(stem+'.pdf')) for stem in plts}
 source_paths=set(paths['input_dir'].rglob('*.plt'))|set(paths['input_dir'].rglob('*.hit'))|set(paths['idf_dir'].glob('*.idf'))
 reference=config.get('weld_reference_idf_pattern')
 if reference:source_paths.update((REPO.parent/reference.format(unit=unit)).glob('*.idf'))
 if paths['hit_dir']:source_paths.update(paths['hit_dir'].glob('*.hit'))
 source_paths.update([REPO.parent/'北海项目/焊口表.csv',REPO.parent/'北海项目/支架表.csv',REPO/'profiles/beihai/config.json',REPO/'profiles/beihai/units'/(unit+'.json')])
 manifest=[]
 for path in sorted(source_paths):
  manifest.append({'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size})
 (folder/'publication_source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 published=json.loads(audit_path(unit).read_text(encoding='utf-8'))
 assert published['sheets']['标注定位清单']==base['sheets']['标注定位清单'],'当前发布结果与基准不一致'
 stats={x['stem']:x for x in base['page_stats']};assert set(stats)==set(plts)
 new_stats={};performance=AUDIT/'performance'/(unit+'_recovered_pages_workers8.json')
 print('Rendering',len(changed),'pages; reusing',len(plts)-len(changed),'verified pages; workers 8',flush=True)
 with tempfile.TemporaryDirectory(prefix=unit+'_recovery_') as tmp,ResourceMonitor(performance,8) as monitor,ProcessPoolExecutor(max_workers=8) as pool:
  stage=Path(tmp);jobs={pool.submit(render_page_job,{'plt_path':str(plts[stem]),'targets':by_page[stem],'config':config,'stage':str(stage)}):stem for stem in sorted(changed)}
  for future in as_completed(jobs):
   stem=jobs[future];result=future.result();assert result['pdf_verified'] and not result['conflicts'],(stem,result['conflicts'])
   new_stats[stem]=result;print('Verified recovered page',stem,result['elapsed_seconds'],flush=True)
  for item in manifest:assert sha(Path(item['path']))==item['sha256'],('输入处理中发生变化',item['path'])
  for stem in changed:shutil.copy2(stage/'pdfs'/(stem+'.pdf'),out/(stem+'.pdf'))
 stats.update(new_stats)
 for stem in set(plts)-changed:assert sha(out/(stem+'.pdf'))==original_hashes[stem]
 record=copy.deepcopy(base);sheets=record['sheets'];mapping=sheets['标注定位清单']
 aliases=config.get('pipeline_aliases',{});table_aliases={**aliases,**config.get('table_pipeline_aliases',{})}
 if table_aliases!=base['metadata'].get('table_pipeline_aliases',{}) or config.get('weld_pipeline_transfers',[])!=base['metadata'].get('weld_pipeline_transfers',[]):
  audit_args=['--input-dir',str(paths['input_dir']),'--idf-dir',str(paths['idf_dir']),'--weld-table',str(REPO.parent/'北海项目/焊口表.csv')]
  if paths['hit_dir']:audit_args+=['--hit-dir',str(paths['hit_dir'])]
  refreshed=input_audit(audit_args,save=False,pipeline_aliases=aliases,table_aliases=table_aliases,model_offset_mm=config.get('idf_coordinate_offset_mm'),weld_transfers=config.get('weld_pipeline_transfers'))
  for sheet in refreshed:sheets[sheet.title]=[list(row) for row in sheet.values]
  rows=remap_rows(read_csv(REPO.parent/'北海项目/焊口表.csv')[0],table_aliases,config.get('weld_pipeline_transfers'))
  record['metadata']['alias_evidence']=[]
  for line,source in table_aliases.items():
   model=load_model(paths['idf_dir']/(aliases.get(line,line)+'.idf'),config.get('idf_coordinate_offset_mm'))
   if config.get('filename_aliases_only') and line not in config.get('confirmed_pipeline_renames',{}):proof=verify_filename_alias(line,source,model,aliases.get(line,line))
   else:
    pages={p.stem:load_page(p,hit_file(p,paths['hit_dir'])) for p in paths['input_dir'].rglob(line+'_Sht_*.plt')}
    proof=verify_configured_alias(config,unit,line,source,model,pages,[r for r in rows if r['管线号']==line])
   record['metadata']['alias_evidence'].append(proof)
 record['metadata'].update(pipeline_aliases=aliases,table_pipeline_aliases=table_aliases,weld_pipeline_transfers=config.get('weld_pipeline_transfers',[]),management_pipeline_transfers=config.get('management_pipeline_transfers',[]))
 corrected_by_row={t['source_row']:t for t in corrected}
 for row in mapping[1:]:
  if row[1]=='焊口' and row[3] in corrected_by_row:
   t=corrected_by_row[row[3]];row[0]=t['page_stem'];row[5:8]=[t['x_mm'],t['y_mm'],t['mapping_method']]
 for t in recovered+recovered_support:
  mapping.append([t['page_stem'],'焊口' if t['kind']=='weld' else '支架',t['number'],t['source_row'],str(t.get('coordinate_mm','')),t['x_mm'],t['y_mm'],t['mapping_method'],t.get('related_weld',''),t.get('ref',''),t.get('source_file','焊口表.csv'),','.join(str(n) for n in t.get('source_rows',[t['source_row']]))])
 if 'management_audit' in current:
  sheets['管理编号逐行核对']=sheets['管理编号逐行核对'][:1]+current['management_audit']
 issues=sheets['未标注编号'][:1]
 for entry in current['unresolved']:
  t=entry['target'];issues.append([t['pipeline'],t['source_table_page'],'焊口',t['number'],entry['diagnosis']['reason'],str(t['coordinate_mm']),t['source_row']])
 issues.extend(current['management_unresolved']);sheets['未标注编号']=issues
 for t in recovered+corrected:
  notes=t.get('review_notes',[])
  if notes:sheets['自动匹配需审核'].append([t['page_stem'],t['page_stem'].rsplit('_Sht_',1)[1],'焊口',t['number'],t['mapping_method'],t.get('ref',''),json.dumps(notes,ensure_ascii=False)])
 for t in recovered_support:
  transfers=[d for d in config.get('management_pipeline_transfers',[]) if d['source_row'] in t.get('source_rows',[t['source_row']])]
  if transfers:sheets['自动匹配需审核'].append([t['page_stem'],t['page_stem'].rsplit('_Sht_',1)[1],'支架',t['number'],t['mapping_method'],t['ref'],'支架元件已转入另一管线；按原表UCI、坐标与新旧IDF及HIT核验，保留来源行：'+json.dumps(transfers,ensure_ascii=False)])
 header=sheets['单页转换结果'][0];rows={r[0]:r for r in sheets['单页转换结果'][1:]}
 for stem,result in new_stats.items():
  counts=result['counts'];rows[stem]=[stem,stem+'.pdf',counts.get('weld',0),0,result['mode'],0,'通过：单页、图幅及标注编号一致',result['elapsed_seconds'],0,0,counts.get('support',0)]
 sheets['单页转换结果']=[header]+[rows[stem] for stem in sorted(rows)]
 updates={'来源焊口':len(current['mapped'])+len(current['unresolved']),'已定位焊口':len(current['mapped']),'未定位焊口':len(current['unresolved']),'支架已标注':len(current['management_mapped']),'支架未标注':len({(r[0],r[3]) for r in current['management_unresolved']}),'未标注清单记录数':len(issues)-1,'自动匹配审核记录数':len(sheets['自动匹配需审核'])-1}
 elapsed=round(time.monotonic()-started,2);initial_elapsed=next(r[1] for r in sheets['本次转换汇总'] if r[0]=='耗时秒')
 for row in sheets['本次转换汇总']:
  if row[0] in updates:row[1]=updates[row[0]]
  if row[0]=='耗时秒':row[1]=round(initial_elapsed+elapsed,2);row[2]='首轮全量转换与最终复绘的累计用时，不含多轮关联预检'
 for row in sheets['本次转换汇总']:
  if row[0]=='最终复绘页数':row[1:]=[len(changed),'本轮受影响页面联合布局复绘']
  if row[0]=='已验证复用页数':row[1:]=[len(plts)-len(changed),'复用页面SHA256保持不变']
 metadata=record['metadata'];metadata['source_drawing_issues']=current.get('source_drawing_issues',metadata.get('source_drawing_issues',[]));metadata['report_coincident_welds']=True;metadata['weld_interface_evidence']=[{k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','interface_identity_evidence')} for t in current['mapped'] if t.get('interface_identity_evidence')]
 metadata['weld_reference_evidence']=[{k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','reference_geometry_evidence')} for t in current['mapped'] if t.get('reference_geometry_evidence')]
 metadata['weld_topology_evidence']=[{k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','native_topology_evidence')} for t in current['mapped'] if t.get('native_topology_evidence')]
 metadata['weld_singleton_evidence']=[{k:t[k] for k in ('pipeline','number','source_row','page_stem','x_mm','y_mm','coordinate_mm','mapping_evidence')} for t in current['mapped'] if t['mapping_method']=='beihai-single-pipe-single-native-axis-free-end']
 if changed:
  metadata.setdefault('initial_full_conversion_performance',metadata['performance']);metadata['performance']=monitor.summary
 metadata['incremental_publication']={'baseline':str(baseline_path),'preflight':str(preflight_path),'redrawn_pages':sorted(changed),'reused_pages':len(plts)-len(changed),'new_welds':len(recovered),'elapsed_seconds':elapsed,'source_manifest':str(folder/'publication_source_manifest.json')}
 wb=Workbook();wb.remove(wb.active)
 for name,content in sheets.items():
  sheet=wb.create_sheet(name)
  for row in content:sheet.append(row)
 save_internal_audit(wb,unit,None,record['valve_centres'],metadata,record.get('spool_roots',[]),[stats[k] for k in sorted(stats)])
 public=reviewer_workbook(wb,metadata);style_workbook(public)
 for sheet in public:
  for col,width in zip('ABCDEFG',(38,8,12,14,64,36,16)):sheet.column_dimensions[col].width=width
  sheet.row_dimensions[1].height=24
  for row in range(2,sheet.max_row+1):
   text=str(sheet.cell(row,5).value or '');units=sum(2 if ord(c)>127 else 1 for c in text);sheet.row_dimensions[row].height=max(42,min(120,14*math.ceil(units/60)+8))
 public.save(paths['input_dir']/f'北海{unit}_标注问题清单.xlsx')
 (folder/'publication_summary.json').write_text(json.dumps({'new_welds':len(recovered),'redrawn_pages':len(changed),'reused_pages':len(plts)-len(changed),'elapsed_seconds':elapsed,'performance':monitor.summary},ensure_ascii=False,indent=2),encoding='utf-8')
 print('PUBLISHED',{'pages':len(plts),'welds':len(current['mapped']),'supports':len(current['management_mapped']),'new_welds':len(recovered),'redrawn_pages':len(changed),'reused_pages':len(plts)-len(changed),'seconds':elapsed,'public_rows':{s.title:s.max_row-1 for s in public}},flush=True)

if __name__=='__main__':main()
