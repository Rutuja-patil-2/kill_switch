import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

pool: AsyncConnectionPool | None = None


async def open_pool():
    global pool
    # autocommit=True: every statement commits on its own; ledger.py opens explicit
    # transactions where it needs atomicity. This also means an HTTP error raised later
    # can never roll back an audit row that was already written.
    pool = AsyncConnectionPool(
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": True},
    )
    await pool.open(wait=True, timeout=30)


async def close_pool():
    if pool is not None:
        await pool.close()
