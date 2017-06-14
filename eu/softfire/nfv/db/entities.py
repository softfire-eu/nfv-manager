from sqlalchemy import String, Column, PickleType
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


# log url {nsrId}/vnfrecord/{vnfrName}/hostname/{hostname}
class Nsr(Base):
    __tablename__ = "ns_records"

    id = Column(String(250), primary_key=True)
    username = Column(String(250), nullable=False)
    status = Column(String(250), nullable=False)
    # {vnfrName:hostname}
    vnf_log_url = Column(PickleType)
