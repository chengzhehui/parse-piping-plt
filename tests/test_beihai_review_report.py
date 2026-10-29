"""Regression: the delivered workbook exposes actions, not the audit trail."""
from pathlib import Path
import unittest
from openpyxl import load_workbook
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'profiles/beihai/parser'))
from project_paths import REPOSITORY, WORKSPACE, ARCHIVE, AUDIT

from beihai_review_report import reviewer_workbook


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


if __name__=='__main__':unittest.main()
