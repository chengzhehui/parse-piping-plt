"""北海项目统一入口：按单元生成 PLT 转换标注 PDF 和审核问题清单。"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    repository = Path(__file__).resolve().parent
    if '--list-units' in arguments:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--list-units', action='store_true')
        parser.parse_args(arguments)
        config = json.loads((repository / 'profiles/beihai/config.json').read_text(encoding='utf-8'))
        incoming = repository.parent / config['input_pattern'].format(unit='')
        units = sorted(path.name for path in incoming.iterdir()
                       if path.is_dir() and next(path.rglob('*.plt'), None) is not None) if incoming.exists() else []
        print('\n'.join(units))
        return 0
    environment = os.environ.copy()
    environment.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environment[key] = '1'
    entry = repository / 'profiles/beihai/workflow/convert_beihai_plt_to_pdf.py'
    return subprocess.call([sys.executable, str(entry), *arguments], env=environment)


if __name__ == '__main__':
    raise SystemExit(main())
