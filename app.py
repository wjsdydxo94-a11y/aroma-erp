import sqlite3
import csv
import pandas as pd
import io
from fastapi import FastAPI, HTTPException, Response, HTMLResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from database import engine, Base

# 서버 구동 시 데이터베이스 테이블 자동 생성
Base.metadata.create_all(bind=engine)
app = FastAPI()

# 데이터베이스 및 테이블 초기화
def init_db():
    conn = sqlite3.connect('erp_factory.db')
    cursor = conn.cursor()
    # 1. 생산 투입 이력 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS batch_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT,
            manifold_id TEXT,
            input_qty REAL,
            operator_id TEXT,
            status TEXT
        )
    ''')
    # 2. 주문서 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT,
            client_name TEXT,
            manager_id TEXT,
            product_summary TEXT,
            order_qty REAL,
            order_amount REAL,
            due_date TEXT,
            remark TEXT,
            status TEXT
        )
    ''')
    # 3. 작업지시서(Work Order) 테이블 추가
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS work_orders (
            work_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            order_no TEXT,
            client_name TEXT,
            product_summary TEXT,
            target_qty REAL,
            status TEXT,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 데이터 전송 규격 정의 (데이터 모델)
class BatchLogRequest(BaseModel):
    batch_id: str
    manifold_id: str
    input_qty: float
    operator_id: str

class OrderRequest(BaseModel):
    order_no: str
    client_name: str
    manager_id: str
    product_summary: str
    order_qty: float
    order_amount: float
    due_date: str
    remark: str = "정상"

# 1. 통합 웹 대시보드 화면
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>Aromaresource ERP Operation Engine</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; margin: 30px; background: #f1f5f9; color: #333; }
            h1 { color: #1e293b; font-size: 24px; margin-bottom: 5px; }
            h2 { color: #334155; font-size: 18px; margin-top: 0; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; }
            p { color: #64748b; margin-top: 0; }
            .card { background: #ffffff; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 25px; }
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-top: 15px; }
            .form-group label { display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 5px; }
            .form-group input { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; }
            .btn-group { display: flex; gap: 10px; margin-top: 20px; }
            .btn-submit { background: #2563eb; color: white; border: none; padding: 10px 20px; font-weight: 600; border-radius: 6px; cursor: pointer; }
            .btn-submit:hover { background: #1d4ed8; }
            .btn-order { background: #7c3aed; color: white; border: none; padding: 10px 20px; font-weight: 600; border-radius: 6px; cursor: pointer; }
            .btn-order:hover { background: #6d28d9; }
            .btn-action { background: #0284c7; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
            .btn-action:hover { background: #0369a1; }
            .btn-delete { background: #ef4444; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
            .btn-delete:hover { background: #dc2626; }
            .btn-export { background: #10b981; color: white; border: none; padding: 10px 20px; font-weight: 600; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }
            .btn-export:hover { background: #059669; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
            th, td { padding: 12px 15px; border-bottom: 1px solid #e2e8f0; text-align: left; }
            th { background-color: #1e293b; color: white; font-weight: 600; }
            tr:hover { background-color: #f8fafc; }
            .clickable-no { color: #2563eb; cursor: pointer; font-weight: bold; text-decoration: underline; }
            .clickable-no:hover { color: #1d4ed8; }
            .badge { background: #3b82f6; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
            .badge-success { background: #22c55e; }
            .badge-progress { background: #d97706; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Aromaresource ERP Operation Engine</h1>
            <p>영업 주문 관리, 작업지시 발행 및 현장 생산 공정 통합 시스템</p>
        </div>

        <!-- [1단계] 주문서 등록 및 수정 섹션 -->
        <div class="card">
            <h2>1. 주문서(발주서) 등록 및 수정</h2>
            <p style="font-size: 13px; color: #64748b;">* 목록에서 <b>[일자-No.]</b>를 클릭하면 수정 모드로 전환되며, <b>[지시발행]</b>을 누르면 작업지시서가 생성됩니다.</p>
            <form id="orderForm" onsubmit="submitOrder(event)">
                <div class="form-grid">
                    <div class="form-group">
                        <label>일자-No. (Order No)</label>
                        <input type="text" id="order_no" value="2026/09/09 -1" required>
                    </div>
                    <div class="form-group">
                        <label>거래처명 (Client)</label>
                        <input type="text" id="client_name" value="에이치비티 주식회사" required>
                    </div>
                    <div class="form-group">
                        <label>담당 사원명 (Manager)</label>
                        <input type="text" id="manager_id" value="김동민" required>
                    </div>
                    <div class="form-group">
                        <label>품목명 요약 (Product)</label>
                        <input type="text" id="product_summary" value="TROPICAL AR-4094 외 1건" required>
                    </div>
                    <div class="form-group">
                        <label>주문수량합계 (kg)</label>
                        <input type="number" step="0.001" id="order_qty" value="2000.000" required>
                    </div>
                    <div class="form-group">
                        <label>주문금액합계 (원)</label>
                        <input type="number" id="order_amount" value="0" required>
                    </div>
                    <div class="form-group">
                        <label>납기일자 (Due Date)</label>
                        <input type="date" id="due_date" value="2026-09-25" required>
                    </div>
                    <div class="form-group">
                        <label>비고 (Remark)</label>
                        <input type="text" id="remark" value="보류/예계량">
                    </div>
                </div>
                <div class="btn-group" id="orderBtnContainer">
                    <button type="submit" id="orderSubmitBtn" class="btn-order">신규 주문서 등록</button>
                </div>
            </form>

            <h3 style="margin-top: 30px; font-size: 16px; color: #334155;">등록된 주문서 목록</h3>
            <table>
                <thead>
                    <tr>
                        <th>일자-No.</th>
                        <th>거래처명</th>
                        <th>담당명</th>
                        <th>품목명(요약)</th>
                        <th>주문수량합계</th>
                        <th>주문금액합계</th>
                        <th>납기일자</th>
                        <th>비고</th>
                        <th>진행상태</th>
                        <th>작업지시</th>
                        <th>관리</th>
                    </tr>
                </thead>
                <tbody id="orderTableBody">
                    <tr><td colspan="11" style="text-align: center;">주문서 데이터를 불러오는 중...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- [2단계] 현장 작업지시서(Work Order) 관리 섹션 -->
        <div class="card">
            <h2>2. 현장 작업지시서 (Work Orders) 현황</h2>
            <p style="font-size: 13px; color: #64748b;">* 발행된 작업지시를 바탕으로 향후 BOM 소요량 산출 및 원료 불출 단계로 이어집니다.</p>
            <table>
                <thead>
                    <tr>
                        <th>지시 ID</th>
                        <th>주문번호</th>
                        <th>거래처명</th>
                        <th>품목명(요약)</th>
                        <th>생산 목표량</th>
                        <th>지시상태</th>
                        <th>관리</th>
                    </tr>
                </thead>
                <tbody id="workOrderTableBody">
                    <tr><td colspan="7" style="text-align: center;">작업지시 데이터를 불러오는 중...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- [3단계] 현장 매니폴드 생산 투입 로깅 섹션 -->
        <div class="card">
            <h2>3. 현장 매니폴드 생산 투입 로깅</h2>
            <form id="logForm" onsubmit="submitLog(event)">
                <div class="form-grid">
                    <div class="form-group">
                        <label>배치 번호 (Batch ID)</label>
                        <input type="text" id="batch_id" value="BATCH-2026-09" required>
                    </div>
                    <div class="form-group">
                        <label>매니폴드 ID (Manifold)</label>
                        <input type="text" id="manifold_id" value="MF-01" required>
                    </div>
                    <div class="form-group">
                        <label>투입 중량 (kg, 0.000)</label>
                        <input type="number" step="0.001" id="input_qty" value="15.250" required>
                    </div>
                    <div class="form-group">
                        <label>작업자 ID (Operator)</label>
                        <input type="text" id="operator_id" value="JEON" required>
                    </div>
                </div>
                <div class="btn-group">
                    <button type="submit" class="btn-submit">생산 데이터 전송 및 기록</button>
                    <a href="/api/v1/production/export/csv" class="btn-export">ISO 감사용 엑셀(CSV) 다운로드</a>
                </div>
            </form>

            <h3 style="margin-top: 30px; font-size: 16px; color: #334155;">실시간 투입 이력 리스트</h3>
            <table>
                <thead>
                    <tr>
                        <th>Log ID</th>
                        <th>Batch ID</th>
                        <th>Manifold ID</th>
                        <th>Input Qty (kg)</th>
                        <th>Operator</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="logTableBody">
                    <tr><td colspan="6" style="text-align: center;">이력 데이터를 불러오는 중...</td></tr>
                </tbody>
            </table>
        </div>

        <script>
            let editingOrderId = null;

            // 주문서 목록 로드
            function loadOrders() {
                fetch('/api/v1/orders')
                    .then(res => res.json())
                    .then(data => {
                        const tbody = document.getElementById('orderTableBody');
                        tbody.innerHTML = '';
                        if (data.data.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="11" style="text-align: center;">등록된 주문서가 없습니다.</td></tr>';
                            return;
                        }
                        data.data.forEach(row => {
                            const tr = document.createElement('tr');
                            tr.innerHTML = `
                                <td><span class="clickable-no" onclick='prepareEdit(${JSON.stringify(row)})'>${row.order_no}</span></td>
                                <td>${row.client_name}</td>
                                <td>${row.manager_id}</td>
                                <td>${row.product_summary}</td>
                                <td>${row.order_qty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</td>
                                <td>${row.order_amount.toLocaleString()} 원</td>
                                <td>${row.due_date}</td>
                                <td>${row.remark}</td>
                                <td><span class="badge badge-progress">${row.status}</span></td>
                                <td><button class="btn-action" onclick="createWorkOrder(${row.order_id})">지시발행</button></td>
                                <td><button class="btn-delete" onclick="deleteOrder(${row.order_id})">삭제</button></td>
                            `;
                            tbody.appendChild(tr);
                        });
                    });
            }

            // 작업지시서 목록 로드
            function loadWorkOrders() {
                fetch('/api/v1/work-orders')
                    .then(res => res.json())
                    .then(data => {
                        const tbody = document.getElementById('workOrderTableBody');
                        tbody.innerHTML = '';
                        if (data.data.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center;">발행된 작업지시서가 없습니다.</td></tr>';
                            return;
                        }
                        data.data.forEach(row => {
                            const tr = document.createElement('tr');
                            tr.innerHTML = `
                                <td><strong>WO-${row.work_order_id}</strong></td>
                                <td>${row.order_no}</td>
                                <td>${row.client_name}</td>
                                <td>${row.product_summary}</td>
                                <td>${row.target_qty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</td>
                                <td><span class="badge badge-success">${row.status}</span></td>
                                <td><button class="btn-delete" onclick="deleteWorkOrder(${row.work_order_id})">취소</button></td>
                            `;
                            tbody.appendChild(tr);
                        });
                    });
            }

            // 작업지시 발행 요청
            function createWorkOrder(orderId) {
                fetch(`/api/v1/work-orders?order_id=${orderId}`, {
                    method: 'POST'
                })
                .then(res => res.json())
                .then(resData => {
                    if (resData.status === "SUCCESS") {
                        alert("작업지시서가 성공적으로 발행되었습니다.");
                        loadOrders();
                        loadWorkOrders();
                    } else {
                        alert("발행 실패: " + (resData.detail || JSON.stringify(resData)));
                    }
                })
                .catch(err => {
                    alert("통신 에러 발생: " + err);
                });
            }

            // 작업지시 삭제 요청
            function deleteWorkOrder(woId) {
                if (!confirm("이 작업지시를 취소(삭제)하시겠습니까?")) return;

                fetch(`/api/v1/work-orders/${woId}`, {
                    method: 'DELETE'
                })
                .then(res => res.json())
                .then(resData => {
                    if (resData.status === "SUCCESS") {
                        alert("작업지시가 취소되었습니다.");
                        loadWorkOrders();
                    } else {
                        alert("취소 실패: " + JSON.stringify(resData));
                    }
                })
                .catch(err => {
                    alert("통신 에러 발생: " + err);
                });
            }

            // 수정 모드로 데이터 세팅
            function prepareEdit(row) {
                editingOrderId = row.order_id;
                document.getElementById('order_no').value = row.order_no;
                document.getElementById('client_name').value = row.client_name;
                document.getElementById('manager_id').value = row.manager_id;
                document.getElementById('product_summary').value = row.product_summary;
                document.getElementById('order_qty').value = row.order_qty;
                document.getElementById('order_amount').value = row.order_amount;
                document.getElementById('due_date').value = row.due_date;
                document.getElementById('remark').value = row.remark;

                const submitBtn = document.getElementById('orderSubmitBtn');
                submitBtn.innerText = "주문서 수정 저장";
                submitBtn.style.background = "#d97706";

                if (!document.getElementById('cancelEditBtn')) {
                    const cancelBtn = document.createElement('button');
                    cancelBtn.type = 'button';
                    cancelBtn.id = 'cancelEditBtn';
                    cancelBtn.className = 'btn-order';
                    cancelBtn.style.background = '#64748b';
                    cancelBtn.innerText = '수정 취소';
                    cancelBtn.onclick = resetOrderForm;
                    document.getElementById('orderBtnContainer').appendChild(cancelBtn);
                }
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }

            function resetOrderForm() {
                editingOrderId = null;
                document.getElementById('orderForm').reset();
                document.getElementById('order_no').value = "2026/09/09 -2";
                const submitBtn = document.getElementById('orderSubmitBtn');
                submitBtn.innerText = "신규 주문서 등록";
                submitBtn.style.background = "#7c3aed";
                const cancelBtn = document.getElementById('cancelEditBtn');
                if (cancelBtn) cancelBtn.remove();
            }

            function submitOrder(event) {
                event.preventDefault();
                const payload = {
                    order_no: document.getElementById('order_no').value,
                    client_name: document.getElementById('client_name').value,
                    manager_id: document.getElementById('manager_id').value,
                    product_summary: document.getElementById('product_summary').value,
                    order_qty: parseFloat(document.getElementById('order_qty').value),
                    order_amount: parseFloat(document.getElementById('order_amount').value),
                    due_date: document.getElementById('due_date').value,
                    remark: document.getElementById('remark').value
                };

                const url = editingOrderId ? `/api/v1/orders/${editingOrderId}` : '/api/v1/orders';
                const method = editingOrderId ? 'PUT' : 'POST';

                fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(resData => {
                    if (resData.status === "SUCCESS") {
                        alert(editingOrderId ? "주문서가 수정되었습니다." : "주문서가 등록되었습니다.");
                        resetOrderForm();
                        loadOrders();
                    } else {
                        alert("처리 실패: " + JSON.stringify(resData));
                    }
                })
                .catch(err => {
                    alert("통신 에러 발생: " + err);
                });
            }

            function deleteOrder(orderId) {
                if (!confirm("정말 이 주문서를 삭제하시겠습니까?")) return;

                fetch(`/api/v1/orders/${orderId}`, {
                    method: 'DELETE'
                })
                .then(res => res.json())
                .then(resData => {
                    if (resData.status === "SUCCESS") {
                        alert("주문서가 삭제되었습니다.");
                        loadOrders();
                        loadWorkOrders();
                    } else {
                        alert("삭제 실패: " + JSON.stringify(resData));
                    }
                })
                .catch(err => {
                    alert("통신 에러 발생: " + err);
                });
            }

            function loadLogs() {
                fetch('/api/v1/production/batches')
                    .then(res => res.json())
                    .then(data => {
                        const tbody = document.getElementById('logTableBody');
                        tbody.innerHTML = '';
                        if (data.data.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">저장된 이력이 없습니다.</td></tr>';
                            return;
                        }
                        data.data.forEach(row => {
                            const tr = document.createElement('tr');
                            tr.innerHTML = `
                                <td>${row.log_id}</td>
                                <td><strong>${row.batch_id}</strong></td>
                                <td>${row.manifold_id}</td>
                                <td>${row.input_qty.toFixed(3)} kg</td>
                                <td>${row.operator_id}</td>
                                <td><span class="badge badge-success">${row.status}</span></td>
                            `;
                            tbody.appendChild(tr);
                        });
                    });
            }

            function submitLog(event) {
                event.preventDefault();
                const payload = {
                    batch_id: document.getElementById('batch_id').value,
                    manifold_id: document.getElementById('manifold_id').value,
                    input_qty: parseFloat(document.getElementById('input_qty').value),
                    operator_id: document.getElementById('operator_id').value
                };

                fetch('/api/v1/production/batches/log', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(resData => {
                    if (resData.status === "SUCCESS") {
                        alert("투입 이력이 성공적으로 저장되었습니다.");
                        loadLogs();
                    } else {
                        alert("저장 실패: " + JSON.stringify(resData));
                    }
                })
                .catch(err => {
                    alert("통신 에러 발생: " + err);
                });
            }

            // 초기 로딩
            loadOrders();
            loadWorkOrders();
            loadLogs();
        </script>
    </body>
    </html>
    """

# --- API 엔드포인트 ---

@app.post("/api/v1/orders")
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

@app.get("/api/v1/orders")
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

@app.put("/api/v1/orders/{order_id}")
def update_order(order_id: int, data: OrderRequest):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE orders 
            SET order_no = ?, client_name = ?, manager_id = ?, product_summary = ?, 
                order_qty = ?, order_amount = ?, due_date = ?, remark = ?
            WHERE order_id = ?
        ''', (data.order_no, data.client_name, data.manager_id, data.product_summary, 
              data.order_qty, data.order_amount, data.due_date, data.remark, order_id))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "주문서가 수정되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/orders/{order_id}")
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

# 작업지시서 생성 API (POST)
@app.post("/api/v1/work-orders")
def create_work_order(order_id: int):
    try:
        conn = sqlite3.connect('erp_factory.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 주문서 정보 조회
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.close()
            raise HTTPException(status_code=404, detail="해당 주문서를 찾을 수 없습니다.")
        
        # 작업지시서 발행
        cursor.execute('''
            INSERT INTO work_orders (order_id, order_no, client_name, product_summary, target_qty, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (order['order_id'], order['order_no'], order['client_name'], order['product_summary'], order['order_qty'], "생산지시발행"))
        
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "작업지시서가 발행되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 작업지시서 목록 조회 API (GET)
@app.get("/api/v1/work-orders")
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

# 작업지시서 삭제(취소) API (DELETE)
@app.delete("/api/v1/work-orders/{work_order_id}")
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

@app.post("/api/v1/production/batches/log")
def log_batch_input(data: BatchLogRequest):
    try:
        conn = sqlite3.connect('erp_factory.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO batch_logs (batch_id, manifold_id, input_qty, operator_id, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (data.batch_id, data.manifold_id, data.input_qty, data.operator_id, "SUCCESS"))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": "저장되었습니다.", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/production/batches")
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

@app.get("/api/v1/production/export/csv")
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
        import pandas as pd
from fastapi import File, UploadFile
from database import SessionLocal, MaterialMaster

@app.post("/api/v1/materials/upload")
async def upload_materials(file: UploadFile = File(...)):
    try:
        df = pd.read_excel(file.file)
        db = SessionLocal()
        
        for _, row in df.iterrows():
            material_code = str(row.get("원료코드", ""))
            if not material_code or material_code == "nan":
                continue
                
            existing = db.query(MaterialMaster).filter(MaterialMaster.material_code == material_code).first()
            
            if existing:
                existing.material_name_kr = str(row.get("원료명(국문)", ""))
                existing.material_name_en = str(row.get("원료명(영문)", ""))
                existing.cas_no = str(row.get("CAS 번호", ""))
                existing.supplier = str(row.get("공급사", ""))
                existing.unit = str(row.get("관리단위", "Kg"))
                existing.category = str(row.get("원료분류", ""))
            else:
                new_material = MaterialMaster(
                    material_code=material_code,
                    material_name_kr=str(row.get("원료명(국문)", "")),
                    material_name_en=str(row.get("원료명(영문)", "")),
                    cas_no=str(row.get("CAS 번호", "")),
                    supplier=str(row.get("공급사", "")),
                    unit=str(row.get("관리단위", "Kg")),
                    category=str(row.get("원료분류", ""))
                )
                db.add(new_material)
                
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": f"총 {len(df)}건의 원료 데이터가 성공적으로 적재되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>Aroma Resource ERP</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { display: flex; height: 100vh; overflow: hidden; background-color: #F8FAFC; }
            .aroma-sidebar {
              width: 260px;
              height: 100vh;
              background-color: #1E242B;
              color: #E2E8F0;
              font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
              display: flex;
              flex-direction: column;
              box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15);
            }
            .sidebar-header {
              padding: 24px 20px 18px 20px;
              border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
            .brand-logo-area {
              display: flex;
              flex-direction: column;
              gap: 6px;
            }
            .logo-text {
              font-size: 19px;
              font-weight: 700;
              color: #FFFFFF;
              letter-spacing: -0.5px;
            }
            .logo-wave-line {
              height: 3px;
              width: 100%;
              background: linear-gradient(90deg, #00A8FF 0%, #0077FF 100%);
              border-radius: 2px;
            }
            .sidebar-header .sub-title {
              display: block;
              font-size: 10px;
              color: #8C9BA5;
              text-transform: uppercase;
              letter-spacing: 1px;
              margin-top: 8px;
            }
            .sidebar-nav {
              padding: 15px 10px;
              overflow-y: auto;
              flex: 1;
            }
            .sidebar-nav::-webkit-scrollbar { width: 4px; }
            .sidebar-nav::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 2px; }
            .aroma-sidebar details {
              margin-bottom: 6px;
              border-radius: 6px;
              transition: background 0.2s;
            }
            .aroma-sidebar details[open] { background-color: rgba(255, 255, 255, 0.02); }
            .aroma-sidebar summary {
              padding: 11px 14px;
              font-size: 13.5px;
              font-weight: 500;
              cursor: pointer;
              color: #CBD5E1;
              list-style: none;
              border-radius: 6px;
              display: flex;
              align-items: center;
              justify-content: space-between;
            }
            .aroma-sidebar summary::-webkit-details-marker { display: none; }
            .aroma-sidebar summary:hover {
              background-color: rgba(0, 168, 255, 0.08);
              color: #00A8FF;
            }
            .aroma-sidebar ul {
              list-style: none;
              padding: 4px 0 6px 14px;
              margin: 0;
            }
            .aroma-sidebar li a {
              display: block;
              padding: 7px 12px;
              font-size: 12.5px;
              color: #94A3B8;
              text-decoration: none;
              border-radius: 4px;
              transition: all 0.2s ease;
            }
            .aroma-sidebar li a:hover {
              color: #FFFFFF;
              background-color: rgba(0, 168, 255, 0.12);
              padding-left: 15px;
            }
            .aroma-sidebar li a.active {
              color: #FFFFFF;
              background: linear-gradient(90deg, rgba(0, 168, 255, 0.25) 0%, rgba(0, 119, 255, 0.05) 100%);
              border-left: 3px solid #00A8FF;
              padding-left: 12px;
              font-weight: 600;
            }
            .main-content {
              flex: 1;
              padding: 40px;
              overflow-y: auto;
            }
            .main-content h1 { color: #1E242B; font-size: 24px; margin-bottom: 10px; }
            .main-content p { color: #64748B; font-size: 14px; }
        </style>
    </head>
    <body>
        <aside class="aroma-sidebar">
          <div class="sidebar-header">
            <div class="brand-logo-area">
              <span class="logo-text">Aroma Resource</span>
              <div class="logo-wave-line"></div>
            </div>
            <span class="sub-title">ERP Management System</span>
          </div>
          <nav class="sidebar-nav">
            <details>
              <summary>견적서 관리</summary>
              <ul>
                <li><a href="#">견적 입력</a></li>
                <li><a href="#">견적 조회 및 현황</a></li>
              </ul>
            </details>
            <details>
              <summary>주문서 관리</summary>
              <ul>
                <li><a href="#">주문 등록</a></li>
                <li><a href="#">주문서 조회</a></li>
              </ul>
            </details>
            <details>
              <summary>판매 관리</summary>
              <ul>
                <li><a href="#">판매 조회</a></li>
                <li><a href="#">판매 입력</a></li>
                <li><a href="#">판매 현황</a></li>
                <li><a href="#">거래명세서 인쇄</a></li>
              </ul>
            </details>
            <details>
              <summary>입고 / 구매</summary>
              <ul>
                <li><a href="#">발주 관리</a></li>
                <li><a href="#">입고 등록 및 검수</a></li>
              </ul>
            </details>
            <details open>
              <summary>원료 마스터 관리</summary>
              <ul>
                <li><a href="#" class="active">원료 리스트 조회 (7,507건)</a></li>
                <li><a href="#">원료 마스터 일괄 업로드</a></li>
              </ul>
            </details>
            <details>
              <summary>생산 및 배치</summary>
              <ul>
                <li><a href="#">작업 지시서</a></li>
                <li><a href="#">배치 투입 이력</a></li>
              </ul>
            </details>
          </nav>
        </aside>
        <main class="main-content">
            <h1>아로마리소스 통합 ERP 시스템</h1>
            <p>좌측 메뉴를 통해 견적, 주문, 판매, 입고, 원료 마스터(7,507건 적재 완료) 및 생산 관리를 수행할 수 있습니다.</p>
        </main>
    </body>
    </html>
    """
