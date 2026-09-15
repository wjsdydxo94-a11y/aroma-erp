import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from database import SessionLocal, MaterialMaster

router = APIRouter(prefix="/api/v1/materials", tags=["Materials"])

class MaterialRequest(BaseModel):
    material_code: str
    material_name_kr: str
    material_name_en: str = ""
    cas_no: str = ""
    supplier: str = ""
    unit: str = "Kg"
    category: str = "원재료"
    remark: str = ""
    pre_weighing: float = 0.0
    stock_qty: float = 0.0
    sales_qty: float = 0.0

class BatchDeleteRequest(BaseModel):
    ids: List[int]

@router.get("")
def get_materials(skip: int = 0, limit: int = 30, search: str = None, category: str = None):
    try:
        db = SessionLocal()
        query = db.query(MaterialMaster)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (MaterialMaster.material_code.like(search_pattern)) |
                (MaterialMaster.material_name_kr.like(search_pattern)) |
                (MaterialMaster.material_name_en.like(search_pattern)) |
                (MaterialMaster.cas_no.like(search_pattern)) |
                (MaterialMaster.supplier.like(search_pattern)) |
                (MaterialMaster.category.like(search_pattern)) |
                (MaterialMaster.remark.like(search_pattern))
            )
        if category:
            query = query.filter(MaterialMaster.category == category)
            
        total = query.count()
        materials = query.offset(skip).limit(limit).all()
        db.close()
        
        data = []
        for m in materials:
            try:
                yearly_dict = json.loads(m.yearly_pre_weighing) if m.yearly_pre_weighing else {}
            except:
                yearly_dict = {}
            try:
                lot_list = json.loads(m.lot_stock) if m.lot_stock else []
            except:
                lot_list = []

            data.append({
                "id": m.id,
                "material_code": m.material_code,
                "material_name_kr": m.material_name_kr,
                "material_name_en": m.material_name_en,
                "cas_no": m.cas_no,
                "supplier": m.supplier,
                "category": m.category or "원재료",
                "remark": m.remark or "",
                "pre_weighing": getattr(m, 'pre_weighing', 0.0) or 0.0,
                "stock_qty": getattr(m, 'stock_qty', 0.0) or 0.0,
                "sales_qty": getattr(m, 'sales_qty', 0.0) or 0.0,
                "yearly_pre_weighing": yearly_dict,
                "lot_stock": lot_list,
                "unit": m.unit
            })
        return {"status": "SUCCESS", "total": total, "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/lookup")
def lookup_material(code: str):
    try:
        db = SessionLocal()
        matches = db.query(MaterialMaster).filter(
            (MaterialMaster.material_code == code) | 
            (MaterialMaster.material_code.like(f"%{code}%"))
        ).limit(10).all()
        db.close()
        
        data = [{
            "material_code": m.material_code,
            "material_name_kr": m.material_name_kr,
            "material_name_en": m.material_name_en,
            "cas_no": m.cas_no,
            "supplier": m.supplier,
            "category": m.category,
            "remark": m.remark
        } for m in matches]
        return {"status": "SUCCESS", "matches": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def create_material(data: MaterialRequest):
    try:
        db = SessionLocal()
        existing = db.query(MaterialMaster).filter(MaterialMaster.material_code == data.material_code).first()
        if existing:
            db.close()
            raise HTTPException(status_code=400, detail="이미 존재하는 제품코드입니다.")
        
        new_m = MaterialMaster(
            material_code=data.material_code,
            material_name_kr=data.material_name_kr,
            material_name_en=data.material_name_en,
            cas_no=data.cas_no,
            supplier=data.supplier,
            category=data.category,
            unit=data.unit,
            remark=data.remark,
            pre_weighing=data.pre_weighing,
            stock_qty=data.stock_qty,
            sales_qty=data.sales_qty
        )
        db.add(new_m)
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "신규 제품이 등록되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete-batch")
def delete_batch_materials(data: BatchDeleteRequest):
    try:
        db = SessionLocal()
        db.query(MaterialMaster).filter(MaterialMaster.id.in_(data.ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": f"선택한 {len(data.ids)}건의 품목이 삭제되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{material_id}")
def update_material(material_id: int, data: MaterialRequest):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        
        m.material_code = data.material_code
        m.material_name_kr = data.material_name_kr
        m.material_name_en = data.material_name_en
        m.cas_no = data.cas_no
        m.supplier = data.supplier
        m.category = data.category
        m.unit = data.unit
        m.remark = data.remark
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "수정되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{material_id}/yearly-pre")
def update_yearly_pre(material_id: int, data: dict):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        
        yearly_data = data.get("yearly_data", {})
        m.yearly_pre_weighing = json.dumps(yearly_data, ensure_ascii=False)
        total = sum(float(v) for v in yearly_data.values() if str(v).strip() != "")
        m.pre_weighing = total
        db.commit()
        db.close()
        return {"status": "SUCCESS", "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{material_id}/lot-stock")
def update_lot_stock(material_id: int, data: dict):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        
        lot_data = data.get("lot_data", [])
        m.lot_stock = json.dumps(lot_data, ensure_ascii=False)
        total = sum(float(item.get("qty", 0)) for item in lot_data if str(item.get("qty", "")).strip() != "")
        m.stock_qty = total
        db.commit()
        db.close()
        return {"status": "SUCCESS", "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{material_id}/qtys")
def update_material_qtys(material_id: int, data: dict):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        
        m.sales_qty = float(data.get("sales_qty", 0))
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "수량이 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{material_id}")
def delete_material(material_id: int):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        db.delete(m)
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "삭제되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
