#!/usr/bin/env python3
"""Bootstrap dependency checker behavior test."""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location('bootstrap_runtime_check', REPO_ROOT / 'scripts' / 'bootstrap-runtime-check.py')
module = importlib.util.module_from_spec(spec)
sys.modules['bootstrap_runtime_check'] = module
spec.loader.exec_module(module)

original = module.check_dependency

try:
    module.check_dependency = lambda name: name != 'requests'
    assert module.main() == 1, 'Expected bootstrap check to fail when requests missing'

    module.check_dependency = lambda name: True
    assert module.main() == 0, 'Expected bootstrap check to pass when all dependencies present'
finally:
    module.check_dependency = original

print('[OK] Bootstrap runtime check behaves as expected')
