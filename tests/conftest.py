"""Keep the test session from ever exhausting the machine's memory: a runaway
allocation (e.g. rasterising a fuzzed 1e6 x 1e6 px element) raises MemoryError
instead of pushing the OS into OOM-killing other processes."""

import resource

LIMIT_BYTES = 16 * 1024 ** 3

soft, hard = resource.getrlimit(resource.RLIMIT_AS)
if hard == resource.RLIM_INFINITY or hard > LIMIT_BYTES:
    resource.setrlimit(resource.RLIMIT_AS, (LIMIT_BYTES, hard))
