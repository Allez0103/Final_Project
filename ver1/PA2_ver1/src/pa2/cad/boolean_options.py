"""Per-native-process OCCT Boolean resource limits."""
THREADS=1


def configure(threads):
    global THREADS
    from OCP.OSD import OSD_ThreadPool, OSD_Parallel
    threads=max(1,int(threads))
    if threads!=THREADS:
        OSD_Parallel.SetUseOcctThreads_s(True)
        pool=OSD_ThreadPool.DefaultPool_s()
        pool.Init(threads); pool.SetNbDefaultThreadsToLaunch(threads)
    THREADS=threads
