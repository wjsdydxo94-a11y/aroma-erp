import sqlite3
import csv
import io
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from database import SessionLocal, MaterialMaster

router = APIRouter(prefix="/api/v1", tags=["Orders & Production"])

class OrderRequest(BaseModel):
    order_no: str
    client_name: str
    manager_id: str
    product_summary: str
    order_qty: float
    order_amount: float
    due_date: str
    remark: str = "정상"

class BatchLogRequest(BaseModel):
    batch_id: str
    manifold_id: str
    input_qty: float
    operator_id: str
    product_code: str = None  # BOM 연동을 위한 생산 품목코드

@router.post("/orders")
def create_order(data: OrderRequest):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (order_no, client_name, manager_id, product_summary, order_qty, order_amount, due_date, remark, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data.order_no, data.client_name, data.manager_id, data.product_summary, data.order_qty, data.order_amount, data.due_date, data.remark, "진행중"))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "주문서가 등록되었습니다.", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders")
def get_orders():
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY order_id DESC")
        rows = cursor.fetchall()
        conn.close()
        return {"status": "SUCCESS", "count": len(rows), "data": [dict(row) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/orders/{order_id}")
def delete_order(order_id: int):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
        cursor.execute("DELETE FROM work_orders WHERE order_id = ?", (order_id,))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "주문서가 삭제되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/work-orders")
def create_work_order(order_id: int):
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.close()
            raise HTTPException(status_code=404, detail="해당 주문서를 찾을 수 없습니다.")
        cursor.execute('''
            INSERT INTO work_orders (order_id, order_no, client_name, product_summary, target_qty, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (order['order_id'], order['order_no'], order['client_name'], order['product_summary'], order['order_qty'], "생산지시발행"))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "작업지시서가 발행되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/work-orders")
def get_work_orders():
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM work_orders ORDER BY work_order_id DESC")
        rows = cursor.fetchall()
        conn.close()
        return {"status": "SUCCESS", "count": len(rows), "data": [dict(row) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/work-orders/{work_order_id}")
def delete_work_order(work_order_id: int):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM work_orders WHERE work_order_id = ?", (work_order_id,))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "작업지시가 취소되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/production/batches/log")
def log_batch_input(data: BatchLogRequest):
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. 배치 투입 로그 기록
        cursor.execute('''
            INSERT INTO batch_logs (batch_id, manifold_id, input_qty, operator_id, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (data.batch_id, data.manifold_id, data.input_qty, data.operator_id, "SUCCESS"))
        
        # 2. BOM 기반 원료 재고 자동 차감 연동
        deduction_details = []
        if data.product_code:
            cursor.execute("SELECT bom_id, production_qty FROM bom_headers WHERE product_code = ? ORDER BY bom_id DESC LIMIT 1", (data.product_code,))
            bom_header = cursor.fetchone()
            
            if bom_header:
                bom_id = bom_header['bom_id']
                base_prod_qty = bom_header['production_qty'] or 1.0
                
                cursor.execute("SELECT material_code, qty FROM bom_items WHERE bom_id = ?", (bom_id,))
                bom_items = cursor.fetchall()
                
                db_mat = SessionLocal()
                for item in bom_items:
                    mat_code = item['material_code']
                    unit_qty = item['qty'] or 0.0
                    consumed_qty = unit_qty * (data.input_qty / base_prod_qty)
                    
                    material = db_mat.query(MaterialMaster).filter(MaterialMaster.material_code == mat_code).first()
                    if material:
                        current_stock = material.stock_qty or 0.0
                        material.stock_qty = max(0.0, current_stock - consumed_qty)
                        deduction_details.append(f"{mat_code}: -{consumed_qty:.3f}kg")
                
                db_mat.commit()
                db_mat.close()
        
        conn.commit()
        conn.close()
        return {
            "status": "SUCCESS", 
            "message": "생산 데이터 저장 및 BOM 재고 자동 차감이 완료되었습니다.", 
            "data": data,
            "deduction": deduction_details
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/production/batches")
def get_batch_logs(batch_id: str = None, manifold_id: str = None):
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT log_id, batch_id, manifold_id, input_qty, operator_id, status FROM batch_logs WHERE 1=1"
        params = []
        if batch_id:
            query += " AND batch_id LIKE ?"
            params.append(f"%{batch_id}%")
        if manifold_id:
            query += " AND manifold_id LIKE ?"
            params.append(f"%{manifold_id}%")
        query += " ORDER BY log_id DESC LIMIT 50"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return {"status": "SUCCESS", "count": len(rows), "data": [dict(row) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/production/export/csv")
def export_csv():
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute("SELECT log_id, batch_id, manifold_id, input_qty, operator_id, status FROM batch_logs ORDER BY log_id DESC")
        rows = cursor.fetchall()
        conn.close()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Log ID", "Batch ID", "Manifold ID", "Input Qty (kg)", "Operator ID", "Status"])
        writer.writerows(rows)
        response = Response(content=output.getvalue(), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=batch_production_logs.csv"
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
