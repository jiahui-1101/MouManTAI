"""Root pytest configuration and environment stabilization.

Forces pure-Python SQLAlchemy execution to prevent Cython ABI segmentation faults
(SIGSEGV exit code 139) on Python 3.12+ runtimes during ORM loading/batching.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

# Ensure pure-python SQLAlchemy implementation on environments with AppControl/WDAC/CI
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


class PurePythonSQLAlchemyFinder(importlib.machinery.PathFinder):
    """Intercept and redirect SQLAlchemy cython modules to pure-Python implementations.

    Prevents native segmentation faults in Cython-compiled modules (e.g. _result_cy)
    during test runs across various Python 3.12 / Linux runner environments.
    """

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if fullname.startswith("sqlalchemy.") and fullname.endswith("_cy"):
            if path is None:
                return None
            for entry in path:
                base = os.path.join(entry, fullname.split(".")[-1] + ".py")
                if os.path.isfile(base):
                    return importlib.util.spec_from_file_location(fullname, base)
        return None


if not any(isinstance(finder, type) and finder.__name__ == "PurePythonSQLAlchemyFinder" for finder in sys.meta_path):
    sys.meta_path.insert(0, PurePythonSQLAlchemyFinder)
