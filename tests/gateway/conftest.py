"""Gateway test fixtures.

Import models so Base.metadata.create_all in root conftest creates all tables
when running gateway tests in isolation (make test-gateway).
"""

import src.board.models  # noqa: F401
