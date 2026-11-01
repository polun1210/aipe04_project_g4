from alembic import context
from sqlalchemy import create_engine

from app.db.config import database_url, sqlalchemy_url

url = context.config.attributes.get("url") or sqlalchemy_url(database_url())
engine = create_engine(url)
with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
