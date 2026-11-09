"""Regression: the delivered workbook exposes actions, not the audit trail."""
from pathlib import Path
import unittest
from openpyxl import load_workbook,Workbook
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from beihai_review_report import reviewer_workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from report_beihai_reconciliation import management_pending_diagnosis


class ReviewerReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ARCHIVE/'beihai_audit/previous_reports/before_valve_center_fix_北海PD60_标注问题清单.xlsx'
        cls.audit=load_workbook(path,read_only=True)
        cls.public=reviewer_workbook(cls.audit)

    @classmethod
    def tearDownClass(cls):cls.audit.close()

    def test_only_actionable_sheets_and_rows(self):
        self.assertEqual(self.public.sheetnames,['未标注编号','已标注需核对'])
        self.assertEqual(self.public['未标注编号'].max_row-1,3)
        self.assertEqual(self.public['已标注需核对'].max_row-1,16)

    def test_resolved_and_routine_matching_not_sent_to_reviewers(self):
        text='\n'.join(str(v) for sheet in self.public for row in sheet.values for v in row)
        for routine in ('同号同位置合并','候选位置','按元件方向及符号规则','elapsed_seconds','mapping_method'):
            self.assertNotIn(routine,text)
        self.assertNotIn('PDMS导出问题',self.public.sheetnames)

    def test_remaining_concrete_issues_and_source_rows_preserved(self):
        rows=list(self.public['未标注编号'].values)[1:]
        self.assertEqual({(r[2],str(r[3])) for r in rows},{('焊口','12'),('法兰','FL4'),('法兰','FL5')})
        self.assertTrue(all(r[6] for r in rows))
        self.assertTrue(all(r[4] and r[5] and r[6] for r in list(self.public['已标注需核对'].values)[1:]))

    def test_missing_management_ref_does_not_claim_model_contains_it(self):
        diagnosis=management_pending_diagnosis('支架','UCI在当前HIT中缺失：123/456',[])
        self.assertIn('IDF中也未找到',diagnosis['reason'])
        self.assertNotIn('IDF中存在',diagnosis['reason'])
        self.assertIn('IDF中存在',management_pending_diagnosis('支架','UCI在当前HIT中缺失：123/456',[{'ref':'123/456'}])['reason'])

    def test_identical_management_issues_merge_source_rows_only(self):
        wb=Workbook();sheet=wb.active;sheet.title='未标注编号';sheet.append(list('ABCDEFG'))
        sheet.append(['PIPE','1','支架','SP1','UCI缺失','0,0,0',10])
        sheet.append(['PIPE','1','支架','SP1','UCI缺失','0,0,0',20])
        sheet.append(['PIPE','1','支架','SP1','UCI缺失','1,0,0',30])
        wb.create_sheet('标注定位清单').append(list('ABCDEFGHIJKL'))
        wb.create_sheet('自动匹配需审核').append(list('ABCDEFG'))
        public=reviewer_workbook(wb)['未标注编号']
        self.assertEqual(public.max_row,3)
        self.assertEqual(public.cell(2,7).value,'10,20')
        self.assertEqual(public.cell(3,7).value,30)

    def test_mapped_duplicate_review_retains_every_source_row(self):
        wb=Workbook();wb.active.title='未标注编号';wb.active.append(list('ABCDEFG'))
        mapping=wb.create_sheet('标注定位清单');mapping.append(list('ABCDEFGHIJKL'))
        mapping.append(['PIPE_Sht_1','支架','SP1',10,'0,0,0',5,5,'coincident-support-surviving-UCI-merged','','1/2;1/3','支架表.csv','10,20'])
        review=wb.create_sheet('自动匹配需审核');review.append(list('ABCDEFG'))
        review.append(['PIPE_Sht_1','1','支架','SP1','coincident-support-surviving-UCI-merged','1/2;1/3','同号同坐标重复记录含失效UCI'])
        self.assertEqual(reviewer_workbook(wb)['已标注需核对'].cell(2,7).value,'10,20')

    def test_interface_migration_without_symbol_gets_priority_review(self):
        import json
        wb=Workbook();wb.active.title='未标注编号';wb.active.append(list('ABCDEFG'))
        mapping=wb.create_sheet('标注定位清单');mapping.append(list('ABCDEFGHIJKL'))
        mapping.append(['PIPE_Sht_1','焊口','2',10,'0,0,0',5,5,'stable-component-interface:test','','','焊口表.csv','10'])
        review=wb.create_sheet('自动匹配需审核');review.append(list('ABCDEFG'))
        review.append(['PIPE_Sht_1','1','焊口','2','stable-component-interface:test','',json.dumps([{'reason':'新旧IDF接口坐标不一致'}],ensure_ascii=False)])
        metadata={'weld_interface_evidence':[{'page_stem':'PIPE_Sht_1','number':'2','interface_identity_evidence':{'native_weld_glyph':False}}]}
        result=reviewer_workbook(wb,metadata)['已标注需核对']
        self.assertIn('无独立焊口符号',result.cell(2,5).value)
        self.assertEqual(result.cell(2,7).value,10)


if __name__=='__main__':unittest.main()
