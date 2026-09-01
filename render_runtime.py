"""Small process-wide locks shared by the plotting and geometry backends."""

from __future__ import annotations

from threading import RLock


# Matplotlib's pyplot state is process-global.  Keep this module deliberately
# dependency-free so importing the lock never pulls in NumPy/SymPy.
MATPLOTLIB_RENDER_LOCK = RLock()


__all__ = ["MATPLOTLIB_RENDER_LOCK"]
