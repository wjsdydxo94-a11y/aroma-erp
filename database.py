from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# 기존 설정 유지 및 MaterialMaster 모델에 remark 컬럼 추가
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
    remark = Column(String, default="")  # 이 줄을 추가해 주세요
