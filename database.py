from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# SQLite 데이터베이스 엔진 및 세션 설정
engine = create_engine('sqlite:///erp_factory.db', connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MaterialMaster(Base):
    __tablename__ = 'material_masters'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_code = Column(String, unique=True, index=True)
    material_name_kr = Column(String)
    material_name_en = Column(String)
    cas_no = Column(String)
    supplier = Column(String)
    unit = Column(String)
    category = Column(String)
    remark = Column(String, default="")
    pre_weighing = Column(Float, default=0.0)
    stock_qty = Column(Float, default=0.0)
    sales_qty = Column(Float, default=0.0)
