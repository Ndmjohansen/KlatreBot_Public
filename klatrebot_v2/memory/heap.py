"""Release unused libc arenas after large collection/cache replacements on Linux."""
import ctypes
import gc
import sys


def release_unused():
    if sys.platform != 'linux':
        return
    gc.collect()
    libc = ctypes.CDLL(None)
    trim = getattr(libc, 'malloc_trim', None)
    if trim is not None:
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        trim(0)
