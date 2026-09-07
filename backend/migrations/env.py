import os

from alembic import context
from app.models import Base
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

load_dotenv()
url = os.environ["DATABASE_URL"]
engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
