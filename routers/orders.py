from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sqlite3
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["orders"])

def get_db_connection():
    conn = sqlite3.connect('erp_factory.db')
    conn.row_factory = sqlite3.Row
    return conn

class OrderModel(BaseModel):
    order_no: str
    client_name: str
    manager_id: str = "전용태"
    product_code: str = ""
    product_name: str = ""
    product_summary: str = ""
    order_qty: float
    order_amount: float
    due_date: str
    remark: str = ""

@router.get("/orders")
def get_orders():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY order_id DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"status": "SUCCESS", "data": [dict(row) for row in rows]}

@router.post("/orders")
def create_order(order: OrderModel):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    summary = order.product_summary
    if order.product_code and order.product_name:
        summary = f"[{order.product_code}] {order.product_name}"
    elif order.product_name:
        summary = order.product_name
    elif order.product_code:
        summary = order.product_code

    cursor.execute("""
        INSERT INTO orders (order_no, client_name, manager_id, product_code, product_name, product_summary, order_qty, order_amount, due_date, remark, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '진행중')
    """, (order.order_no, order.client_name, order.manager_id, order.product_code, order.product_name, summary, order.order_qty, order.order_amount, order.due_date, order.remark))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "주문서가 등록되었습니다."}

@router.delete("/orders/{order_id}")
def delete_order(order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "주문서가 삭제되었습니다."}

@router.get("/work-orders")
def get_work_orders():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM work_orders ORDER BY work_order_id DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"status": "SUCCESS", "data": [dict(row) for row in rows]}

@router.post("/work-orders/{order_id}")
def create_work_order(order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="주문서를 찾을 수 없습니다.")
    
    # 작업지시서 번호 자동 채번 (YYYYMMDD-N 형식)
    today_str = datetime.now().strftime("%Y%m%d")
    cursor.execute("SELECT COUNT(*) FROM work_orders WHERE work_order_no LIKE ?", (f"{today_str}%",))
    count = cursor.fetchone()[0]
    wo_no = f"{today_str}-{count + 1}"

    p_code = order["product_code"] or ""
    p_name = order["product_name"] or order["product_summary"] or ""
    p_summary = f"[{p_code}] {p_name}" if p_code else p_name

    cursor.execute("""
        INSERT INTO work_orders (work_order_no, order_id, order_no, client_name, product_summary, target_qty, status)
        VALUES (?, ?, ?, ?, ?, ?, '생산대기')
    """, (wo_no, order["order_id"], order["order_no"], order["client_name"], p_summary, order["order_qty"]))
    
    cursor.execute("UPDATE orders SET status = '지시발행완료' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": f"작업지시서({wo_no})가 발행되었습니다."}

@router.delete("/work-orders/{work_order_id}")
def delete_work_order(work_order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM work_orders WHERE work_order_id = ?", (work_order_id,))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "작업지시가 취소되었습니다."}

def get_material_trait(code: str, name: str) -> str:
    c = (code or "").upper()
    n = (name or "").upper()
    # 분말/결정형 원료 (P)
    if "-T" in c or "CRYSTALS" in n or "POWDER" in n or "분말" in n:
        return "P"
    # 응고/결빙성 원료 (S)
    solid_keywords = ["MENTHOL", "CAMPHOR", "BORNEOL", "멘톨", "캠퍼", "보르네올", "SOLID"]
    if any(kw in c or kw in n for kw in solid_keywords):
        return "S"
    return ""

@router.get("/work-orders/{work_order_id}/print")
def print_work_order(work_order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,))
    wo = cursor.fetchone()
    if not wo:
        conn.close()
        raise HTTPException(status_code=404, detail="작업지시서를 찾을 수 없습니다.")
    
    summary = str(wo["product_summary"]).strip()
    
    code_variants = [summary]
    if "[" in summary and "]" in summary:
        code_part = summary.split("]")[0].replace("[", "").strip()
        code_variants.append(code_part)
        if code_part.isdigit():
            code_variants.append(f"AR-{code_part}")
    elif summary.isdigit():
        code_variants.append(f"AR-{summary}")
    elif summary.startswith("AR-"):
        code_variants.append(summary.replace("AR-", ""))

    bom_h = None
    for variant in code_variants:
        cursor.execute("""
            SELECT * FROM bom_headers 
            WHERE product_code = ? 
               OR product_name = ? 
               OR ? LIKE '%' || product_code || '%'
               OR product_code LIKE '%' || ? || '%'
        """, (variant, variant, variant, variant))
        bom_h = cursor.fetchone()
        if bom_h:
            break
    
    items = []
    if bom_h:
        cursor.execute("SELECT * FROM bom_items WHERE bom_id = ?", (bom_h["bom_id"],))
        raw_items = cursor.fetchall()
        for item in raw_items:
            item_dict = dict(item)
            cursor.execute("SELECT category, stock_qty FROM material_masters WHERE material_code = ?", (item_dict["material_code"],))
            mat = cursor.fetchone()
            if mat:
                item_dict["stock_qty"] = mat["stock_qty"] or 0.0
            else:
                item_dict["stock_qty"] = 0.0
            
            # P 또는 S 특성 부여
            item_dict["trait"] = get_material_trait(item_dict["material_code"], item_dict["material_name"])
            items.append(item_dict)
    
    conn.close()
    return {
        "status": "SUCCESS",
        "work_order": dict(wo),
        "bom_items": items
    }
