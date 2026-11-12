"""Environment budget for isolated full and provisional grid workers."""
import os

THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
                    'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')


def worker_environment():
    """Return a child environment; never change the service's own settings."""
    return {**os.environ, **dict.fromkeys(THREAD_VARIABLES, '1')}
