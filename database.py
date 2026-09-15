import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_URL = "sqlite:///./erp_factory.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MaterialMaster(Base):
    __tablename__ = "material_masters"
    id = Column(Integer, primary_key=True, index=True)
    material_code = Column(String, unique=True, index=True)
    material_name_kr = Column(String)
    material_name_en = Column(String)
    cas_no = Column(String)
    supplier = Column(String)
    unit = Column(String, default="Kg")
    category = Column(String, default="원재료")
    remark = Column(Text, default="")
    pre_weighing = Column(Float, default=0.0)
    stock_qty = Column(Float, default=0.0)
    sales_qty = Column(Float, default=0.0)
    yearly_pre_weighing = Column(Text, default="{}")
    lot_stock = Column(Text, default="[]")
