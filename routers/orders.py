from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sqlite3

router = APIRouter(prefix="/api/v1", tags=["orders"])

def get_db_connection():
    conn = sqlite3.connect('erp_factory.db')
    conn.row_factory = sqlite3.Row
    return conn

class OrderModel(BaseModel):
    order_no: str
    client_name: str
    manager_id: str
    product_summary: str
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
    cursor.execute("""
        INSERT INTO orders (order_no, client_name, manager_id, product_summary, order_qty, order_amount, due_date, remark, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '진행중')
    """, (order.order_no, order.client_name, order.manager_id, order.product_summary, order.order_qty, order.order_amount, order.due_date, order.remark))
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
    
    cursor.execute("""
        INSERT INTO work_orders (order_id, order_no, client_name, product_summary, target_qty, status)
        VALUES (?, ?, ?, ?, ?, '생산대기')
    """, (order["order_id"], order["order_no"], order["client_name"], order["product_summary"], order["order_qty"]))
    
    cursor.execute("UPDATE orders SET status = '지시발행완료' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "작업지시서가 발행되었습니다."}

@router.delete("/work-orders/{work_order_id}")
def delete_work_order(work_order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM work_orders WHERE work_order_id = ?", (work_order_id,))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "작업지시가 취소되었습니다."}

@router.get("/work-orders/{work_order_id}/print")
def print_work_order(work_order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,))
    wo = cursor.fetchone()
    if not wo:
        conn.close()
        raise HTTPException(status_code=404, detail="작업지시서를 찾을 수 없습니다.")
    
    # product_summary 또는 연동된 품목의 BOM 아이템 조회 시도
    cursor.execute("SELECT * FROM bom_headers WHERE product_code = ? OR product_name = ?", (wo["product_summary"], wo["product_summary"]))
    bom_h = cursor.fetchone()
    items = []
    if bom_h:
        cursor.execute("SELECT * FROM bom_items WHERE bom_id = ?", (bom_h["bom_id"],))
        items = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "status": "SUCCESS",
        "work_order": dict(wo),
        "bom_items": items
    }
