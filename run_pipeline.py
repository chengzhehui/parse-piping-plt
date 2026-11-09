"""Convert supplied PDMS IDF/PLT/HIT and optional numbering CSVs to single-page PDFs."""
from pathlib import Path
import argparse
import csv
import os
import subprocess
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir','--plt-dir',dest='input_dir',type=Path,required=True,help='PLT目录，递归读取；文件名为 管线号_Sht_页码.plt')
    parser.add_argument('--idf-dir',type=Path,required=True,help='按管线号命名的IDF目录')
    parser.add_argument('--hit-dir',type=Path,help='独立HIT目录；省略时读取PLT旁同名HIT')
    parser.add_argument('--weld-table',type=Path,help='焊口CSV；省略时只标注管理编号或仅还原原图')
    parser.add_argument('--management-tables-dir',type=Path,help='包含支架表.csv、阀门表.csv、法兰表.csv的目录，仅读取存在的文件')
    for kind,label in [('support','支架'),('valve','阀门'),('flange','法兰')]:
        parser.add_argument('--'+kind+'-table',type=Path,help=label+'CSV，覆盖表格目录内的同类文件')
    parser.add_argument('--out-dir',type=Path,required=True,help='输出目录，包含PDF子目录、问题清单及.audit运行证据')
    parser.add_argument('--unit',help='可选，仅筛选管理表的指定单元；不加载北海历史配置')
    parser.add_argument('--pipeline',help='可选，仅转换指定管线')
    parser.add_argument('--workers',type=int,default=8,help='按页工作进程数，默认8')
    parser.add_argument('--spool',action='store_true',help='按焊口表管段编号增加管段标注')
    args=parser.parse_args(argv)
    if args.workers<1:parser.error('--workers 必须大于等于1')
    if args.spool and not args.weld_table:parser.error('--spool 需要 --weld-table')
    for name in ('input_dir','idf_dir','hit_dir','management_tables_dir'):
        value=getattr(args,name)
        if value is not None and not value.is_dir():parser.error(f'目录不存在：{value}')
    if not next(args.input_dir.rglob('*.plt'),None):parser.error('输入目录中没有PLT')
    tables={}
    for kind,label in [('support','支架'),('valve','阀门'),('flange','法兰')]:
        path=getattr(args,kind+'_table')
        if path is None and args.management_tables_dir:
            candidate=args.management_tables_dir/(label+'表.csv')
            if candidate.is_file():path=candidate
        if path is not None:
            if not path.is_file():parser.error(f'表格不存在：{path}')
            tables[kind]=path.resolve()
    if args.weld_table and not args.weld_table.is_file():parser.error(f'焊口表不存在：{args.weld_table}')
    output=args.out_dir.resolve()
    repository=Path(__file__).resolve().parent
    if output==repository or repository in output.parents:parser.error('请将输出目录放在代码项目之外')
    output.mkdir(parents=True,exist_ok=True)
    audit=output/'.audit';weld=args.weld_table
    if weld is None:
        weld=audit/'inputs/empty_weld_table.csv';weld.parent.mkdir(parents=True,exist_ok=True)
        with weld.open('w',encoding='utf-8-sig',newline='') as stream:
            csv.writer(stream).writerow(['管线号','页码','焊点编号','管段编号','焊点位置','焊点类型'])
    arguments=['--generic','--unit',args.unit or '通用','--input-dir',str(args.input_dir.resolve()),
               '--idf-dir',str(args.idf_dir.resolve()),'--weld-table',str(weld.resolve()),
               '--out-dir',str(output/'PDF'),'--report-path',str(output/'标注问题清单.xlsx'),
               '--workers',str(args.workers),'--spool' if args.spool else '--no-spool']
    if not args.unit:arguments.append('--all-units')
    if args.hit_dir:arguments+=['--hit-dir',str(args.hit_dir.resolve())]
    if args.pipeline:arguments+=['--pipeline',args.pipeline]
    if tables:
        arguments+=['--management','--management-kinds',*tables]
        for kind,path in tables.items():arguments+=['--'+kind+'-table',str(path)]
    else:arguments.append('--no-management')
    environment=os.environ.copy()
    environment.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PLT_AUDIT_DIR=str(audit))
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):environment[name]='1'
    return subprocess.call([sys.executable,str(repository/'profiles/beihai/workflow/convert_beihai_plt_to_pdf.py'),*arguments],env=environment)


if __name__=='__main__':raise SystemExit(main())
