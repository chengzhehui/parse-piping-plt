"""Paper-space preferred bands and staged short/long leader penalties."""
import math

STAGES=((0.,0.,0.),(150.,250.,12000.),(300.,650.,40000.),(500.,1400.,120000.))


def preferred_band(kind,sheet_scale):
    values=(350,850) if kind=='weld' else (450,1000) if kind=='spool' else (400,900)
    return tuple(v*sheet_scale for v in values)


def length_penalty(length_units,kind,sheet_scale):
    lower,upper=preferred_band(kind,sheet_scale)
    for stage,(shorten,extend,cost) in enumerate(STAGES):
        if max(0,lower-shorten)<=length_units<=upper+extend:
            return stage,cost
    excess=max(0,lower-STAGES[-1][0]-length_units,length_units-upper-STAGES[-1][1])/40
    return 4,350000.+excess*6000.


def audit_length(length_mm,kind,sheet_scale):
    stage,cost=length_penalty(length_mm*40,kind,sheet_scale)
    lower,upper=preferred_band(kind,sheet_scale)
    return {'length_mm':length_mm,'preferred_min_mm':lower/40,'preferred_max_mm':upper/40,
            'penalty_stage':stage,'penalty_score':cost}
