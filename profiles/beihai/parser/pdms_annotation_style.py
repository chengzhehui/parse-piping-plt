"""Sheet-proportional typography and fixed per-family annotation frames."""
from dataclasses import asdict,dataclass


@dataclass(frozen=True)
class SheetAnnotationStyle:
    sheet_scale: float
    font_height_mm: float
    weld_diameter_mm: float
    management_width_mm: float
    management_height_mm: float
    spool_width_mm: float
    spool_height_mm: float
    spool_inner_gap_mm: float
    stroke_width_mm: float=.2
    annotation_scale: float=2.0
    compact_frames: bool=False
    text_padding_mm: float=.6

    def as_dict(self):
        return asdict(self)


def sheet_style(width_mm,height_mm,annotation_scale=2.0,font_height_mm=None,weld_diameter_mm=None,compact_frames=False):
    # A3 is the reference sheet. All labels on the same sheet use the same
    # font height and each family uses one frame size, independent of digits.
    scale=min(width_mm,height_mm)/297
    half_mm=lambda v:round(v*scale*2)/2*annotation_scale
    if font_height_mm is not None:
        annotation_scale=font_height_mm/(round(2.5*scale*2)/2)
    return SheetAnnotationStyle(scale,font_height_mm if font_height_mm is not None else half_mm(2.5),
                                weld_diameter_mm if weld_diameter_mm is not None else half_mm(6),
                                None if compact_frames else half_mm(7),None if compact_frames else half_mm(4),
                                None if compact_frames else half_mm(5.5),None if compact_frames else half_mm(4),
                                .4 if compact_frames else round(.35*scale,2)*annotation_scale,
                                annotation_scale=annotation_scale,compact_frames=compact_frames)
