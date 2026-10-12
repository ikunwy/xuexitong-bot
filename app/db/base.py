from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.utils.paths import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionFactory = scoped_session(
    sessionmaker(bind=engine, expire_on_commit=False, future=True)
)