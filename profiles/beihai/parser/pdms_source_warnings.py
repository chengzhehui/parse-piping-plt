"""Recognize the native PDMS stroked FAIL banner, retaining source offsets.

This is a font-specific vector signature, not OCR of general drawing text.
All eight consecutive paths must match; annotation text is never inspected.
"""
import math
from pdms_weld_geometry import native_paths

FAIL_PATHS=(
    ((0,6.6),(6.7,6.6)),
    ((7.4,12.6),(0,12.6),(0,0)),
    ((9.4,0),(14.1,12.6),(18.7,0)),
    ((11,4.2),(17.1,4.2)),
    ((23,0),(26.6,0)),
    ((24.8,0),(24.8,12.6)),
    ((23,12.6),(26.6,12.6)),
    ((32.4,12.6),(32.4,0),(39.8,0)))


def native_source_warnings(data):
    paths=native_paths(data);warnings=[]
    for i in range(len(paths)-7):
        block=paths[i:i+8]
        if [len(p['points']) for p in block]!=[len(p) for p in FAIL_PATHS]:continue
        root=block[1]['points'][2];height=block[1]['points'][0][1]-root[1]
        if not 5<height<30:continue
        scale=height/12.6
        if any(math.dist(point,(root[0]+expected[0]*scale,root[1]+expected[1]*scale))>.12*scale
               for actual,template in zip(block,FAIL_PATHS) for point,expected in zip(actual['points'],template)):continue
        warnings.append({'source_file':data['source'],'source_sha256':data['sha256'],'code':'native-PDMS-FAIL',
                         'bounds_mm':[root[0],root[1],root[0]+39.8*scale,root[1]+height],
                         'native_offsets':[offset for path in block for offset in path['offsets']],
                         'reason':'原始PLT带有FAIL标记；请设计核查原图错误提示、模型连接及轴测图后重新导出。此标记来自设计源图。'})
    return warnings
