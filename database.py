from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./erp_factory.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class MaterialMaster(Base):
    __tablename__ = "material_masters"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    material_code = Column(String, unique=True, index=True, nullable=False)
    material_name_kr = Column(String, nullable=False)
    material_name_en = Column(String)
    cas_no = Column(String)
    supplier = Column(String)
    unit = Column(String, default="Kg")
    category = Column(String)
