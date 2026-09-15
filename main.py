import sqlite3
import glob
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os
import shutil
from datetime import datetime
from database import engine, Base, SessionLocal, MaterialMaster
from routers import materials, orders, boms

Base.metadata.create_all(bind=engine)
app = FastAPI()

# 라우터 등록
app.include_router(materials.router)
app.include_router(orders.router)
app.include_router(boms.router)

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
def backup_database():
    """서버 구동 시 erp_factory.db 파일을 안전하게 백업합니다."""
    db_file = "erp_factory.db"
    backup_dir = "backups"
    
    if os.path.exists(db_file):
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"erp_factory_{timestamp}.db")
        
        try:
            shutil.copy(db_file, backup_file)
            print(f"[Backup Success] 데이터베이스 백업 완료: {backup_file}")
            
            backups = sorted(os.listdir(backup_dir))
            if len(backups) > 10:
                os.remove(os.path.join(backup_dir, backups[0]))
        except Exception as e:
            print(f"[Backup Error] 백업 실패: {e}")
def init_db():
    backup_database()
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
    
    for col_def in [
        ("remark", "TEXT"),
        ("pre_weighing", "REAL DEFAULT 0"),
        ("stock_qty", "REAL DEFAULT 0"),
        ("sales_qty", "REAL DEFAULT 0"),
        ("yearly_pre_weighing", "TEXT DEFAULT '{}'"),
        ("lot_stock", "TEXT DEFAULT '[]'")
    ]:
        try:
            cursor.execute(f"ALTER TABLE material_masters ADD COLUMN {col_def[0]} {col_def[1]};")
            conn.commit()
        except Exception:
            pass

    cursor.execute("UPDATE material_masters SET category = 'KT&G상품' WHERE material_code LIKE '1000%' AND material_code != '1000052941'")
    conn.commit()
    conn.close()
    
    auto_seed_materials()
    bulk_update_categories()

def auto_seed_materials():
    db = SessionLocal()
    excel_files = glob.glob("*.xlsx")
    for file_path in excel_files:
        try:
            xls = pd.ExcelFile(file_path)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                sheet_cat_override = None
                if "KT&G" in sheet_name or "케이티앤지" in sheet_name:
                    sheet_cat_override = "KT&G상품"

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

                    cat = sheet_cat_override if sheet_cat_override else get_auto_category(material_code)

                    existing = db.query(MaterialMaster).filter(MaterialMaster.material_code == material_code).first()
                    if not existing:
                        new_material = MaterialMaster(
                            material_code=material_code,
                            material_name_kr=name_kr,
                            material_name_en=name_en,
                            cas_no=cas_no,
                            supplier=supplier,
                            unit="Kg",
                            category=cat,
                            remark="",
                            pre_weighing=0.0,
                            stock_qty=0.0,
                            sales_qty=0.0,
                            yearly_pre_weighing="{}",
                            lot_stock="[]"
                        )
                        db.add(new_material)
                    else:
                        if name_kr: existing.material_name_kr = name_kr
                        if name_en: existing.material_name_en = name_en
                        if cas_no: existing.cas_no = cas_no
                        if supplier: existing.supplier = supplier
                        if sheet_cat_override: existing.category = sheet_cat_override
            db.commit()
        except Exception as e:
            print(f"[Auto-Seed Error for {file_path}] {e}")
    db.close()

def bulk_update_categories():
    db = SessionLocal()
    try:
        materials = db.query(MaterialMaster).all()
        for m in materials:
            code = str(m.material_code).strip()
            if m.category == "상품" or m.category == "KT&G상품":
                continue
            new_cat = get_auto_category(code)
            if m.category != new_cat:
                m.category = new_cat
        db.commit()
    except Exception as e:
        print(f"[Bulk Update Error] {e}")
    finally:
        db.close()

init_db()

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

            .search-bar { display: flex; gap: 10px; margin-bottom: 15px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
            .search-left { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
            .search-bar input { padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; width: 220px; font-size: 13px; }
            .filter-btn { padding: 8px 12px; border: 1px solid #cbd5e1; background: white; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; color: #475569; }
            .filter-btn.active { background: #0077FF; color: white; border-color: #0077FF; }
            
            .pagination { display: flex; justify-content: center; gap: 5px; margin-top: 20px; align-items: center; }
            .pagination button { padding: 6px 12px; border: 1px solid #cbd5e1; background: white; border-radius: 4px; cursor: pointer; font-size: 13px; }
            .pagination button.active { background: #0077FF; color: white; border-color: #0077FF; }
            .pagination button:disabled { background: #f1f5f9; color: #94a3b8; cursor: not-allowed; }

            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); justify-content: center; align-items: center; z-index: 1000; }
            .modal-content { background: white; padding: 25px; border-radius: 10px; width: 550px; max-height: 90vh; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
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
            <details open>
              <summary>입고 / 구매</summary>
              <ul>
                <li><a onclick="switchTab('ktng-tab')">KT&G 상품 품목리스트</a></li>
              </ul>
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
                    <form id="logForm" onsubmit="submitLog(event)">
        <div class="form-grid">
            <div class="form-group"><label>배치 번호</label><input type="text" id="batch_id" value="BATCH-2026-09" required></div>
            <div class="form-group"><label>매니폴드 ID</label><input type="text" id="manifold_id" value="MF-01" required></div>
            <div class="form-group"><label>투입 중량 (kg)</label><input type="number" step="0.001" id="input_qty" value="15.250" required></div>
            <div class="form-group"><label>작업자 ID</label><input type="text" id="operator_id" value="JEON" required></div>
            <div class="form-group"><label>생산 품목코드 (BOM 연동)</label><input type="text" id="log_product_code" value="1000052941" required></div>
        </div>
        <div class="btn-group">
            <button type="submit" class="btn-submit">생산 데이터 전송 및 재고 차감</button>
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
                    <p>아로마리소스 향료 원료 품목 리스트 조회, 검색, 수정 및 신규 등록 관리 (구분: 원재료/제품/반제품/상품/KT&G상품 등)</p>
                </div>

                <div class="card">
                    <h2>품목등록 리스트 (데이터베이스 연동)</h2>
                    
                    <div class="search-bar" style="margin-top: 15px;">
                        <div class="search-left">
                            <input type="text" id="searchInput" placeholder="원료코드, 원료명, CAS No, 공급사 검색..." onkeyup="if(event.key==='Enter') searchMaterials()">
                            <button type="button" class="btn-action" onclick="searchMaterials()" style="padding: 8px 14px;">검색</button>
                            <button type="button" class="btn-delete" onclick="resetSearch()" style="padding: 8px 14px; background:#64748b;">초기화</button>
                            <!-- 카테고리 필터 버튼 그룹 -->
                            <button type="button" class="filter-btn active" id="btn-cat-all" onclick="filterByCategory('')">전체</button>
                            <button type="button" class="filter-btn" id="btn-cat-원재료" onclick="filterByCategory('원재료')">원재료</button>
                            <button type="button" class="filter-btn" id="btn-cat-제품" onclick="filterByCategory('제품')">제품</button>
                            <button type="button" class="filter-btn" id="btn-cat-반제품" onclick="filterByCategory('반제품')">반제품</button>
                            <button type="button" class="filter-btn" id="btn-cat-상품" onclick="filterByCategory('상품')">상품</button>
                            <button type="button" class="filter-btn" id="btn-cat-KT&G상품" onclick="filterByCategory('KT&G상품')">KT&G상품</button>
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
                                <th>제조사</th>
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

            <!-- [탭 3] KT&G 상품 품목리스트 탭 -->
            <div id="ktng-tab" class="tab-content">
                <div class="card">
                    <h1>KT&G 상품 품목리스트</h1>
                    <p>원료 마스터 중 <b>'KT&G상품'</b>으로 분류된 품목 리스트입니다. 수치(예계량, 재고수량)를 클릭하여 연도별 또는 LOT별 상세 내역을 관리하세요.</p>
                </div>

                <div class="card">
                    <h2>KT&G 연동 품목 리스트</h2>
                    
                    <div class="search-bar" style="margin-top: 15px;">
                        <div class="search-left">
                            <input type="text" id="ktngSearchInput" placeholder="품목코드 또는 품목명 검색..." onkeyup="if(event.key==='Enter') searchKtngMaterials()">
                            <button type="button" class="btn-action" onclick="searchKtngMaterials()" style="padding: 8px 14px;">검색</button>
                            <button type="button" class="btn-delete" onclick="resetKtngSearch()" style="padding: 8px 14px; background:#64748b;">초기화</button>
                        </div>
                        <button type="button" class="btn-order" onclick="openCreateModalForKtng()">KT&G 상품 신규 등록</button>
                    </div>

                    <table>
                        <thead>
                            <tr>
                                <th style="width: 60px;">순번</th>
                                <th>원료코드</th>
                                <th>원료명(국문)</th>
                                <th>제조사</th>
                                <th>예계량 (kg)</th>
                                <th>재고수량 (kg)</th>
                                <th>판매수량 (kg)</th>
                                <th>관리</th>
                            </tr>
                        </thead>
                        <tbody id="ktngMaterialTableBody">
                            <tr><td colspan="8" style="text-align: center;">데이터를 불러오는 중...</td></tr>
                        </tbody>
                    </table>

                    <div class="pagination" id="ktngPaginationContainer"></div>
                </div>
            </div>

            <!-- [탭 4] BOM 조회 및 관리 탭 -->
            <div id="bom-tab" class="tab-content">
                <div class="card">
                    <h1>BOM(소요량) 조회 및 관리</h1>
                    <p>품목코드를 체크하여 삭제하거나 신규 품목을 등록할 수 있습니다.</p>
                </div>

                <div class="card">
                    <h2>BOM 대상 품목 리스트</h2>
                    
                    <div class="search-bar" style="margin-top: 15px;">
                        <div class="search-left">
                            <input type="text" id="bomSearchInput" placeholder="품목코드 또는 품목명 검색..." onkeyup="if(event.key==='Enter') searchBomMaterials()">
                            <button type="button" class="btn-action" onclick="searchBomMaterials()" style="padding: 8px 14px;">검색</button>
                            <button type="button" class="btn-delete" onclick="resetBomSearch()" style="padding: 8px 14px; background:#64748b;">초기화</button>
                        </div>
                        <div style="display: flex; gap: 10px;">
                            <button type="button" class="btn-delete" onclick="deleteSelectedBomMaterials()">선택 삭제</button>
                            <button type="button" class="btn-order" onclick="openCreateModal()">신규 등록</button>
                        </div>
                    </div>

                    <table>
                        <thead>
                            <tr>
                                <th style="width: 40px;"><input type="checkbox" id="bomSelectAll" onclick="toggleBomSelectAll(this)"></th>
                                <th style="width: 60px;">순번</th>
                                <th>품목코드</th>
                                <th>원료명(국문)</th>
                                <th>제조사</th>
                                <th>CAS No.</th>
                                <th>공급사</th>
                                <th>원료구분</th>
                                <th>적요/비고</th>
                                <th>관리</th>
                            </tr>
                        </thead>
                        <tbody id="bomMaterialTableBody">
                            <tr><td colspan="10" style="text-align: center;">원료 데이터를 불러오는 중...</td></tr>
                        </tbody>
                    </table>

                    <div class="pagination" id="bomPaginationContainer"></div>
                </div>
            </div>
        </main>

        <!-- 연도별 예계량 상세 관리 모달 -->
        <div id="yearlyPreModal" class="modal-overlay">
            <div class="modal-content">
                <div class="modal-header">
                    <span id="yearlyPreModalTitle">연도별 예계량 관리</span>
                    <span class="modal-close" onclick="closeYearlyPreModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="yearly_target_id">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <p style="font-size: 13px; color: #475569;">연도별 예계량 수량을 기입하고 저장하세요.</p>
                        <button type="button" class="btn-action" onclick="addYearlyRow()" style="padding: 5px 10px;">+ 연도 추가</button>
                    </div>
                    <div style="max-height: 250px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr><th>연도 선택</th><th>예계량 (kg)</th><th>관리</th></tr>
                            </thead>
                            <tbody id="yearlyRowsBody"></tbody>
                        </table>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn-order" onclick="saveYearlyPreData()">저장</button>
                    <button type="button" class="btn-delete" onclick="closeYearlyPreModal()" style="background:#64748b;">닫기</button>
                </div>
            </div>
        </div>

        <!-- LOT별 재고수량 상세 관리 모달 -->
        <div id="lotStockModal" class="modal-overlay">
            <div class="modal-content">
                <div class="modal-header">
                    <span id="lotStockModalTitle">LOT별 재고수량 관리</span>
                    <span class="modal-close" onclick="closeLotStockModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="lot_target_id">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <p style="font-size: 13px; color: #475569;">LOT 번호별 재고 수량을 기입하고 저장하세요.</p>
                        <button type="button" class="btn-action" onclick="addLotRow()" style="padding: 5px 10px;">+ LOT 추가</button>
                    </div>
                    <div style="max-height: 250px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr><th>LOT 번호</th><th>재고수량 (kg)</th><th>관리</th></tr>
                            </thead>
                            <tbody id="lotRowsBody"></tbody>
                        </table>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn-order" onclick="saveLotStockData()">저장</button>
                    <button type="button" class="btn-delete" onclick="closeLotStockModal()" style="background:#64748b;">닫기</button>
                </div>
            </div>
        </div>

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

        <!-- 간소화된 신규 원료 등록 팝업 모달 (제품코드, 제품명, 구분, 적요) -->
        <div id="createModal" class="modal-overlay">
            <div class="modal-content">
                <div class="modal-header">
                    <span>신규 원료 등록</span>
                    <span class="modal-close" onclick="closeCreateModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>제품코드 *</label>
                        <input type="text" id="new_code" placeholder="예: 1-999 또는 AR-001" oninput="onMaterialCodeInput(this.value)">
                    </div>
                    <div class="form-group">
                        <label>제품명 *</label>
                        <input type="text" id="new_name_kr" placeholder="국문 제품명 입력">
                        <div id="duplicateNameSuggestions" style="margin-top: 5px; display: none;">
                            <select id="suggestedNamesSelect" style="width:100%; padding:6px; border:1px solid #0077FF; border-radius:4px; background:#eff6ff;" onchange="selectSuggestedName(this.value)">
                                <option value="">-- 일치하거나 유사한 제품명 선택 --</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>원료 구분</label>
                        <select id="new_category">
                            <option value="원재료">원재료</option>
                            <option value="제품">제품</option>
                            <option value="반제품">반제품</option>
                            <option value="상품">상품</option>
                            <option value="KT&G상품">KT&G상품</option>
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
                    <div class="form-group"><label>제품코드</label><input type="text" id="edit_code"></div>
                    <div class="form-group"><label>제품명</label><input type="text" id="edit_name_kr"></div>
                    <div class="form-group"><label>제조사</label><input type="text" id="edit_name_en"></div>
                    <div class="form-group"><label>CAS No.</label><input type="text" id="edit_cas"></div>
                    <div class="form-group"><label>공급사</label><input type="text" id="edit_supplier"></div>
                    <div class="form-group">
                        <label>원료 구분</label>
                        <select id="edit_category">
                            <option value="원재료">원재료</option>
                            <option value="제품">제품</option>
                            <option value="반제품">반제품</option>
                            <option value="상품">상품</option>
                            <option value="KT&G상품">KT&G상품</option>
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
            let ktngCurrentPage = 1;
            let bomCurrentPage = 1;
            const pageSize = 30;
            let currentSearch = '';
            let currentKtngSearch = '';
            let currentCategory = '';
            let currentBomSearch = '';

            let currentMaterialMap = {};

            function switchTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
                if (tabId === 'materials-tab') {
                    loadMaterials(1);
                } else if (tabId === 'ktng-tab') {
                    loadKtngMaterials(1);
                } else if (tabId === 'bom-tab') {
                    loadBomMaterials(1);
                }
            }

            function filterByCategory(cat) {
                currentCategory = cat;
                document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                const btnId = cat === '' ? 'btn-cat-all' : `btn-cat-${cat}`;
                const targetBtn = document.getElementById(btnId);
                if (targetBtn) targetBtn.classList.add('active');
                loadMaterials(1);
            }

            function toggleSelectAll(source) {
                const checkboxes = document.querySelectorAll('.row-checkbox');
                checkboxes.forEach(cb => cb.checked = source.checked);
            }

            function toggleBomSelectAll(source) {
                const checkboxes = document.querySelectorAll('.bom-row-checkbox');
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
                        loadKtngMaterials(ktngCurrentPage);
                        loadBomMaterials(bomCurrentPage);
                    } else {
                        alert("삭제 실패");
                    }
                });
            }

            function deleteSelectedBomMaterials() {
                const selectedIds = Array.from(document.querySelectorAll('.bom-row-checkbox:checked'))
                                         .map(cb => parseInt(cb.value));
                if (selectedIds.length === 0) {
                    alert("삭제할 항목을 체크박스로 하나 이상 선택해 주세요.");
                    return;
                }
                if (!confirm(`선택한 ${selectedIds.length}개의 품목 데이터를 정말 삭제하시겠습니까?`)) return;

                fetch('/api/v1/materials/delete-batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids: selectedIds })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert(data.message);
                        loadBomMaterials(bomCurrentPage);
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
                if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;

                fetch(url)
                .then(res => res.json())
                .then(data => {
                    const tbody = document.getElementById('materialTableBody');
                    tbody.innerHTML = '';
                    const selectAllCb = document.getElementById('selectAll');
                    if (selectAllCb) selectAllCb.checked = false;

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

            function loadKtngMaterials(page) {
                ktngCurrentPage = page;
                const skip = (page - 1) * pageSize;
                let url = `/api/v1/materials?skip=${skip}&limit=${pageSize}&category=${encodeURIComponent('KT&G상품')}`;
                if (currentKtngSearch) url += `&search=${encodeURIComponent(currentKtngSearch)}`;

                fetch(url)
                .then(res => res.json())
                .then(data => {
                    const tbody = document.getElementById('ktngMaterialTableBody');
                    tbody.innerHTML = '';
                    if (!data.data || data.data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">등록된 KT&G 상품 품목이 없습니다.</td></tr>';
                        document.getElementById('ktngPaginationContainer').innerHTML = '';
                        return;
                    }

                    data.data.forEach((row, index) => {
                        currentMaterialMap[row.id] = row;
                        const rowNum = skip + index + 1;
                        const preQty = row.pre_weighing || 0;
                        const stockQty = row.stock_qty || 0;
                        const salesQty = row.sales_qty || 0;

                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${rowNum}</td>
                            <td><strong>${row.material_code || ''}</strong></td>
                            <td>${row.material_name_kr || ''}</td>
                            <td>${row.material_name_en || ''}</td>
                            <td><span class="clickable-no" onclick='openYearlyPreModal(${row.id})'>${preQty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</span></td>
                            <td><span class="clickable-no" onclick='openLotStockModal(${row.id})'>${stockQty.toLocaleString(undefined, {minimumFractionDigits: 3})} kg</span></td>
                            <td><input type="number" step="0.001" value="${salesQty}" id="sales_${row.id}" style="width:100px; padding:4px;" onchange="saveSalesQty(${row.id})"></td>
                            <td>
                                <button class="btn-action" onclick='openEditModal(${JSON.stringify(row)})' style="padding:5px 8px;">상세</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                    renderPagination(data.total, 'ktngPaginationContainer', loadKtngMaterials, ktngCurrentPage);
                });
            }

            function saveSalesQty(id) {
                const sales = parseFloat(document.getElementById(`sales_${id}`).value) || 0;
                const m = currentMaterialMap[id];
                if (!m) return;

                fetch(`/api/v1/materials/${id}/qtys`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sales_qty: sales })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        m.sales_qty = sales;
                    }
                });
            }

            function openYearlyPreModal(id) {
                const m = currentMaterialMap[id];
                if (!m) return;
                document.getElementById('yearly_target_id').value = id;
                document.getElementById('yearlyPreModalTitle').innerText = `연도별 예계량 관리 - [${m.material_code}] ${m.material_name_kr}`;
                
                const tbody = document.getElementById('yearlyRowsBody');
                tbody.innerHTML = '';
                
                const yearlyData = m.yearly_pre_weighing || {};
                const keys = Object.keys(yearlyData);
                if (keys.length === 0) {
                    addYearlyRow('2026', '');
                } else {
                    keys.forEach(year => {
                        addYearlyRow(year, yearlyData[year]);
                    });
                }
                document.getElementById('yearlyPreModal').style.display = 'flex';
            }

            function closeYearlyPreModal() {
                document.getElementById('yearlyPreModal').style.display = 'none';
            }

            function addYearlyRow(year='2026', qty='') {
                const tbody = document.getElementById('yearlyRowsBody');
                const tr = document.createElement('tr');
                tr.className = 'yearly-row';
                
                const years = ['2024', '2025', '2026', '2027', '2028', '2029', '2030'];
                let optionsHtml = '';
                years.forEach(y => {
                    const sel = (y === year) ? 'selected' : '';
                    optionsHtml += `<option value="${y}" ${sel}>${y}년</option>`;
                });

                tr.innerHTML = `
                    <td><select class="y-year" style="width:100%; padding:6px; border:1px solid #cbd5e1; border-radius:4px;">${optionsHtml}</select></td>
                    <td><input type="number" step="0.001" class="y-qty" value="${qty}" placeholder="수량 (kg)" style="width:100%; padding:6px; border:1px solid #cbd5e1; border-radius:4px;"></td>
                    <td><button type="button" class="btn-delete" onclick="this.closest('tr').remove()" style="padding:5px 10px;">삭제</button></td>
                `;
                tbody.appendChild(tr);
            }

            function saveYearlyPreData() {
                const id = document.getElementById('yearly_target_id').value;
                const rows = document.querySelectorAll('.yearly-row');
                const yearlyData = {};
                rows.forEach(r => {
                    const yr = r.querySelector('.y-year').value.trim();
                    const qt = parseFloat(r.querySelector('.y-qty').value) || 0;
                    if (yr) yearlyData[yr] = qt;
                });

                fetch(`/api/v1/materials/${id}/yearly-pre`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ yearly_data: yearlyData })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("연도별 예계량이 저장되었습니다.");
                        closeYearlyPreModal();
                        loadKtngMaterials(ktngCurrentPage);
                    }
                });
            }

            function openLotStockModal(id) {
                const m = currentMaterialMap[id];
                if (!m) return;
                document.getElementById('lot_target_id').value = id;
                document.getElementById('lotStockModalTitle').innerText = `LOT별 재고수량 관리 - [${m.material_code}] ${m.material_name_kr}`;
                
                const tbody = document.getElementById('lotRowsBody');
                tbody.innerHTML = '';
                
                const lotData = m.lot_stock || [];
                if (lotData.length === 0) {
                    addLotRow('', '');
                } else {
                    lotData.forEach(item => {
                        addLotRow(item.lot, item.qty);
                    });
                }
                document.getElementById('lotStockModal').style.display = 'flex';
            }

            function closeLotStockModal() {
                document.getElementById('lotStockModal').style.display = 'none';
            }

            function addLotRow(lot='', qty='') {
                const tbody = document.getElementById('lotRowsBody');
                const tr = document.createElement('tr');
                tr.className = 'lot-row';
                tr.innerHTML = `
                    <td><input type="text" class="l-lot" value="${lot}" placeholder="LOT 번호 입력" style="width:100%; padding:6px; border:1px solid #cbd5e1; border-radius:4px;"></td>
                    <td><input type="number" step="0.001" class="l-qty" value="${qty}" placeholder="수량 (kg)" style="width:100%; padding:6px; border:1px solid #cbd5e1; border-radius:4px;"></td>
                    <td><button type="button" class="btn-delete" onclick="this.closest('tr').remove()" style="padding:5px 10px;">삭제</button></td>
                `;
                tbody.appendChild(tr);
            }

            function saveLotStockData() {
                const id = document.getElementById('lot_target_id').value;
                const rows = document.querySelectorAll('.lot-row');
                const lotData = [];
                rows.forEach(r => {
                    const lotNo = r.querySelector('.l-lot').value.trim();
                    const qt = parseFloat(r.querySelector('.l-qty').value) || 0;
                    if (lotNo) lotData.push({ lot: lotNo, qty: qt });
                });

                fetch(`/api/v1/materials/${id}/lot-stock`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lot_data: lotData })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("LOT별 재고수량이 저장되었습니다.");
                        closeLotStockModal();
                        loadKtngMaterials(ktngCurrentPage);
                    }
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
                    const selectAllCb = document.getElementById('bomSelectAll');
                    if (selectAllCb) selectAllCb.checked = false;

                    if (!data.data || data.data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center;">등록된 품목이 없습니다.</td></tr>';
                        document.getElementById('bomPaginationContainer').innerHTML = '';
                        return;
                    }

                    data.data.forEach((row, index) => {
                        const rowNum = skip + index + 1;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><input type="checkbox" class="bom-row-checkbox" value="${row.id}"></td>
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
                    <td><input type="text" class="b-code" value="${code}" placeholder="원료코드" style="padding:4px; width:100%;" oninput="onBomCodeInput(this)"></td>
                    <td><input type="text" class="b-name" value="${name}" placeholder="원료명" style="padding:4px; width:100%;"></td>
                    <td><input type="number" step="0.001" class="b-qty" value="${qty}" placeholder="수량" style="padding:4px; width:100%;"></td>
                    <td><input type="text" class="b-unit" value="${unit}" style="padding:4px; width:100%;"></td>
                    <td><input type="text" class="b-cas" value="${cas}" placeholder="CAS No" style="padding:4px; width:100%;"></td>
                    <td><button type="button" class="btn-delete" onclick="this.closest('tr').remove()" style="padding:4px 8px;">삭제</button></td>
                `;
                tbody.appendChild(tr);
            }

            function onBomCodeInput(inputEl) {
                const code = inputEl.value.trim();
                if (code.length < 2) return;

                fetch(`/api/v1/materials/lookup?code=${encodeURIComponent(code)}`)
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS" && data.matches && data.matches.length > 0) {
                        const m = data.matches[0];
                        const tr = inputEl.closest('tr');
                        if (tr && m.material_name_kr) {
                            tr.querySelector('.b-name').value = m.material_name_kr;
                            if (m.cas_no) tr.querySelector('.b-cas').value = m.cas_no;
                        }
                    }
                });
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
                currentCategory = '';
                document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                const allBtn = document.getElementById('btn-cat-all');
                if (allBtn) allBtn.classList.add('active');
                loadMaterials(1);
            }
            function searchKtngMaterials() {
                currentKtngSearch = document.getElementById('ktngSearchInput').value.trim();
                loadKtngMaterials(1);
            }

            function resetKtngSearch() {
                document.getElementById('ktngSearchInput').value = '';
                currentKtngSearch = '';
                loadKtngMaterials(1);
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
                document.getElementById('new_category').value = '원재료';
                document.getElementById('new_remark').value = '';
                const sugg = document.getElementById('duplicateNameSuggestions');
                if (sugg) sugg.style.display = 'none';
                document.getElementById('createModal').style.display = 'flex';
            }

            function openCreateModalForKtng() {
                openCreateModal();
                document.getElementById('new_category').value = 'KT&G상품';
            }

            function closeCreateModal() {
                document.getElementById('createModal').style.display = 'none';
            }

            function onMaterialCodeInput(codeVal) {
                const code = codeVal.trim();
                if (code.length < 2) return;

                fetch(`/api/v1/materials/lookup?code=${encodeURIComponent(code)}`)
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS" && data.matches && data.matches.length > 0) {
                        const matches = data.matches;
                        if (matches.length === 1) {
                            document.getElementById('new_name_kr').value = matches[0].material_name_kr || '';
                            document.getElementById('new_category').value = matches[0].category || '원재료';
                            document.getElementById('duplicateNameSuggestions').style.display = 'none';
                        } else {
                            const select = document.getElementById('suggestedNamesSelect');
                            select.innerHTML = '<option value="">-- 일치하거나 유사한 제품 선택 (중복 항목) --</option>';
                            matches.forEach(m => {
                                const opt = document.createElement('option');
                                opt.value = JSON.stringify(m);
                                opt.innerText = `[${m.material_code}] ${m.material_name_kr}`;
                                select.appendChild(opt);
                            });
                            document.getElementById('duplicateNameSuggestions').style.display = 'block';
                        }
                    }
                });
            }

            function selectSuggestedName(valStr) {
                if (!valStr) return;
                const m = JSON.parse(valStr);
                document.getElementById('new_code').value = m.material_code || '';
                document.getElementById('new_name_kr').value = m.material_name_kr || '';
                document.getElementById('new_category').value = m.category || '원재료';
                document.getElementById('duplicateNameSuggestions').style.display = 'none';
            }

            function saveNewMaterial() {
                const code = document.getElementById('new_code').value.trim();
                const category = document.getElementById('new_category').value;

                const payload = {
                    material_code: code,
                    material_name_kr: document.getElementById('new_name_kr').value.trim(),
                    material_name_en: "",
                    cas_no: "",
                    supplier: "",
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
                        loadKtngMaterials(1);
                        loadBomMaterials(1);
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
                const category = document.getElementById('edit_category').value;

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
                        loadKtngMaterials(ktngCurrentPage);
                        loadBomMaterials(bomCurrentPage);
                    }
                });
            }

            function deleteMaterial(id, type) {
                if (!confirm("정말 이 원료 데이터를 삭제하시겠습니까?")) return;
                fetch(`/api/v1/materials/${id}`, { method: 'DELETE' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "SUCCESS") {
                        alert("삭제되었습니다.");
                        loadMaterials(currentPage);
                        if (type === 'ktng') loadKtngMaterials(ktngCurrentPage);
                        loadBomMaterials(bomCurrentPage);
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

 function submitLog(event) {
            event.preventDefault();
            const payload = {
                batch_id: document.getElementById('batch_id').value,
                manifold_id: document.getElementById('manifold_id').value,
                input_qty: parseFloat(document.getElementById('input_qty').value) || 0,
                operator_id: document.getElementById('operator_id').value,
                product_code: document.getElementById('log_product_code').value.trim()
            };
            
            fetch('/api/v1/production/batches/log', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === "SUCCESS") {
                    let msg = data.message;
                    if (data.deduction && data.deduction.length > 0) {
                        msg += "\n[BOM 재고 자동 차감 내역]\n" + data.deduction.join(", ");
                    }
                    alert(msg);
                    loadLogs();
                } else {
                    alert("전송 실패");
                }
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

            loadOrders(); loadWorkOrders(); loadLogs(); loadKtngMaterials(1); loadBomMaterials(1);
        </script>
    </body>
    </html>
    """
