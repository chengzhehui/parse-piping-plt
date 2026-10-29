"""Vectorized Chengda-style compatibility/min-conflicts for large fixed frames.

The physical box and straight-leader rules are identical to the shared layout
contract; NumPy updates replace repeated Python pair scans on dense pages.
"""
import math
import numpy as np


def segment_box(ax,ay,bx,by,left,bottom,right,top):
    shape=np.broadcast_shapes(np.shape(bx),np.shape(left))
    lower=np.zeros(shape);upper=np.ones(shape);valid=np.ones(shape,dtype=bool)
    for start,end,lo,hi in ((ax,bx,left,right),(ay,by,bottom,top)):
        delta=end-start
        parallel=np.abs(delta)<1e-9
        valid &= ~parallel | ((start>=lo)&(start<=hi))
        safe=np.where(parallel,1.,delta)
        t0=(lo-start)/safe;t1=(hi-start)/safe
        lower=np.maximum(lower,np.where(parallel,-np.inf,np.minimum(t0,t1)))
        upper=np.minimum(upper,np.where(parallel,np.inf,np.maximum(t0,t1)))
    return valid & (upper>=lower)


def solve(points,options,max_restarts=48,max_iterations=8000):
    n=len(points)
    if not n:return [],{'method':'vectorized-compatible-min-conflicts','iterations':0}
    sizes=[len(o) for o in options];k=max(sizes)
    conflicts=np.zeros((n,k,n,k),dtype=bool)
    costs=np.full((n,k),np.inf)
    xs=[];ys=[];boxes=[];spacing_boxes=[]
    for i,opts in enumerate(options):
        costs[i,:sizes[i]]=[o.placement.score for o in opts]
        xs.append(np.array([o.placement.leader_x for o in opts]))
        ys.append(np.array([o.placement.leader_y for o in opts]))
        # Match Chengda's adaptive insets too: tiny text-wrapping frames have
        # a larger safety envelope than simply subtracting the 60-unit gap.
        box=np.array([o.marker_box for o in opts],dtype=float)
        smaller=np.minimum(box[:,2]-box[:,0],box[:,3]-box[:,1])
        physical=np.minimum(60,smaller*.20)
        spacing=np.minimum(50,smaller*.15)
        boxes.append(box+np.column_stack((physical,physical,-physical,-physical)))
        spacing_boxes.append(box+np.column_stack((spacing,spacing,-spacing,-spacing)))
    for i in range(n):
        a=points[i];ab=boxes[i];ax=xs[i][:,None];ay=ys[i][:,None]
        for j in range(i+1,n):
            b=points[j];bb=boxes[j];bx=xs[j][None,:];by=ys[j][None,:]
            sa,sb=spacing_boxes[i],spacing_boxes[j]
            overlap=((sa[:,None,0]<sb[None,:,2])&(sa[:,None,2]>sb[None,:,0])&
                     (sa[:,None,1]<sb[None,:,3])&(sa[:,None,3]>sb[None,:,1]))
            first_box=segment_box(a.center_x,a.center_y,ax,ay,
                                  bb[None,:,0],bb[None,:,1],bb[None,:,2],bb[None,:,3])
            second_box=segment_box(b.center_x,b.center_y,bx,by,
                                   ab[:,None,0],ab[:,None,1],ab[:,None,2],ab[:,None,3])
            cross=np.zeros_like(overlap)
            if math.hypot(a.center_x-b.center_x,a.center_y-b.center_y)>1:
                o1=(ax-a.center_x)*(b.center_y-a.center_y)-(ay-a.center_y)*(b.center_x-a.center_x)
                o2=(ax-a.center_x)*(by-a.center_y)-(ay-a.center_y)*(bx-a.center_x)
                o3=(bx-b.center_x)*(a.center_y-b.center_y)-(by-b.center_y)*(a.center_x-b.center_x)
                o4=(bx-b.center_x)*(ay-b.center_y)-(by-b.center_y)*(ax-b.center_x)
                cross=(o1*o2<0)&(o3*o4<0)
                def on(px,py,x0,y0,x1,y1):
                    return (px>=np.minimum(x0,x1)-1e-7)&(px<=np.maximum(x0,x1)+1e-7)&(py>=np.minimum(y0,y1)-1e-7)&(py<=np.maximum(y0,y1)+1e-7)
                cross |= (np.abs(o1)<1e-7)&on(b.center_x,b.center_y,a.center_x,a.center_y,ax,ay)
                cross |= (np.abs(o2)<1e-7)&on(bx,by,a.center_x,a.center_y,ax,ay)
                cross |= (np.abs(o3)<1e-7)&on(a.center_x,a.center_y,b.center_x,b.center_y,bx,by)
                cross |= (np.abs(o4)<1e-7)&on(ax,ay,b.center_x,b.center_y,bx,by)
            flags=overlap|first_box|second_box|cross
            conflicts[i,:sizes[i],j,:sizes[j]]=flags
            conflicts[j,:sizes[j],i,:sizes[i]]=flags.T
    rng=np.random.default_rng(0x50444D53)
    indexes=np.arange(n)
    best=None
    iteration_total=0
    for restart in range(max_restarts):
        chosen=(np.zeros(n,dtype=int) if restart==0 else
                np.array([rng.integers(0,min(s,32+restart*4)) for s in sizes]))
        counts=np.zeros((n,k),dtype=np.int16)
        for j in range(n):counts+=conflicts[:,:,j,chosen[j]]
        stalled=0
        for iteration in range(max_iterations):
            iteration_total+=1
            current=counts[indexes,chosen]
            bad=np.flatnonzero(current)
            total=int(current.sum())//2
            if best is None or total<best[0]:
                best=(total,chosen.copy());stalled=0
            else:stalled+=1
            if not len(bad):
                # Improve visual cost while preserving zero pair conflicts.
                for _ in range(12):
                    changed=False
                    for i in rng.permutation(n):
                        free=np.flatnonzero(counts[i,:sizes[i]]==0)
                        new=int(free[np.argmin(costs[i,free])])
                        old=int(chosen[i])
                        if new!=old and costs[i,new]<costs[i,old]-1e-6:
                            counts+=conflicts[:,:,i,new].astype(np.int16)-conflicts[:,:,i,old].astype(np.int16)
                            chosen[i]=new
                            changed=True
                    if not changed:break
                # A long leader may be blocked by just one neighbouring tag.
                # Allow two labels to exchange space without introducing a
                # conflict, so the staged length cost can improve globally.
                for _ in range(2):
                    changed=False
                    for i in range(n):
                        for j in range(i+1,n):
                            left=np.flatnonzero(counts[i,:sizes[i]]-conflicts[i,:sizes[i],j,chosen[j]]==0)
                            right=np.flatnonzero(counts[j,:sizes[j]]-conflicts[j,:sizes[j],i,chosen[i]]==0)
                            left=left[np.argsort(costs[i,left])[:12]]
                            right=right[np.argsort(costs[j,right])[:12]]
                            if not len(left) or not len(right):continue
                            sums=costs[i,left,None]+costs[j,right][None,:]
                            forbidden=conflicts[i,:sizes[i],j,:sizes[j]][np.ix_(left,right)]
                            sums=np.where(forbidden,np.inf,sums)
                            a,b=np.unravel_index(np.argmin(sums),sums.shape)
                            if sums[a,b]<costs[i,chosen[i]]+costs[j,chosen[j]]-1e-6:
                                for v,new in ((i,int(left[a])),(j,int(right[b]))):
                                    old=int(chosen[v])
                                    counts+=conflicts[:,:,v,new].astype(np.int16)-conflicts[:,:,v,old].astype(np.int16)
                                    chosen[v]=new
                                changed=True
                    if not changed:break
                return [options[i][chosen[i]].placement for i in range(n)],{
                    'method':'vectorized-compatible-min-conflicts','restarts':restart,
                    'iterations':iteration_total,'pair_conflicts':0}
            if stalled>700:break
            i=int(rng.choice(bad))
            row=counts[i,:sizes[i]]
            candidates=np.flatnonzero(row==row.min())
            # Deterministic seeded noise escapes candidate cycles; cost wins
            # once the compatibility graph has a zero-conflict assignment.
            if rng.random()<.25:
                new=int(rng.choice(candidates))
            else:
                ranked=candidates[np.argsort(costs[i,candidates])[:min(5,len(candidates))]]
                new=int(rng.choice(ranked))
            if stalled>100 and rng.random()<.12:new=int(rng.integers(sizes[i]))
            old=int(chosen[i])
            if new!=old:
                counts+=conflicts[:,:,i,new].astype(np.int16)-conflicts[:,:,i,old].astype(np.int16)
                chosen[i]=new
    raise ValueError(f'Large-frame search did not reach zero conflicts; best remaining pairs={best[0]}')
