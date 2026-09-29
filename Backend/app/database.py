from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import get_settings

settings = get_settings()

database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Managed Postgres providers (Neon, Supabase, ...) hand out connection strings
# built for libpq/psycopg2 — query params like sslmode=require and
# channel_binding=require, neither of which asyncpg's connect() understands.
# asyncpg raises on the unrecognized channel_binding param specifically,
# failing the connection outright rather than just ignoring it. Strip both
# and translate sslmode into the connect_args asyncpg actually takes.
connect_args = {}
if "+asyncpg" in database_url:
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query))
    query.pop("channel_binding", None)  # asyncpg has no equivalent; just discard it
    sslmode = query.pop("sslmode", None)
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True
    database_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()
