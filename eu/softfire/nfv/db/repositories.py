import logging
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.pool import StaticPool

from eu.softfire.nfv.db.entities import Base
from eu.softfire.nfv.utils.static_config import CONFIG_FILE_PATH
from eu.softfire.nfv.utils.utils import get_logger
from sdk.softfire.utils import get_config

logger = get_logger('eu.softfire.tub.repository')

lock = threading.RLock()

db_url = get_config('database', 'url', CONFIG_FILE_PATH, "sqlite:////tmp/nfv-manager.db")
if db_url.startswith("sqlite:"):
    engine = create_engine(db_url, poolclass=StaticPool, connect_args={'check_same_thread': False})
else:
    engine = create_engine(db_url)
debug_echo = (logger.getEffectiveLevel() == logging.DEBUG) and get_config('database', 'show_sql',CONFIG_FILE_PATH,
                                                                          False).lower() == 'true'
engine.echo = debug_echo
Base.metadata.create_all(engine)
session_factory = sessionmaker(bind=engine)
_session = scoped_session(session_factory)
session = _session()


@contextmanager
def get_db_session():
    with lock:
        with session.no_autoflush:
            yield session


def rollback():
    with get_db_session() as se:
        se.rollback()


def save(entity, _clazz=None):
    if _clazz:
        if hasattr(entity, 'id'):  # usually id is None so this method acs as normal save
            _id = entity.id
        else:
            _id = entity.name
        try:
            if _id:
                found = find(_clazz, _id)
                if isinstance(found, list):
                    for e in found:
                        delete(e)
                else:
                    if found:
                        delete(found)
        except NoResultFound as nrf:
            pass

    with get_db_session() as se:
        se.add(entity)
        se.commit()


def delete(entity):
    with get_db_session() as se:
        se.delete(entity)
        se.commit()


def find(_clazz, _id=None):
    with get_db_session() as se:
        if _id is None:
            res = se.query(_clazz).all()
        else:
            res = se.query(_clazz).filter(_clazz.id == _id).one()
        se.commit()
    return res


def drop_tables():
    Base.metadata.drop_all(engine)


def find_by_element_value(_clazz, element, value):
    with get_db_session() as se:
        res = se.query(_clazz).filter(element == value).all()
        se.commit()
    return res