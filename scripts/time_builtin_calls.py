"""
Benchmarks the CALL_FUNCTION opcode specifically only for function
calls of __builtins__.

Note: CALL_FUNCTION is only emitted for non-keyword function calls.
"""
HAS_PYPERF = False
try:
    import pyperf
    HAS_PYPERF = True
except ImportError:
    print("No pyperf, falling back on timeit. Results may be less accurate.")
    import time
    class pyperf: ...
    pyperf.perf_counter = staticmethod(time.process_time)
    class runner: ...
    runner.bench_time_func = staticmethod(lambda desc, func: func(40_000_000))

def bench_pycfunc_noargs(loops):
    range_it = range(loops)
    t0 = pyperf.perf_counter()

    for _ in range_it:
        globals()

    return pyperf.perf_counter() - t0

def bench_pycfunc_o(loops):
    range_it = range(loops)
    val = ''
    t0 = pyperf.perf_counter()

    for _ in range_it:
        len(val)

    return pyperf.perf_counter() - t0    

def bench_pycfunc_fast(loops):
    range_it = range(loops)
    t0 = pyperf.perf_counter()

    for _ in range_it:
        getattr(None, '', None)

    return pyperf.perf_counter() - t0    

def bench_pycfunc_fast_with_keywords(loops):
    range_it = range(loops)
    val = (1,)
    t0 = pyperf.perf_counter()

    for _ in range_it:
        sorted(val)

    return pyperf.perf_counter() - t0    

def bench_pycfunc_with_keywords(loops):
    range_it = range(loops)
    val = (1,)    
    t0 = pyperf.perf_counter()
    
    for _ in range_it:
        max(val)

    return pyperf.perf_counter() - t0    

if __name__ == "__main__":
    if HAS_PYPERF:
        runner = pyperf.Runner()
        runner.metadata["description"] = "Bench CALL_FUNCTION opcode for builtins"

    benches = (
        runner.bench_time_func("METH_NOARGS", bench_pycfunc_noargs),
        runner.bench_time_func("METH_O", bench_pycfunc_o),
        runner.bench_time_func("METH_FASTCALL", bench_pycfunc_fast),
        runner.bench_time_func("METH_FASTCALL | METH_KEYWORDS",
            bench_pycfunc_fast_with_keywords),
        runner.bench_time_func("METH_VARARGS | METH_KEYWORDS",
            bench_pycfunc_with_keywords),
    )
    if not HAS_PYPERF:
        for bench in benches:
            print(f"Took: {bench}s")

