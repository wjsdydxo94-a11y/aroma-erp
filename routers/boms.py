from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import sqlite3
import pandas as pd
import io

router = APIRouter(prefix="/api/v1", tags=["boms"])

def get_db_connection():
    conn = sqlite3.connect('erp_factory.db')
    conn.row_factory = sqlite3.Row
    return conn

class BomItem(BaseModel):
    material_code: str
    material_name: str
    qty: float
    unit: str = "KG"
    cas_no: str = ""
    location: str = ""

class BomSaveModel(BaseModel):
    product_code: str
    product_name: str
    bom_version: str = "v1.0"
    items: list[BomItem]

@router.get("/boms")
def get_bom(product_code: str, version: str = "v1.0"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bom_headers WHERE product_code = ? AND bom_version = ?", (product_code, version))
    header = cursor.fetchone()
    if not header:
        # 버전이 없다면 기본 헤더 생성 혹은 빈 리스트 반환
        conn.close()
        return {"status": "SUCCESS", "header": None, "items": [], "versions": [version]}
    
    cursor.execute("SELECT * FROM bom_items WHERE bom_id = ?", (header["bom_id"],))
    items = [dict(row) for row in cursor.fetchall()]
    
    # 해당 제품의 모든 버전 리스트 조회
    cursor.execute("SELECT DISTINCT bom_version FROM bom_headers WHERE product_code = ?", (product_code,))
    versions = [row["bom_version"] for row in cursor.fetchall()]
    if not versions:
        versions = ["v1.0"]

    conn.close()
    return {"status": "SUCCESS", "header": dict(header), "items": items, "versions": versions}

@router.post("/boms/save")
def save_bom(bom: BomSaveModel):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 기존 헤더 확인
    cursor.execute("SELECT bom_id FROM bom_headers WHERE product_code = ? AND bom_version = ?", (bom.product_code, bom.bom_version))
    header = cursor.fetchone()
    
    if header:
        bom_id = header["bom_id"]
        cursor.execute("DELETE FROM bom_items WHERE bom_id = ?", (bom_id,))
    else:
        cursor.execute("""
            INSERT INTO bom_headers (product_code, product_name, bom_version, is_default, production_qty)
            VALUES (?, ?, ?, 1, 1.0)
        """, (bom.product_code, bom.product_name, bom.bom_version))
        bom_id = cursor.lastrowid

    for item in bom.items:
        cursor.execute("""
            INSERT INTO bom_items (bom_id, material_code, material_name, qty, unit, cas_no, location, item_bom_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (bom_id, item.material_code, item.material_name, item.qty, item.unit, item.cas_no, item.location, bom.bom_version))

    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": f"BOM 버전 ({bom.bom_version})이 저장되었습니다."}

@router.post("/boms/upload-excel")
async def upload_bom_excel(product_code: str = Form(...), bom_version: str = Form(...), file: UploadFile = File(...)):
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents), header=None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"엑셀 파일 읽기 실패: {e}")

    items = []
    for idx, row in df.iterrows():
        vals = [str(v).strip() for v in row.values if pd.notnull(v)]
        if not vals or any(kw in " ".join(vals) for kw in ["코드", "품목", "원료명", "수량", "CAS"]):
            continue
        if len(vals) >= 2:
            code = vals[0]
            name = vals[1] if len(vals) > 1 else ""
            qty = 0.0
            for v in vals[2:]:
                try:
                    qty = float(v)
                    break
                except ValueError:
                    continue
            unit = "KG"
            cas = ""
            for v in vals:
                if "-" in v and len(v) >= 7:
                    cas = v
            items.append(BomItem(material_code=code, material_name=name, qty=qty, unit=unit, cas_no=cas))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bom_id FROM bom_headers WHERE product_code = ? AND bom_version = ?", (product_code, bom_version))
    header = cursor.fetchone()
    
    if header:
        bom_id = header["bom_id"]
        cursor.execute("DELETE FROM bom_items WHERE bom_id = ?", (bom_id,))
    else:
        cursor.execute("""
            INSERT INTO bom_headers (product_code, product_name, bom_version, is_default, production_qty)
            VALUES (?, ?, ?, 1, 1.0)
        """, (product_code, product_code, bom_version))
        bom_id = cursor.lastrowid

    for item in items:
        cursor.execute("""
            INSERT INTO bom_items (bom_id, material_code, material_name, qty, unit, cas_no, location, item_bom_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (bom_id, item.material_code, item.material_name, item.qty, item.unit, item.cas_no, "", bom_version))

    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": f"{len(items)}개의 원료 BOM이 엑셀에서 업로드되었습니다."}
