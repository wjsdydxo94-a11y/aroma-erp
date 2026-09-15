import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from database import SessionLocal, MaterialMaster

router = APIRouter(prefix="/api/v1/boms", tags=["BOM"])

class BomSaveRequest(BaseModel):
    product_code: str
    product_name: str
    bom_version: str = "1"
    items: List[dict]

def get_auto_category(code: str) -> str:
    code = str(code).strip()
    if code == "1000052941":
        return "제품"
    elif code.startswith("1000"):
        return "KT&G상품"
    elif code.startswith("AR-"):
        return "제품"
    elif code.startswith("CB-"):
        return "반제품"
    elif "-M" in code or "-P" in code:
        return "반제품"
    else:
        return "원재료"

@router.get("")
def get_bom(product_code: str, version: str = "1"):
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bom_headers WHERE product_code = ? AND bom_version = ?", (product_code, version))
        header = cursor.fetchone()
        if not header:
            conn.close()
            return {"header": None, "items": []}
        
        cursor.execute("SELECT * FROM bom_items WHERE bom_id = ?", (header['bom_id'],))
        items = cursor.fetchall()
        conn.close()
        return {
            "header": dict(header),
            "items": [dict(it) for it in items]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/save")
def save_bom(data: BomSaveRequest):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT bom_id FROM bom_headers WHERE product_code = ? AND bom_version = ?", (data.product_code, data.bom_version))
        row = cursor.fetchone()
        if row:
            bom_id = row[0]
            cursor.execute("DELETE FROM bom_items WHERE bom_id = ?", (bom_id,))
            cursor.execute("UPDATE bom_headers SET product_name = ? WHERE bom_id = ?", (data.product_name, bom_id))
        else:
            cursor.execute("INSERT INTO bom_headers (product_code, product_name, process_code, bom_version, production_qty) VALUES (?, ?, ?, ?, ?)",
                           (data.product_code, data.product_name, "제품", data.bom_version, 1.0))
            bom_id = cursor.lastrowid
            
        db_mat = SessionLocal()
        for item in data.items:
            cursor.execute('''
                INSERT INTO bom_items (bom_id, material_code, material_name, qty, unit, cas_no, location, item_bom_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (bom_id, item.get('material_code'), item.get('material_name'), item.get('qty'), item.get('unit', 'KG'), item.get('cas_no', ''), '', data.bom_version))
            
            m_code = item.get('material_code')
            if m_code:
                existing = db_mat.query(MaterialMaster).filter(MaterialMaster.material_code == m_code).first()
                cat = get_auto_category(m_code)

                if not existing:
                    new_m = MaterialMaster(
                        material_code=m_code,
                        material_name_kr=item.get('material_name'),
                        material_name_en="",
                        cas_no=item.get('cas_no', ''),
                        supplier="",
                        category=cat,
                        unit=item.get('unit', 'Kg'),
                        remark=""
                    )
                    db_mat.add(new_m)
        db_mat.commit()
        db_mat.close()
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "BOM이 성공적으로 저장되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
