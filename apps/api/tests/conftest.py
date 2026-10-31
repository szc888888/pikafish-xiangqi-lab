"""Keep the test suite away from the configured application database."""
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_suite.db"
