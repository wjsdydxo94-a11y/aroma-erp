import sqlite3
import csv
import io
import os
import glob
import pandas as pd
from fastapi import FastAPI, HTTPException, Response, File, UploadFile, Query, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List
from database import engine, Base, SessionLocal, MaterialMaster

Base.metadata.create_all(bind=engine)
app = FastAPI()

def init_db():
    conn = sqlite3.connect('erp_factory.db')
    cursor = conn.cursor()
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bom_headers (
            bom_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code TEXT,
            product_name TEXT,
            process_code TEXT,
            bom_version TEXT,
            is_default INTEGER DEFAULT 1,
            production_qty REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bom_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bom_id INTEGER,
            material_code TEXT,
            material_name TEXT,
            qty REAL,
            unit TEXT,
            cas_no TEXT,
            location TEXT,
            item_bom_version TEXT,
            FOREIGN KEY (bom_id) REFERENCES bom_headers (bom_id)
        )
    ''')
    try:
        cursor.execute("ALTER TABLE material_masters ADD COLUMN remark TEXT;")
        conn.commit()
    except Exception:
        pass

    conn.commit()
    conn.close()
    
    auto_seed_materials()
    bulk_update_categories()

def auto_seed_materials():
    db = SessionLocal()
    count = db.query(MaterialMaster).count()
    if count == 0:
        excel_files = glob.glob("*.xlsx")
        file_path = None
        for f in excel_files:
            if "원료" in f or "material" in f.lower():
                file_path = f
                break
        if not file_path and excel_files:
            file_path = excel_files[0]

        if file_path and os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path, header=None)
                success_count = 0
                for idx, row in df.iterrows():
                    vals = [str(val).strip() for val in row.values]
                    if not vals or all(v == "" or v.lower() in ["nan", "none"] for v in vals):
                        continue
                    row_str = " ".join(vals)
                    if any(keyword in row_str for keyword in ["회사명", "사업자", "대표", "주소", "TEL", "FAX"]):
                        continue
                    if ("코드" in row_str or "품목코드" in row_str or "원료코드" in row_str) and ("명" in row_str or "규격" in row_str):
                        continue
                    
                    material_code = vals[0] if len(vals) > 0 else ""
                    if not material_code or material_code.lower() in ["nan", "none", "", "품목코드", "원료코드", "code", "코드"] or "회사명" in material_code:
                        continue
                    
                    name_kr = vals[1] if len(vals) > 1 else ""
                    name_en = vals[2] if len(vals) > 2 else ""
                    cas_no, supplier = "", ""
                    
                    for v in vals:
                        if "-" in v and len(v) >= 7 and any(char.isdigit() for char in v) and len(v.split("-")) >= 2:
                            parts = v.split("-")
                            if len(parts[0]) >= 2 and len(parts[-1]) >= 1 and parts[0].isdigit():
                                cas_no = v
                        if any(kw in v for kw in ["주식회사", "코퍼레이션", "사", "AROMA", "LLC", "주", "유한"]):
                            if len(v) < 30 and v != name_kr:
                                supplier = v

                    if name_kr.lower() in ["nan", "none"]: name_kr = ""
                    if name_en.lower() in ["nan", "none"]: name_en = ""
                    if cas_no.lower() in ["nan", "none"]: cas_no = ""
                    if supplier.lower() in ["nan", "none"]: supplier = ""

                    cat = "원재료"
                    if material_code.startswith("AR-"):
                        cat = "제품"
                    elif material_code.startswith("1-") or material_code.startswith("2-") or material_code.startswith("3-"):
                        cat = "원재료"
                    elif material_code.startswith("CB-"):
                        cat = "반제품"

                    new_material = MaterialMaster(
                        material_code=material_code,
                        material_name_kr=name_kr,
                        material_name_en=name_en,
                        cas_no=cas_no,
                        supplier=supplier,
                        unit="Kg",
                        category=cat
                    )
                    if hasattr(new_material, 'remark'):
                        new_material.remark = ""
                    db.add(new_material)
                    success_count += 1
                db.commit()
                print(f"[Auto-Seed] 총 {success_count}건의 원료 데이터가 자동으로 적재되었습니다.")
            except Exception as e:
                print(f"[Auto-Seed Error] {e}")
    db.close()

def bulk_update_categories():
    db = SessionLocal()
    try:
        materials = db.query(MaterialMaster).all()
        for m in materials:
            code = str(m.material_code).strip()
            new_cat = m.category or "원재료"
            if code.startswith("AR-"):
                new_cat = "제품"
            elif code.startswith("1-") or code.startswith("2-") or code.startswith("3-"):
                new_cat = "원재료"
            elif code.startswith("CB-"):
                new_cat = "반제품"
            
            if m.category != new_cat:
                m.category = new_cat
        db.commit()
    except Exception as e:
        print(f"[Bulk Update Error] {e}")
    finally:
        db.close()

init_db()

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

class MaterialRequest(BaseModel):
    material_code: str
    material_name_kr: str
    material_name_en: str
    cas_no: str
    supplier: str
    unit: str = "Kg"
    category: str = "원재료"
    remark: str = ""

class BatchDeleteRequest(BaseModel):
    ids: List[int]

class BomSaveRequest(BaseModel):
    product_code: str
    product_name: str
    bom_version: str = "1"
    items: List[dict]

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>Aroma Resource ERP System</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { display: flex; height: 100vh; overflow: hidden; background-color: #F8FAFC; font-family: 'Pretendard', -apple-system, sans-serif; }
            
            .aroma-sidebar {
              width: 260px; height: 100vh; background-color: #1E242B; color: #E2E8F0;
              display: flex; flex-direction: column; box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15); flex-shrink: 0;
            }
            .sidebar-header { padding: 24px 20px 18px 20px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
            .brand-logo-area { display: flex; flex-direction: column; gap: 6px; }
            .logo-text { font-size: 19px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.5px; }
            .logo-wave-line { height: 3px; width: 100%; background: linear-gradient(90deg, #00A8FF 0%, #0077FF 100%); border-radius: 2px; }
            .sidebar-header .sub-title { display: block; font-size: 10px; color: #8C9BA5; text-transform: uppercase; letter-spacing: 1px; margin-top: 8px; }
            .sidebar-nav { padding: 15px 10px; overflow-y: auto; flex: 1; }
            .sidebar-nav::-webkit-scrollbar { width: 4px; }
            .sidebar-nav::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 2px; }
            .aroma-sidebar details { margin-bottom: 6px; border-radius: 6px; transition: background 0.2s; }
            .aroma-sidebar details[open] { background-color: rgba(255, 255, 255, 0.02); }
            .aroma-sidebar summary {
              padding: 11px 14px; font-size: 13.5px; font-weight: 500; cursor: pointer; color: #CBD5E1;
              list-style: none; border-radius: 6px; display: flex; align-items: center; justify-content: space-between;
            }
            .aroma-sidebar summary::-webkit-details-marker { display: none; }
            .aroma-sidebar summary:hover { background-color: rgba(0, 168, 255, 0.08); color: #00A8FF; }
            .aroma-sidebar ul { list-style: none; padding: 4px 0 6px 14px; margin: 0; }
            .aroma-sidebar li a {
              display: block; padding: 7px 12px; font-size: 12.5px; color: #94A3B8; text-decoration: none; border-radius: 4px; cursor: pointer; transition: all 0.2s ease;
            }
            .aroma-sidebar li a:hover { color: #FFFFFF; background-color: rgba(0, 168, 255, 0.12); padding-left: 15px; }
            .aroma-sidebar li a.active {
              color: #FFFFFF; background: linear-gradient(90deg, rgba(0, 168, 255, 0.25) 0%, rgba(0, 119, 255, 0.05) 100%);
              border-left: 3px solid #00A8FF; padding-left: 12px; font-weight: 600;
            }

            .main-content { flex: 1; padding: 30px; overflow-y: auto; }
            .tab-content { display: none; }
            .tab-content.active { display: block; }
            
            h1 { color: #1e293b; font-size: 22px; margin-bottom: 5px; }
            h2 { color: #334155; font-size: 16px; margin-top: 0; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; }
            p { color: #64748b; margin-top: 0; font-size: 13px; }
            .card { background: #ffffff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 20px; }
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 12px; }
            .form-group label { display: block; font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 4px; }
            .form-group input, .form-group select { width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; font-size: 13px; background: #fff; }
            .btn-group { display: flex; gap: 10px; margin-top: 15px; }
            .btn-submit { background: #2563eb; color: white; border: none; padding: 8px 16px; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 13px; }
            .btn-order { background: #0077FF; color: white; border: none; padding: 8px 16px; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 13px; }
            .btn-action { background: #0284c7; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
            .btn-delete { background: #ef4444; color: white; border: none; padding: 8px 16px; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 13px; }
            .btn-export { background: #10b981; color: white; border: none; padding: 8px 16px; font-weight: 600; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; font-size: 13px; }
            
            table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
            th, td { padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: left; }
            th { background-color: #1E242B; color: white; font-weight: 600; }
            tr:hover { background-color: #f8fafc; }
            .clickable-no { color: #0077FF; cursor: pointer; font-weight: bold; text-decoration: underline; }
            .badge { background: #3b82f6; color: white; padding: 3px 6px; border-radius: 4px; font-size: 11px; }
            .badge-success { background: #22c55e; }
            .badge-progress { background: #d97706; }

            .search-bar { display: flex; gap: 10px; margin-bottom: 15px; align-items: center; justify-content: space-between; }
            .search-left { display: flex; gap: 10px; align-items: center; }
            .search-bar input { padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; width: 260px; font-size: 13px; }
            .pagination { display: flex; justify-content: center; gap: 5px; margin-top: 20px; align-items: center; }
            .pagination button { padding: 6px 12px; border: 1px solid #cbd5e1; background: white; border-radius: 4px; cursor: pointer; font-size: 13px; }
            .pagination button.active { background: #0077FF; color: white; border-color: #0077FF; }
            .pagination button:disabled { background: #f1f5f9; color: #94a3b8; cursor: not-allowed; }

            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); justify-content: center; align-items: center; z-index: 1000; }
            .modal-content { background: white; padding: 25px; border-radius: 10px; width: 500px; max-height: 90vh; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
            .modal-header { font-size: 16px; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; display: flex; justify-content: space-between; align-items: center; color: #1e293b; }
            .modal-close { cursor: pointer; font-size: 18px; color: #64748b; }
            .modal-body .form-group { margin-bottom: 12px; }
            .modal-body label { display: block; font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 4px; }
            .modal-body input, .modal-body select { width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; box-sizing: border-box; }
            .modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
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
              <ul><li><a onclick="switchTab('orders-tab')">견적 입력/조회</a></li></ul>
            </details>
            <details open>
              <summary>주문서 관리</summary>
              <ul><li><a class="active" onclick="switchTab('orders-tab')">주문 등록 및 조회</a></li></ul>
            </details>
            <details>
              <summary>판매 관리</summary>
              <ul><li><a onclick="switchTab('orders-tab')">판매 조회 및 입력</a></li></ul>
            </details>
            <details>
              <summary>입고 / 구매</summary>
              <ul><li><a onclick="switchTab('orders-tab')">발주 및 입고 관리</a></li></ul>
            </details>
            <details open>
              <summary>원료 마스터 관리</summary>
              <ul>
                <li><a onclick="switchTab('materials-tab')">원료 마스터 통합 관리</a></li>
              </ul>
            </details>
            <details open>
              <summary>생산 및 배치</summary>
              <ul>
                <li><a onclick="switchTab('orders-tab')">작업 지시서 및 투입이력</a></li>
                <li><a onclick="switchTab('bom-tab')">BOM 조회 및 관리</a></li>
              </ul>
            </details>
          </nav>
        </aside>

        <main class="main-content">
            <!-- [탭 1] 주문 및 생산 관리 탭 -->
            <div id="orders-tab" class="tab-content active">
                <div class="card">
                    <h1>아로마리소스 통합 ERP 시스템</h1>
                    <p>영업 주문 관리, 작업지시 발행 및 현장 생산 공정 통합 제어 패널</p>
                </div>

                <div class="card">
                    <h2>1. 주문서(발주서) 등록 및 관리</h2>
                    <form id="orderForm" onsubmit="submitOrder(event)">
                        <div class="form-grid">
                            <div class="form-group"><label>일자-No.</label><input type="text" id="order_no" value="2026/09/10 -1" required></div>
                            <div class="form-group"><label>거래처명</label><input type="text" id="client_name" value="에이치비티 주식회사" required></div>
                            <div class="form-group"><label>담당 사원명</label><input type="text" id="manager_id" value="전용태" required></div>
                            <div class="form-group"><label>품목명 요약</label><input type="text" id="product_summary" value="TROPICAL AR-4094" required></div>
                            <div class="form-group"><label>주문수량합계 (kg)</label><input type="number" step="0.001" id="order_qty" value="2000.000" required></div>
                            <div class="form-group"><label>주문금액합계 (원)</label><input type="number" id="order_amount" value="0" required></div>
                            <div class="form-group"><label>납기일자</label><input type="date" id="due_date" value="2026-09-25" required></div>
                            <div class="form-group"><label>비고</label><input type="text" id="remark" value="정상"></div>
                        </div>
                        <div class="btn-group" id="orderBtnContainer">
                            <button type="submit" id="orderSubmitBtn" class="btn-order">신규 주문서 등록</button>
                        </div>
                    </form>

                    <h3 style="margin-top: 20px; font-size: 14px; color: #334155;">등록된 주문서 목록</h3>
                    <table>
                        <thead>
                            <tr><th>일자-No.</th><th>거래처명</th><th>담당명</th><th>품목명(요약)</th><th>주문수량</th><th>주문금액</th><th>납기일자</th><th>비고</th><th>상태</th><th>작업지시</th><th>관리</th></tr>
                        </thead>
                        <tbody id="orderTableBody"><tr><td colspan="11" style="text-align: center;">불러오는 중...</td></tr></tbody>
                    </table>
                </div>

                <div class="card">
                    <h2>2. 현장 작업지시서 (Work Orders)</h2>
                    <table>
                        <thead>
                            <tr><th>지시 ID</th><th>주문번호</th><th>거래처명</th><th>품목명(요약)</th><th>생산 목표량</th><th>상태</th><th>관리</th></tr>
                        </thead>
                        <tbody id="workOrderTableBody"><tr><td colspan="7" style="text-align: center;">발행된 작업지시서가 없습니다.</td></tr></tbody>
                    </table>
                </div>

                <div class="card">
                    <h2>3. 현장 매니폴드 생산 투입 로깅</h2>
                    <form id="logForm" onsubmit="submitLog(event)">
                        <div class="form-grid">
                            <div class="form-group"><label>배치 번호</label><input type="text" id="batch_id" value="BATCH-2026-09" required></div>
                            <div class="form-group"><label>매니폴드 ID</label><input type="text" id="manifold_id" value="MF-01" required></div>
                            <div class="form-group"><label>투입 중량 (kg)</label><input type="number" step="0.001" id="input_qty" value="15.250" required></div>
                            <div class="form-group"><label>작업자 ID</label><input type="text" id="operator_id" value="JEON" required></div>
                        </div>
                        <div class="btn-group">
                            <button type="submit" class="btn-submit">생산 데이터 전송</button>
                            <a href="/api/v1/production/export/csv" class="btn-export">ISO 감사용 CSV 다운로드</a>
                        </div>
                    </form>

                    <h3 style="margin-top: 20px; font-size: 14px; color: #334155;">실시간 투입 이력</h3>
                    <table>
                        <thead>
                            <tr><th>Log ID</th><th>Batch ID</th><th>Manifold ID</th><th>Input Qty</th><th>Operator</th><th>Status</th></tr>
                        </thead>
                        <tbody id="logTableBody"><tr><td colspan="6" style="text-align: center;">이력이 없습니다.</td></tr></tbody>
                    </table>
                </div>
            </div>

            <!-- [탭 2] 원료 마스터 통합 관리 탭 -->
            <div id="materials-tab" class="tab-content">
                <div class="card">
                    <h1>원료 마스터 관리 (Raw Material Master)</h1>
                    <p>아로마리소스 향료 원료 품목 리스트 조회, 검색, 수정 및 신규 등록 관리 (구분: 원재료/제품/반제품/상품)</p>
                </div>

                <div class="card">
                    <h2>품목등록 리스트 (데이터베이스 연동)</h2>
                    
                    <div class="search-bar" style="margin-top: 15px;">
                        <div class="search-left">
                            <input type="text" id="searchInput" placeholder="원료코드, 원료명, CAS No, 공급사 검색..." onkeyup="if(event.key==='Enter') searchMaterials()">
                            <button type="button" class="btn-action" onclick="searchMaterials()" style="padding: 8px 14px;">검색</button>
                            <button type="button" class="btn-delete" onclick="resetSearch()" style="padding: 8px 14px; background:#64748b;">초기화</button>
                        </div>
                        <div style="display: flex; gap: 10px;">
                            <button type="button" class="btn-delete" onclick="deleteSelectedMaterials()">선택 삭제</button>
                            <button type="button" class="btn-order" onclick="openCreateModal()">신규 원료 등록</button>
                        </div>
                    </div>

                    <table>
                        <thead>
                            <tr>
                                <th style="width: 40px;"><input type="checkbox" id="selectAll" onclick="toggleSelectAll(this)"></th>
                                <th style="width: 60px;">순번</th>
                                <th>원료코드</th>
                                <th>원료명(국문)</th>
                                <th>원료명(영문)</th>
                                <th>CAS No.</th>
                                <th>공급사</th>
                                <th>원료구분</th>
                                <th>적요/비고</th>
                            </tr>
                        </thead>
                        <tbody id="materialTableBody">
                            <tr><td colspan="9" style="text-align: center;">원료 데이터를 불러오는 중...</td></tr>
                        </tbody>
                    </table>

                    <div class="pagination" id="paginationContainer"></div>
                </div>
            </div>

            <!-- [탭 3] BOM 조회 및 관리 탭 -->
            <div id="bom-tab" class="tab-content">
                <div class="card">
                    <h1>BOM(소요량) 조회 및 관리</h1>
                    <p>품목코드를 클릭하면 개별 품목의 처방(BOM)을 등록하거나 수정할 수 있습니다.</p>
                </div>

                <div class="card">
                    <h2>BOM 대상 품목 리스트</h2>
                    
                    <div class="search-bar" style="margin-top: 15px;">
                        <div class="search-left">
                            <input type="text" id="bomSearchInput" placeholder="품목코드 또는 품목명 검색..." onkeyup="if(event.key==='Enter') searchBomMaterials()">
                            <button type="button" class="btn-action" onclick="searchBomMaterials()" style="padding: 8px 14px;">검색</button>
                            <button type="button" class="btn-delete" onclick="resetBomSearch()" style="padding: 8px 14px; background:#64748b;">초기화</button>
                        </div>
                    </div>

                    <table>
                        <thead>
                            <tr>
                                <th style="width: 60px;">순번</th>
                                <th>품목코드</th>
                                <th>원료명(국문)</th>
                                <th>원료명(영문)</th>
                                <th>CAS No.</th>
                                <th>공급사</th>
                                <th>원료구분</th>
                                <th>적요/비고</th>
                                <th>관리</th>
                            </tr>
                        </thead>
                        <tbody id="bomMaterialTableBody">
                            <tr><td colspan="9" style="text-align: center;">원료 데이터를 불러오는 중...</td></tr>
                        </tbody>
                    </table>

                    <div class="pagination" id="bomPaginationContainer"></div>
                </div>
            </div>
        </main>

        <!-- 개별 품목 BOM 등록/수정 팝업 모달 -->
        <div id="bomModal" class="modal-overlay">
            <div class="modal-content" style="width: 850px;">
                <div class="modal-header">
                    <span id="modalBomTitle">품목 BOM 관리</span>
                    <span class="modal-close" onclick="closeBomModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="bom_target_code">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <p style="font-size: 13px; color: #475569;">선택한 품목의 구성 원료 및 투입량을 입력하거나 수정하세요.</p>
                        <button type="button" class="btn-action" onclick="addBomItemRow()" style="padding: 6px 12px;">+ 원료 행 추가</button>
                    </div>
                    <div style="max-height: 350px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>원료코드</th>
                                    <th>원료명</th>
                                    <th>투입수량</th>
                                    <th>단위</th>
                                    <th>CAS No</th>
                                    <th>관리</th>
                                </tr>
                            </thead>
                            <tbody id="modalBomItemsTableBody">
                                <!-- 동적 행 삽입 -->
                            </tbody>
                        </table>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn-order" onclick="saveBomData()" style="padding: 8px 16px;">BOM 저장</button>
                    <button type="button" class="btn-delete" onclick="closeBomModal()" style="padding: 8px 16px; background:#64748b;">닫기</button>
                </div>
            </div>
        </div>

        <!-- 신규 원료 등록 팝업 모달 -->
        <div id="createModal" class="modal-overlay">
            <div class="modal-content">
                <div class="modal-header">
                    <span>신규 원료 등록</span>
                    <span class="modal-close" onclick="closeCreateModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <div class="form-group"><label>원료코드 *</label><input type="text" id="new_code" placeholder="예: 1-999 또는 AR-001"></div>
                    <div class="form-group"><label>원료명(국문) *</label><input type="text" id="new_name_kr" placeholder="국문 원료명 입력"></div>
                    <div class="form-group"><label>원료명(영문)</label><input type="text" id="new_name_en" placeholder="영문 원료명 입력"></div>
                    <div class="form-group"><label>CAS No.</label><input type="text" id="new_cas" placeholder="예: 0000-00-0"></div>
                    <div class="form-group"><label>공급사</label><input type="text" id="new_supplier" placeholder="공급사 입력"></div>
                    <div class="form-group">
                        <label>원료 구분</label>
                        <select id="new_category">
                            <option value="원재료">원재료</option>
                            <option value="제품">제품</option>
                            <option value="반제품">반제품</option>
                            <option value="상품">상품</option>
                        </select>
                    </div>
                    <div class="form-group"><label>적요 / 비고</label><input type="text" id="new_remark" placeholder="비고 및 담당자 멘트 입력"></div>
                </div>
                <div class="modal-footer">
                    <button class="btn-action" onclick="saveNewMaterial()" style="background:#0077FF; padding: 8px 16px;">등록 저장</button>
                    <button class="btn-delete" onclick="closeCreateModal()" style="padding: 8px 16px; background:#64748b;">닫기</button>
                </div>
            </div>
        </div>

        <!-- 원료 수정 팝업 모달 -->
        <div id="editModal" class="modal-overlay">
            <div class="modal-content">
                <div class="modal-header">
                    <span>품목 상세 정보 및 수정</span>
                    <span class="modal-close" onclick="closeEditModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="edit_id">
                    <div class="form-group"><label>원료코드</label><input type="text" id="edit_code"></div>
                    <div class="form-group"><label>원료명(국문)</label><input type="text" id="edit_name_kr"></div>
                    <div class="form-group"><label>원료명(영문)</label><input type="text" id="edit_name_en"></div>
                    <div class="form-group"><label>CAS No.</label><input type="text" id="edit_cas"></div>
                    <div class="form-group"><label>공급사</label><input type="text" id="edit_supplier"></div>
                    <div class="form-group">
                        <label>원료 구분</label>
                        <select id="edit_category">
                            <option value="원재료">원재료</option>
                            <option value="제품">제품</option>
                            <option value="반제품">반제품</option>
                            <option value="상품">상품</option>
                        </select>
                    </div>
                    <div class="form-group"><label>적요 / 비고</label><input type="text" id="edit_remark" placeholder="비고 및 담당자 멘트 입력"></div>
                </div>
                <div class="modal-footer">
                    <button class="btn-action" onclick="saveModalEdit()" style="background:#0077FF; padding: 8px 16px;">수정 저장</button>
                    <button class="btn-delete" onclick="closeEditModal()" style="padding: 8px 16px; background:#64748b;">닫기</button>
                </div>
            </div>
        </div>

        <script>
            let currentPage = 1;
            let bomCurrentPage = 1;
            const pageSize = 30;
            let currentSearch = '';
            let currentBomSearch = '';

            function switchTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
                if (tabId === 'materials-tab') {
                    loadMaterials(1);
                } else if (tabId === 'bom-tab') {
                    loadBomMaterials(1);
                }
            }

            function toggleSelectAll(source) {
                const checkboxes = document.querySelectorAll('.row-checkbox');
                checkboxes.forEach(cb => cb.checked = source.checked);
            }

            function deleteSelectedMaterials() {
                const selectedIds = Array.from(document.querySelectorAll('.row-checkbox:checked'))
                                         .map(cb => parseInt(cb.value));
                if (selectedIds.length === 0) {
                    alert("삭제할 항목을 체크박스로 하나 이상 선택해 주세요.");
                    return;
                }
                if (!confirm(`선택한 ${selectedIds.length}개의 원료 데이터를 정말 삭제하시겠습니까?`)) return;

                fetch('/api/v1/materials/delete-batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids: selectedIds })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert(data.message);
                        loadMaterials(currentPage);
                    } else {
                        alert("삭제 실패");
                    }
                });
            }

            function loadMaterials(page) {
                currentPage = page;
                const skip = (page - 1) * pageSize;
                let url = `/api/v1/materials?skip=${skip}&limit=${pageSize}`;
                if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;

                fetch(url)
                .then(res => res.json())
                .then(data => {
                    const tbody = document.getElementById('materialTableBody');
                    tbody.innerHTML = '';
                    document.getElementById('selectAll').checked = false;
                    if (!data.data || data.data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center;">등록된 원료 데이터가 없습니다.</td></tr>';
                        document.getElementById('paginationContainer').innerHTML = '';
                        return;
                    }

                    data.data.forEach((row, index) => {
                        const rowNum = skip + index + 1;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><input type="checkbox" class="row-checkbox" value="${row.id}"></td>
                            <td>${rowNum}</td>
                            <td><span class="clickable-no" onclick='openEditModal(${JSON.stringify(row)})'>${row.material_code || ''}</span></td>
                            <td><span class="clickable-no" onclick='openEditModal(${JSON.stringify(row)})'>${row.material_name_kr || ''}</span></td>
                            <td>${row.material_name_en || ''}</td>
                            <td>${row.cas_no || ''}</td>
                            <td>${row.supplier || ''}</td>
                            <td><span class="badge" style="background:#475569;">${row.category || '원재료'}</span></td>
                            <td>${row.remark || ''}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                    renderPagination(data.total, 'paginationContainer', loadMaterials, currentPage);
                });
            }

            function loadBomMaterials(page) {
                bomCurrentPage = page;
                const skip = (page - 1) * pageSize;
                let url = `/api/v1/materials?skip=${skip}&limit=${pageSize}`;
                if (currentBomSearch) url += `&search=${encodeURIComponent(currentBomSearch)}`;

                fetch(url)
                .then(res => res.json())
                .then(data => {
                    const tbody = document.getElementById('bomMaterialTableBody');
                    tbody.innerHTML = '';
                    if (!data.data || data.data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center;">등록된 품목이 없습니다.</td></tr>';
                        document.getElementById('bomPaginationContainer').innerHTML = '';
                        return;
                    }

                    data.data.forEach((row, index) => {
                        const rowNum = skip + index + 1;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${rowNum}</td>
                            <td><span class="clickable-no" onclick="openBomModal('${row.material_code}', '${row.material_name_kr}')">${row.material_code || ''}</span></td>
                            <td><span class="clickable-no" onclick="openBomModal('${row.material_code}', '${row.material_name_kr}')">${row.material_name_kr || ''}</span></td>
                            <td>${row.material_name_en || ''}</td>
                            <td>${row.cas_no || ''}</td>
                            <td>${row.supplier || ''}</td>
                            <td><span class="badge" style="background:#475569;">${row.category || '원재료'}</span></td>
                            <td>${row.remark || ''}</td>
                            <td>
                                <button class="btn-action" onclick="openBomModal('${row.material_code}', '${row.material_name_kr}')" style="background:#0077FF;">BOM 등록/수정</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                    renderPagination(data.total, 'bomPaginationContainer', loadBomMaterials, bomCurrentPage);
                });
            }

            function renderPagination(totalItems, containerId, callback, pageNo) {
                const totalPages = Math.ceil(totalItems / pageSize);
                const container = document.getElementById(containerId);
                container.innerHTML = '';
                if (totalPages <= 1) return;

                const prevBtn = document.createElement('button');
                prevBtn.innerText = '◀ 이전';
                prevBtn.disabled = pageNo === 1;
                prevBtn.onclick = () => callback(pageNo - 1);
                container.appendChild(prevBtn);

                let startPage = Math.max(1, pageNo - 2);
                let endPage = Math.min(totalPages, startPage + 4);
                for (let i = startPage; i <= endPage; i++) {
                    const pageBtn = document.createElement('button');
                    pageBtn.innerText = i;
                    if (i === pageNo) pageBtn.classList.add('active');
                    pageBtn.onclick = () => callback(i);
                    container.appendChild(pageBtn);
                }

                const nextBtn = document.createElement('button');
                nextBtn.innerText = '다음 ▶';
                nextBtn.disabled = pageNo === totalPages;
                nextBtn.onclick = () => callback(pageNo + 1);
                container.appendChild(nextBtn);
            }

            function openBomModal(productCode, productName) {
                document.getElementById('modalBomTitle').innerText = `품목 [${productCode}] ${productName} - BOM 등록 및 관리`;
                document.getElementById('bom_target_code').value = productCode;
                document.getElementById('modalBomItemsTableBody').innerHTML = '<tr><td colspan="6" style="text-align: center;">불러오는 중...</td></tr>';
                document.getElementById('bomModal').style.display = 'flex';

                fetch(`/api/v1/boms?product_code=${encodeURIComponent(productCode)}&version=1`)
                .then(res => res.json())
                .then(data => {
                    const tbody = document.getElementById('modalBomItemsTableBody');
                    tbody.innerHTML = '';
                    const items = data.items || [];
                    if (items.length === 0) {
                        addBomItemRow();
                    } else {
                        items.forEach(item => {
                            addBomItemRow(item.material_code, item.material_name, item.qty, item.unit, item.cas_no);
                        });
                    }
                });
            }

            function closeBomModal() {
                document.getElementById('bomModal').style.display = 'none';
            }

            function addBomItemRow(code='', name='', qty='', unit='KG', cas='') {
                const tbody = document.getElementById('modalBomItemsTableBody');
                const tr = document.createElement('tr');
                tr.className = 'bom-item-row';
                tr.innerHTML = `
                    <td><input type="text" class="b-code" value="${code}" placeholder="원료코드" style="padding:4px; width:100%;"></td>
                    <td><input type="text" class="b-name" value="${name}" placeholder="원료명" style="padding:4px; width:100%;"></td>
                    <td><input type="number" step="0.001" class="b-qty" value="${qty}" placeholder="수량" style="padding:4px; width:100%;"></td>
                    <td><input type="text" class="b-unit" value="${unit}" style="padding:4px; width:100%;"></td>
                    <td><input type="text" class="b-cas" value="${cas}" placeholder="CAS No" style="padding:4px; width:100%;"></td>
                    <td><button type="button" class="btn-delete" onclick="this.closest('tr').remove()" style="padding:4px 8px;">삭제</button></td>
                `;
                tbody.appendChild(tr);
            }

            function saveBomData() {
                const productCode = document.getElementById('bom_target_code').value;
                const rows = document.querySelectorAll('.bom-item-row');
                const items = [];
                rows.forEach(row => {
                    const code = row.querySelector('.b-code').value.trim();
                    const name = row.querySelector('.b-name').value.trim();
                    const qty = parseFloat(row.querySelector('.b-qty').value) || 0;
                    const unit = row.querySelector('.b-unit').value.trim() || 'KG';
                    const cas = row.querySelector('.b-cas').value.trim();
                    if (code) {
                        items.push({ material_code: code, material_name: name, qty: qty, unit: unit, cas_no: cas, location: '' });
                    }
                });

                const payload = {
                    product_code: productCode,
                    product_name: productCode,
                    bom_version: "1",
                    items: items
                };

                fetch('/api/v1/boms/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("BOM이 성공적으로 저장되었습니다.");
                        closeBomModal();
                    } else {
                        alert("저장 실패");
                    }
                });
            }

            function searchMaterials() {
                currentSearch = document.getElementById('searchInput').value.trim();
                loadMaterials(1);
            }

            function resetSearch() {
                document.getElementById('searchInput').value = '';
                currentSearch = '';
                loadMaterials(1);
            }

            function searchBomMaterials() {
                currentBomSearch = document.getElementById('bomSearchInput').value.trim();
                loadBomMaterials(1);
            }

            function resetBomSearch() {
                document.getElementById('bomSearchInput').value = '';
                currentBomSearch = '';
                loadBomMaterials(1);
            }

            function openCreateModal() {
                document.getElementById('new_code').value = '';
                document.getElementById('new_name_kr').value = '';
                document.getElementById('new_name_en').value = '';
                document.getElementById('new_cas').value = '';
                document.getElementById('new_supplier').value = '';
                document.getElementById('new_category').value = '원재료';
                document.getElementById('new_remark').value = '';
                document.getElementById('createModal').style.display = 'flex';
            }

            function closeCreateModal() {
                document.getElementById('createModal').style.display = 'none';
            }

            function saveNewMaterial() {
                const code = document.getElementById('new_code').value.trim();
                let category = document.getElementById('new_category').value;
                if (code.startsWith("AR-")) category = "제품";
                else if (code.startsWith("1-") || code.startsWith("2-") || code.startsWith("3-")) category = "원재료";
                else if (code.startsWith("CB-")) category = "반제품";

                const payload = {
                    material_code: code,
                    material_name_kr: document.getElementById('new_name_kr').value.trim(),
                    material_name_en: document.getElementById('new_name_en').value.trim(),
                    cas_no: document.getElementById('new_cas').value.trim(),
                    supplier: document.getElementById('new_supplier').value.trim(),
                    category: category,
                    unit: 'Kg',
                    remark: document.getElementById('new_remark').value.trim()
                };
                fetch('/api/v1/materials', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("신규 원료가 등록되었습니다.");
                        closeCreateModal();
                        loadMaterials(1);
                    } else {
                        alert("등록 실패: " + (data.detail || "중복된 코드일 수 있습니다."));
                    }
                });
            }

            function openEditModal(row) {
                document.getElementById('edit_id').value = row.id;
                document.getElementById('edit_code').value = row.material_code || '';
                document.getElementById('edit_name_kr').value = row.material_name_kr || '';
                document.getElementById('edit_name_en').value = row.material_name_en || '';
                document.getElementById('edit_cas').value = row.cas_no || '';
                document.getElementById('edit_supplier').value = row.supplier || '';
                document.getElementById('edit_category').value = row.category || '원재료';
                document.getElementById('edit_remark').value = row.remark || '';
                document.getElementById('editModal').style.display = 'flex';
            }

            function closeEditModal() {
                document.getElementById('editModal').style.display = 'none';
            }

            function saveModalEdit() {
                const id = document.getElementById('edit_id').value;
                const code = document.getElementById('edit_code').value.trim();
                let category = document.getElementById('edit_category').value;
                if (code.startsWith("AR-")) category = "제품";
                else if (code.startsWith("1-") || code.startsWith("2-") || code.startsWith("3-")) category = "원재료";
                else if (code.startsWith("CB-")) category = "반제품";

                const payload = {
                    material_code: code,
                    material_name_kr: document.getElementById('edit_name_kr').value,
                    material_name_en: document.getElementById('edit_name_en').value,
                    cas_no: document.getElementById('edit_cas').value,
                    supplier: document.getElementById('edit_supplier').value,
                    category: category,
                    unit: 'Kg',
                    remark: document.getElementById('edit_remark').value.trim()
                };
                fetch(`/api/v1/materials/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("수정되었습니다.");
                        closeEditModal();
                        loadMaterials(currentPage);
                    }
                });
            }

            function loadOrders() {
                fetch('/api/v1/orders').then(res => res.json()).then(data => {
                    const tbody = document.getElementById('orderTableBody');
                    tbody.innerHTML = '';
                    if (!data.data || data.data.length === 0) return;
                    data.data.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><span class="clickable-no" onclick='prepareEdit(${JSON.stringify(row)})'>${row.order_no}</span></td>
                            <td>${row.client_name}</td><td>${row.manager_id}</td><td>${row.product_summary}</td>
                            <td>${row.order_qty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</td>
                            <td>${row.order_amount.toLocaleString()} 원</td><td>${row.due_date}</td><td>${row.remark}</td>
                            <td><span class="badge badge-progress">${row.status}</span></td>
                            <td><button class="btn-action" onclick="createWorkOrder(${row.order_id})">지시발행</button></td>
                            <td><button class="btn-delete" onclick="deleteOrder(${row.order_id})">삭제</button></td>
                        `;
                        tbody.appendChild(tr);
                    });
                });
            }

            function loadWorkOrders() {
                fetch('/api/v1/work-orders').then(res => res.json()).then(data => {
                    const tbody = document.getElementById('workOrderTableBody');
                    tbody.innerHTML = '';
                    if (!data.data || data.data.length === 0) return;
                    data.data.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><strong>WO-${row.work_order_id}</strong></td><td>${row.order_no}</td><td>${row.client_name}</td>
                            <td>${row.product_summary}</td><td>${row.target_qty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</td>
                            <td><span class="badge badge-success">${row.status}</span></td>
                            <td><button class="btn-delete" onclick="deleteWorkOrder(${row.work_order_id})">취소</button></td>
                        `;
                        tbody.appendChild(tr);
                    });
                });
            }

            function loadLogs() {
                fetch('/api/v1/production/batches').then(res => res.json()).then(data => {
                    const tbody = document.getElementById('logTableBody');
                    tbody.innerHTML = '';
                    if (!data.data || data.data.length === 0) return;
                    data.data.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `<td>${row.log_id}</td><td><strong>${row.batch_id}</strong></td><td>${row.manifold_id}</td><td>${row.input_qty.toFixed(3)} kg</td><td>${row.operator_id}</td><td><span class="badge badge-success">${row.status}</span></td>`;
                        tbody.appendChild(tr);
                    });
                });
            }

            loadOrders(); loadWorkOrders(); loadLogs();
        </script>
    </body>
    </html>
    """

# --- BOM 및 원료 마스터 API 엔드포인트 ---

@app.get("/api/v1/boms")
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

@app.post("/api/v1/boms/save")
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
                cat = "원재료"
                if m_code.startswith("AR-"): cat = "제품"
                elif m_code.startswith("1-") or m_code.startswith("2-") or m_code.startswith("3-"): cat = "원재료"
                elif m_code.startswith("CB-"): cat = "반제품"

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

@app.get("/api/v1/materials")
def get_materials(skip: int = 0, limit: int = 30, search: str = None):
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
        total = query.count()
        materials = query.offset(skip).limit(limit).all()
        db.close()
        
        data = [{
            "id": m.id,
            "material_code": m.material_code,
            "material_name_kr": m.material_name_kr,
            "material_name_en": m.material_name_en,
            "cas_no": m.cas_no,
            "supplier": m.supplier,
            "category": m.category or "원재료",
            "remark": m.remark or "",
            "unit": m.unit
        } for m in materials]
        return {"status": "SUCCESS", "total": total, "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/materials")
def create_material(data: MaterialRequest):
    try:
        db = SessionLocal()
        existing = db.query(MaterialMaster).filter(MaterialMaster.material_code == data.material_code).first()
        if existing:
            db.close()
            raise HTTPException(status_code=400, detail="이미 존재하는 원료코드입니다.")
        
        cat = data.category
        if data.material_code.startswith("AR-"): cat = "제품"
        elif data.material_code.startswith("1-") or data.material_code.startswith("2-") or data.material_code.startswith("3-"): cat = "원재료"
        elif data.material_code.startswith("CB-"): cat = "반제품"

        new_m = MaterialMaster(
            material_code=data.material_code,
            material_name_kr=data.material_name_kr,
            material_name_en=data.material_name_en,
            cas_no=data.cas_no,
            supplier=data.supplier,
            category=cat,
            unit=data.unit,
            remark=data.remark
        )
        db.add(new_m)
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "신규 원료가 등록되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/materials/delete-batch")
def delete_batch_materials(data: BatchDeleteRequest):
    try:
        db = SessionLocal()
        db.query(MaterialMaster).filter(MaterialMaster.id.in_(data.ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": f"선택한 {len(data.ids)}건의 원료가 삭제되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/materials/{material_id}")
def update_material(material_id: int, data: MaterialRequest):
    try:
        db = SessionLocal()
        m = db.query(MaterialMaster).filter(MaterialMaster.id == material_id).first()
        if not m:
            db.close()
            raise HTTPException(status_code=404, detail="원료를 찾을 수 없습니다.")
        
        cat = data.category
        if data.material_code.startswith("AR-"): cat = "제품"
        elif data.material_code.startswith("1-") or data.material_code.startswith("2-") or data.material_code.startswith("3-"): cat = "원재료"
        elif data.material_code.startswith("CB-"): cat = "반제품"

        m.material_code = data.material_code
        m.material_name_kr = data.material_name_kr
        m.material_name_en = data.material_name_en
        m.cas_no = data.cas_no
        m.supplier = data.supplier
        m.category = cat
        m.unit = data.unit
        m.remark = data.remark
        db.commit()
        db.close()
        return {"status": "SUCCESS", "message": "수정되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/materials/{material_id}")
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

@app.post("/api/v1/work-orders")
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
