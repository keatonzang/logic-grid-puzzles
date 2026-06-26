"""Ensure the project root is importable so ``import logicgrid`` works whether
pytest is invoked from the repo root or elsewhere."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
