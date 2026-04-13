from __future__ import annotations

"""
conftest.py — pytest configuration for the backend test suite.

I add the backend directory to sys.path here so that all test files can
import modules (parsers, services, utils, routes) using the same bare
import names that the running application uses. Without this, pytest would
require the tests to use relative imports, which breaks the convention
established in the application code.

Running tests:
    cd backend
    pytest tests/ -v
"""

import sys
import os

# Insert the backend directory so 'from parsers.structure_parser import ...'
# works in tests just as it does in the application itself.
sys.path.insert(0, os.path.dirname(__file__))
