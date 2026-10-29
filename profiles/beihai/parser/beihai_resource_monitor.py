"""Sample this conversion process tree and host load, without external services."""
import json
import os
from pathlib import Path
import threading
import time
import psutil


class ResourceMonitor:
    def __init__(self,path,workers,interval=1.):
        self.path=Path(path);self.workers=workers;self.interval=interval;self.samples=[]
        self.phase='mapping-and-workers';self.stop_event=threading.Event();self.summary={}

    def __enter__(self):
        self.started=time.monotonic();self.root=psutil.Process(os.getpid());self.logical=psutil.cpu_count() or 1
        self.host={'logical_cpus':self.logical,'physical_cores':psutil.cpu_count(logical=False),
                   'memory_total_bytes':psutil.virtual_memory().total,'initial_available_bytes':psutil.virtual_memory().available}
        self.previous={};psutil.cpu_percent(None)
        self._sample()
        self.thread=threading.Thread(target=self._run,name='conversion-resource-monitor',daemon=True);self.thread.start()
        return self

    def _sample(self):
        now=time.monotonic();rss=private=cpu=0.;pids=[];children=[]
        try:children=self.root.children(recursive=True)
        except psutil.Error:pass
        for proc in [self.root,*children]:
            try:
                info=proc.memory_info();times=proc.cpu_times();total=times.user+times.system
                rss+=info.rss;private+=getattr(info,'private',info.rss);pids.append(proc.pid)
                previous=self.previous.get(proc.pid)
                if previous:cpu+=max(0,total-previous[0])/max(.001,now-previous[1])
                self.previous[proc.pid]=(total,now)
            except psutil.Error:continue
        vm=psutil.virtual_memory()
        self.samples.append({'seconds':round(now-self.started,3),'phase':self.phase,
            'process_cpu_cores':round(cpu,4),'process_cpu_machine_percent':round(cpu/self.logical*100,3),
            'system_cpu_percent':psutil.cpu_percent(None),'process_tree_rss_bytes':int(rss),
            'process_tree_private_bytes':int(private),'available_memory_bytes':vm.available,
            'system_memory_percent':vm.percent,'pids':pids})

    def _run(self):
        next_log=30
        while not self.stop_event.wait(self.interval):
            self._sample();sample=self.samples[-1]
            if sample['seconds']>=next_log:
                print(f"Resources {sample['seconds']:.0f}s: process CPU {sample['process_cpu_cores']:.2f} cores "
                      f"({sample['process_cpu_machine_percent']:.1f}% of host), "
                      f"RSS {sample['process_tree_rss_bytes']/2**30:.2f} GiB, "
                      f"available {sample['available_memory_bytes']/2**30:.2f} GiB",flush=True)
                next_log+=30

    def __exit__(self,*args):
        self.stop_event.set();self.thread.join(timeout=3);self._sample()
        samples=self.samples[1:] or self.samples
        active=[s for s in samples if s['phase']=='page-workers'] or samples
        self.summary={'workers':self.workers,'host':self.host,'elapsed_seconds':round(time.monotonic()-self.started,3),
            'sample_interval_seconds':self.interval,'sample_count':len(self.samples),
            'process_cpu_average_cores':sum(s['process_cpu_cores'] for s in samples)/len(samples),
            'process_cpu_peak_cores':max(s['process_cpu_cores'] for s in samples),
            'page_workers_average_cpu_cores':sum(s['process_cpu_cores'] for s in active)/len(active),
            'system_cpu_average_percent':sum(s['system_cpu_percent'] for s in samples)/len(samples),
            'system_cpu_peak_percent':max(s['system_cpu_percent'] for s in samples),
            'peak_process_tree_rss_bytes':max(s['process_tree_rss_bytes'] for s in samples),
            'peak_process_tree_private_bytes':max(s['process_tree_private_bytes'] for s in samples),
            'minimum_available_memory_bytes':min(s['available_memory_bytes'] for s in samples),
            'measurement':'CPU cores are process-tree CPU seconds / wall seconds; RSS sum includes shared mappings; private bytes are private committed memory.'}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps({'summary':self.summary,'samples':self.samples},ensure_ascii=False,indent=2),encoding='utf-8')
