"""Measure the actual embedded SimHei glyph bounds in paper millimetres."""
from functools import lru_cache
from fontTools.ttLib import TTFont

DEFAULT_FONT='C:/Windows/Fonts/simhei.ttf'


@lru_cache(maxsize=4)
def font_data(path):
    font=TTFont(path,lazy=True)
    return font,font.getBestCmap(),font['head'].unitsPerEm,font['glyf'],font['hmtx'].metrics


@lru_cache(maxsize=2048)
def text_metrics(text,height_mm,font_file=DEFAULT_FONT):
    font,cmap,units,glyf,hmtx=font_data(str(font_file))
    advance=0;bounds=[]
    for char in text:
        name=cmap[ord(char)]
        glyph=glyf[name]
        if getattr(glyph,'numberOfContours',0):
            bounds.append((advance+glyph.xMin,glyph.yMin,advance+glyph.xMax,glyph.yMax))
        advance+=hmtx[name][0]
    if not bounds:raise ValueError('Annotation text has no visible glyphs')
    scale=height_mm/units
    left=min(b[0] for b in bounds)*scale;right=max(b[2] for b in bounds)*scale
    bottom=min(b[1] for b in bounds)*scale;top=max(b[3] for b in bounds)*scale
    return {'ink_width_mm':right-left,'ink_height_mm':top-bottom,
            'ink_center_x_mm':(left+right)/2,'ink_center_y_mm':(bottom+top)/2,
            'advance_mm':advance*scale}
