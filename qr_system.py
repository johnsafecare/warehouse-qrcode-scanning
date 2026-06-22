from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
import pymysql
import qrcode
import os
import time

app = Flask(__name__)
app.secret_key = "super_secret_key_warehouse"
app.config['JSON_SORT_KEYS'] = False

# Create qrcodes directory if it doesn't exist
if not os.path.exists("images/qrcodes"):
    os.makedirs("images/qrcodes", exist_ok=True)

def connect_database():
    try:
        connection = None
        for pwd in ["1234", ""]:
            try:
                connection = pymysql.connect(
                    host="localhost",
                    user="root",
                    password=pwd,
                    port=3306
                )
                print("Connected successfully")
                break
            except Exception:
                continue

        if connection is None:
            raise Exception("Unable to connect to MySQL. Check password or port.")
            
        cursor = connection.cursor()

        # create database
        cursor.execute("CREATE DATABASE IF NOT EXISTS inventory_system")
        cursor.execute("USE inventory_system")

        # create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products
            (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id VARCHAR(50),
                name VARCHAR(100) NOT NULL,
                category VARCHAR(100),
                brand VARCHAR(100),
                qty INT DEFAULT 0,
                barcode VARCHAR(100),
                warehouse_name VARCHAR(100),
                section VARCHAR(100),
                rack VARCHAR(50),
                shelf VARCHAR(50),
                batch_no VARCHAR(100),
                total_qty INT DEFAULT 0,
                balance_qty INT DEFAULT 0,
                expiry_date VARCHAR(50)
            )
        """)
        
        # Alter table to add new columns if they do not exist
        for col_name, col_type in [
            ("batch_no", "VARCHAR(100)"),
            ("total_qty", "INT DEFAULT 0"),
            ("balance_qty", "INT DEFAULT 0"),
            ("expiry_date", "VARCHAR(50)"),
            ("bin_pallet", "VARCHAR(50)"),
            ("bin_pallet_no", "VARCHAR(50)"),
            ("subcategory", "VARCHAR(100)"),
            ("task_status", "VARCHAR(100)")
        ]:
            try:
                cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass
                
        try:
            cursor.execute("ALTER TABLE products DROP COLUMN price")
        except Exception:
            pass

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                password VARCHAR(50) NOT NULL
            )
        """)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'employee'")
        except Exception:
            pass

        cursor.execute("SELECT * FROM users WHERE username='admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'Binali@123', 'admin')")
        else:
            cursor.execute("UPDATE users SET role='admin' WHERE username='admin'")

        # Create activity_logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col_name, col_type in [
            ("product_id", "VARCHAR(50)"),
            ("product_name", "VARCHAR(100)"),
            ("warehouse", "VARCHAR(100)"),
            ("quantity", "INT")
        ]:
            try:
                cursor.execute(f"ALTER TABLE activity_logs ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

        # Migrate existing table to use `id` as PRIMARY KEY instead of `product_id`
        try:
            cursor.execute("SHOW COLUMNS FROM products LIKE 'id'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE products DROP PRIMARY KEY")
                cursor.execute("ALTER TABLE products ADD COLUMN id INT AUTO_INCREMENT PRIMARY KEY FIRST")
        except Exception as e:
            print("Migration exception:", e)

        connection.commit()
        connection.close()
        print("Database and products table verified successfully")
    except Exception as e:
        print("Error during database connection/creation:", e)

_db_cached_pwd = [None]

def get_db_connection():
    if _db_cached_pwd[0] is not None:
        try:
            return pymysql.connect(
                host="localhost",
                user="root",
                password=_db_cached_pwd[0],
                port=3306,
                database="inventory_system",
                connect_timeout=5,
            )
        except Exception:
            _db_cached_pwd[0] = None

    for pwd in ["1234", ""]:
        try:
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password=pwd,
                port=3306,
                database="inventory_system",
                connect_timeout=5,
            )
            _db_cached_pwd[0] = pwd
            return conn
        except Exception:
            pass
    raise Exception("Unable to connect to MySQL. Check password or port.")

# Initialize DB on startup
connect_database()

def log_activity(username, action, details="", product_id=None, product_name=None, warehouse=None, quantity=None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity_logs (username, action, details, product_id, product_name, warehouse, quantity) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (username, action, details, product_id, product_name, warehouse, quantity)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging activity: {e}")

# --- Routes ---

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/admin")
def admin_page():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html")

@app.route("/admin_dashboard")
def admin_dashboard():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("admin_page"))
    return render_template("admin_dashboard.html")

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = data.get("username", "")
    pwd = data.get("password", "")
    is_admin_login = data.get("is_admin", False)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        if is_admin_login:
            cur.execute("SELECT * FROM users WHERE username=%s AND password=%s AND role='admin'", (user, pwd))
        else:
            cur.execute("SELECT * FROM users WHERE username=%s AND password=%s AND (role='employee' OR role IS NULL)", (user, pwd))
            
        row = cur.fetchone()
        conn.close()
        
        if row:
            session["user"] = user
            session["role"] = row.get("role", "employee")
            log_activity(user, "LOGIN", "User logged in")
            return jsonify({"success": True, "role": session.get("role")})
        else:
            return jsonify({"success": False, "message": "Invalid Username or Password"}), 401
    except Exception as e:
        return jsonify({"success": False, "message": f"Database Error: {e}"}), 500

@app.route("/api/admin/employees", methods=["GET"])
def get_employees():
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        conn = get_db_connection()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT id, username, password FROM users WHERE role='employee' OR role IS NULL")
        employees = cur.fetchall()
        conn.close()
        return jsonify({"success": True, "employees": employees})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/admin/employees", methods=["POST"])
def add_employee():
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required"}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Username already exists"}), 400
            
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'employee')", (username, password))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/admin/employees/<int:emp_id>", methods=["DELETE"])
def delete_employee(emp_id):
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id=%s AND (role='employee' OR role IS NULL)", (emp_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/logout", methods=["POST"])
def logout():
    user = session.get("user")
    if user:
        log_activity(user, "LOGOUT", "User logged out")
    session.pop("user", None)
    session.pop("role", None)
    return jsonify({"success": True})

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("index"))
    return render_template("dashboard.html")

@app.route("/api-converter")
def api_converter():
    if "user" not in session:
        return redirect(url_for("index"))
    return render_template("api_converter.html")

import json
import urllib.request
import urllib.error
import time

@app.route("/api/fetch-and-save-link", methods=["POST"])
def fetch_and_save_link():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.json
    api_url = data.get("api_url", "").strip()
    if not api_url:
        return jsonify({"success": False, "message": "API URL is required"}), 400
        
    try:
        # Fetch data
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        # Ensure directory exists
        save_dir = "fetched_data"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
            
        # Save to file
        filename = f"fetched_{int(time.time())}.json"
        filepath = os.path.join(save_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
            
        return jsonify({"success": True, "message": f"Data fetched and saved to {filepath}", "data": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/save-api-data", methods=["POST"])
def save_api_data():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        data = request.json
        with open("api_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/get-api-data", methods=["GET"])
def get_api_data():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    try:
        if os.path.exists("api_data.json"):
            with open("api_data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify({"success": True, "data": data})
        else:
            return jsonify({"success": True, "data": []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/product/<path:product_id>")
def get_product(product_id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute(
            "SELECT product_id, name, category, brand, qty, warehouse_name, section, rack, shelf, barcode, "
            "batch_no, total_qty, balance_qty, expiry_date, bin_pallet, bin_pallet_no, task_status "
            "FROM products WHERE product_id=%s OR barcode=%s ORDER BY warehouse_name",
            (product_id, product_id)
        )
        rows = cursor.fetchall()

        if rows:
            first_row = rows[0]
            total_qty_stock = sum(r[4] for r in rows if r[4] is not None)
            
            warehouses = []
            for r in rows:
                warehouses.append({
                    "warehouse_name": r[5] or "--",
                    "section": r[6] or "--",
                    "rack": r[7] or "--",
                    "shelf": r[8] or "--",
                    "qty": r[4] or 0,
                    "bin_pallet": r[14] or "",
                    "bin_pallet_no": r[15] or ""
                })
                
            data = {
                "product_id": first_row[0],
                "name": first_row[1],
                "category": first_row[2] or "--",
                "brand": first_row[3] or "--",
                "barcode": first_row[9] or first_row[0],
                "batch_no": first_row[10] or "--",
                "total_qty": str(first_row[11]) if first_row[11] is not None else "--",
                "balance_qty": str(first_row[12]) if first_row[12] is not None else "--",
                "expiry_date": first_row[13] or "--",
                "task_status": first_row[16] or "",
                "warehouses": warehouses,
                "total_qty_stock": total_qty_stock
            }
            connection.close()
            return jsonify({"success": True, "data": data})
        else:
            connection.close()
            return jsonify({"success": False, "message": "Product not found"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/product/generate", methods=["POST"])
def generate_product():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    data = request.json
    pid = data.get("product_id", "").strip()
    pname = data.get("name", "").strip()
    
    if not pid or not pname:
        return jsonify({"success": False, "message": "Product ID and Name are required"}), 400
        
    try:
        cat = data.get("category", "").strip()
        subcat = data.get("subcategory", "").strip()
        task_status = data.get("task_status", "").strip()
        brand = data.get("brand", "").strip()
        w_sec = data.get("section", "").strip()
        w_name = data.get("warehouse_name", "").strip()
        rack = data.get("rack", "").strip()
        shelf = data.get("shelf", "").strip()
        bin_pallet = data.get("bin_pallet", "").strip()
        bin_pallet_no = data.get("bin_pallet_no", "").strip()
        barcode_val = pid
        batch_no = data.get("batch_no", "").strip()
        expiry_date_val = data.get("expiry_date", "").strip()
        if expiry_date_val == "YYYY-MM-DD":
            expiry_date_val = ""
            
        qty_add = int(data.get("qty_add", 0))
        qty_remove = int(data.get("qty_remove", 0))
        current_qty = int(data.get("current_qty", 0))

        qty = current_qty + qty_add - qty_remove
        if qty < 0:
            qty = 0

        connection = get_db_connection()
        cursor = connection.cursor()

        if bin_pallet.lower() == 'pallet' and bin_pallet_no:
            cursor.execute("""
                SELECT product_id, name FROM products
                WHERE LOWER(bin_pallet)='pallet' AND bin_pallet_no=%s AND product_id != %s
                LIMIT 1
            """, (bin_pallet_no, pid))
            conflict = cursor.fetchone()
            if conflict:
                connection.close()
                return jsonify({
                    "success": False,
                    "message": "Another item already exists in the selected pallet. Please change to another pallet."
                }), 400

        cursor.execute("""
            SELECT id FROM products 
            WHERE product_id=%s AND warehouse_name=%s AND section=%s AND rack=%s AND shelf=%s AND batch_no=%s AND IFNULL(bin_pallet_no, '')=%s
        """, (pid, w_name, w_sec, rack, shelf, batch_no, bin_pallet_no))
        existing_row = cursor.fetchone()

        action = ""
        if existing_row:
            cursor.execute("""
                UPDATE products
                SET name=%s, category=%s, subcategory=%s, task_status=%s, brand=%s, qty=%s, barcode=%s, expiry_date=%s, bin_pallet=%s, bin_pallet_no=%s
                WHERE id=%s
            """, (pname, cat, subcat, task_status, brand, qty, barcode_val, expiry_date_val, bin_pallet, bin_pallet_no, existing_row[0]))
            action = "updated"
        else:
            cursor.execute("""
                INSERT INTO products
                    (product_id, name, category, subcategory, task_status, brand, qty, barcode, warehouse_name,
                     section, rack, shelf, batch_no, expiry_date, bin_pallet, bin_pallet_no)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (pid, pname, cat, subcat, task_status, brand, qty, barcode_val, w_name, w_sec, rack, shelf,
                   batch_no, expiry_date_val, bin_pallet, bin_pallet_no))
            action = "saved"

        cursor.execute("SELECT SUM(qty) FROM products WHERE product_id=%s", (pid,))
        sum_row = cursor.fetchone()
        total_sum = int(sum_row[0]) if sum_row and sum_row[0] else 0

        new_total = total_sum
        new_balance = total_sum

        cursor.execute("""
            UPDATE products
            SET total_qty=%s, balance_qty=%s, name=%s, category=%s, brand=%s, barcode=%s
            WHERE product_id=%s
        """, (new_total, new_balance, pname, cat, brand, barcode_val, pid))
            
        cursor.execute("SELECT warehouse_name, section, qty, expiry_date FROM products WHERE product_id=%s", (pid,))
        all_records = cursor.fetchall()
        
        locations_str = ""
        for rec in all_records:
            w_n = rec[0] or "--"
            w_s = rec[1] or "--"
            q = rec[2] or 0
            exp = rec[3] or "--"
            locations_str += f"- {w_n}: {q} units | Exp: {exp}\n"
            
        connection.commit()
        connection.close()
        
        actual_action = 'UPDATE_PRODUCT' if action == 'updated' else 'ADD_PRODUCT'
        log_activity(session['user'], actual_action, f"Product: {pid} - {pname} (Qty Add: {qty_add}, Qty Remove: {qty_remove})", product_id=pid, product_name=pname, warehouse=w_name, quantity=qty)
        
        qr_data = (f"Product ID: {pid}\n"
                   f"Name: {pname}\n"
                   f"Category: {cat}\n"
                   f"Subcategory: {subcat}\n"
                   f"Task Status: {task_status}\n"
                   f"Brand: {brand}\n"
                   f"Total Quantity: {new_total}\n"
                   f"\n--- Stock Locations ---\n"
                   f"{locations_str.strip()}")
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        img_qr = qr.make_image(fill_color="black", back_color="white")
        qr_file_path = f"images/qrcodes/{pid}.png"
        img_qr.save(qr_file_path)
        
        return jsonify({
            "success": True, 
            "message": f"Product successfully {action} and QR Code generated!",
            "qr_url": f"/images/qrcodes/{pid}.png?t={int(time.time())}",
            "qty": qty,
            "total_qty": new_total,
            "balance_qty": new_balance
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, product_id, name, category, brand, qty, 
                   warehouse_name, rack, shelf, batch_no, expiry_date, bin_pallet, bin_pallet_no
            FROM products ORDER BY name
        """)
        rows = cur.fetchall()
        
        cur.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''")
        categories = sorted([row[0] for row in cur.fetchall()])
        
        cur.execute("SELECT DISTINCT warehouse_name FROM products WHERE warehouse_name IS NOT NULL AND warehouse_name != ''")
        warehouses = sorted([row[0] for row in cur.fetchall()])
        
        conn.close()
        
        inventory = []
        for r in rows:
            inventory.append({
                "id": r[0],
                "product_id": r[1],
                "name": r[2],
                "category": r[3],
                "brand": r[4],
                "qty": r[5] or 0,
                "warehouse_name": r[6],
                "rack": r[7],
                "shelf": r[8],
                "batch_no": r[9],
                "expiry_date": r[10],
                "bin_pallet": r[11] or "",
                "bin_pallet_no": r[12] or ""
            })
            
        return jsonify({
            "success": True, 
            "inventory": inventory,
            "categories": categories,
            "warehouses": warehouses
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/inventory/<int:id>", methods=["DELETE"])
def delete_inventory(id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT product_id, name FROM products WHERE id=%s", (id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Record not found"}), 404
            
        product_id = row[0]
        product_name = row[1]
        
        cur.execute("DELETE FROM products WHERE id=%s", (id,))
        
        cur.execute("SELECT SUM(qty) FROM products WHERE product_id=%s", (product_id,))
        sum_row = cur.fetchone()
        total_sum = int(sum_row[0]) if sum_row and sum_row[0] else 0
        
        cur.execute("""
            UPDATE products
            SET total_qty=%s, balance_qty=%s
            WHERE product_id=%s
        """, (total_sum, total_sum, product_id))
        
        conn.commit()
        conn.close()
        
        log_activity(session['user'], 'REMOVE_PRODUCT', f"Removed Product Record: {product_id} - {product_name}", product_id=product_id, product_name=product_name)
        
        if total_sum == 0:
            qr_img_path = f"images/qrcodes/{product_id}.png"
            if os.path.exists(qr_img_path):
                try:
                    os.remove(qr_img_path)
                except Exception:
                    pass
                    
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/activity-logs", methods=["GET"])
def get_activity_logs():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        conn = get_db_connection()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM activity_logs ORDER BY timestamp DESC")
        logs = cur.fetchall()
        conn.close()
        
        for log in logs:
            if log.get('timestamp'):
                log['timestamp'] = log['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/tracking/warehouses", methods=["GET"])
def get_tracking_warehouses():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT warehouse_name FROM products WHERE warehouse_name IS NOT NULL AND warehouse_name != ''")
        wh_list = sorted([r[0] for r in cur.fetchall()])
        conn.close()
        return jsonify({"success": True, "warehouses": wh_list})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/tracking/search", methods=["GET"])
def search_tracking():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    query = request.args.get("q", "")
    if not query:
        return jsonify({"success": False, "message": "Empty query"}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Exact match first (try ID then Name)
        cur.execute(
            "SELECT product_id, name FROM products WHERE product_id=%s OR name=%s LIMIT 1",
            (query, query)
        )
        row = cur.fetchone()
        if not row:
            # Partial match (try ID then Name)
            cur.execute(
                "SELECT product_id, name FROM products WHERE product_id LIKE %s OR name LIKE %s LIMIT 1",
                (f"%{query}%", f"%{query}%")
            )
            row = cur.fetchone()

        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Not found"}), 404

        found_pid, found_name = row[0], row[1]

        # Step 2: fetch ALL warehouse records for that product
        cur.execute(
            "SELECT warehouse_name, rack, shelf, qty, section, batch_no, expiry_date, bin_pallet, bin_pallet_no "
            "FROM products WHERE product_id=%s ORDER BY warehouse_name, rack, shelf",
            (found_pid,)
        )
        all_rows = cur.fetchall()
        conn.close()

        warehouses = []
        total_qty = 0
        for r in all_rows:
            q = r[3] or 0
            total_qty += q
            warehouses.append({
                "warehouse_name": r[0] or "--",
                "rack": r[1] or "--",
                "shelf": r[2] or "--",
                "qty": q,
                "section": r[4] or "--",
                "batch_no": r[5] or "--",
                "expiry_date": r[6] or "--",
                "bin_pallet": r[7] or "",
                "bin_pallet_no": r[8] or ""
            })

        return jsonify({
            "success": True,
            "data": {
                "product_id": found_pid,
                "name": found_name,
                "total_qty": total_qty,
                "warehouses": warehouses
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/tracking/move", methods=["POST"])
def move_item():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.json
    product_id    = data.get("product_id", "").strip()
    from_wh       = data.get("from_warehouse", "").strip()
    from_rack     = data.get("from_rack", "").strip()
    from_shelf    = data.get("from_shelf", "").strip()
    to_wh         = data.get("to_warehouse", "").strip()
    to_rack       = data.get("to_rack", "").strip()
    to_shelf      = data.get("to_shelf", "").strip()

    try:
        qty = int(data.get("qty", 0))
    except (ValueError, TypeError):
        qty = 0

    if not product_id:
        return jsonify({"success": False, "message": "product_id is required"}), 400
    if not from_rack or not from_shelf:
        return jsonify({"success": False, "message": "Source rack and shelf are required"}), 400
    if not to_rack or not to_shelf:
        return jsonify({"success": False, "message": "Destination rack and shelf are required"}), 400
    if qty <= 0:
        return jsonify({"success": False, "message": "Quantity to move must be greater than zero"}), 400

    # Disallow moving to the exact same location
    if from_wh == to_wh and from_rack == to_rack and from_shelf == to_shelf:
        return jsonify({"success": False, "message": "Source and destination location are the same"}), 400

    try:
        conn = get_db_connection()
        cur  = conn.cursor()

        # --- Locate source row ---
        cur.execute(
            "SELECT id, qty, name, category, brand, barcode, batch_no, expiry_date, section "
            "FROM products "
            "WHERE product_id=%s AND IFNULL(warehouse_name, '')=%s AND rack=%s AND shelf=%s",
            (product_id, from_wh, from_rack, from_shelf)
        )
        src = cur.fetchone()
        if not src:
            conn.close()
            return jsonify({"success": False, "message": "Source record not found"}), 404

        src_id, src_qty, pname, cat, brand, barcode, batch_no, expiry_date, section = src

        if qty > src_qty:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Cannot move {qty} units — only {src_qty} available at that location"
            }), 400

        # --- Deduct from source ---
        new_src_qty = src_qty - qty
        if new_src_qty == 0:
            cur.execute("DELETE FROM products WHERE id=%s", (src_id,))
        else:
            cur.execute("UPDATE products SET qty=%s WHERE id=%s", (new_src_qty, src_id))

        # --- Find or create destination row ---
        cur.execute(
            "SELECT id, qty FROM products "
            "WHERE product_id=%s AND IFNULL(warehouse_name, '')=%s AND rack=%s AND shelf=%s",
            (product_id, to_wh, to_rack, to_shelf)
        )
        dst = cur.fetchone()
        if dst:
            cur.execute("UPDATE products SET qty=%s WHERE id=%s", (dst[1] + qty, dst[0]))
        else:
            cur.execute(
                "INSERT INTO products "
                "(product_id, name, category, brand, qty, barcode, warehouse_name, section, rack, shelf, batch_no, expiry_date) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (product_id, pname, cat, brand, qty, barcode, to_wh, section, to_rack, to_shelf, batch_no, expiry_date)
            )

        # --- Recalculate totals ---
        cur.execute("SELECT SUM(qty) FROM products WHERE product_id=%s", (product_id,))
        total_row = cur.fetchone()
        total = int(total_row[0]) if total_row and total_row[0] else 0
        cur.execute(
            "UPDATE products SET total_qty=%s, balance_qty=%s WHERE product_id=%s",
            (total, total, product_id)
        )

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Item moved successfully"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/tracking/map", methods=["GET"])
def get_tracking_map():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    wh = request.args.get("warehouse", "All Warehouses")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if wh == "All Warehouses":
            cur.execute("SELECT warehouse_name, product_id, name, rack, shelf, qty, bin_pallet, bin_pallet_no FROM products WHERE rack IS NOT NULL AND rack != ''")
        else:
            cur.execute("SELECT warehouse_name, product_id, name, rack, shelf, qty, bin_pallet, bin_pallet_no FROM products WHERE warehouse_name=%s AND rack IS NOT NULL AND rack != ''", (wh,))
        rows = cur.fetchall()
        conn.close()
        
        warehouses = {}
        for w_name, pid, pname, r, s, qty, bp, bp_no in rows:
            if not w_name: w_name = "Unknown Warehouse"
            r_str, s_str = str(r), str(s)
            
            if w_name not in warehouses:
                warehouses[w_name] = {}
            if r_str not in warehouses[w_name]:
                warehouses[w_name][r_str] = {}
            if s_str not in warehouses[w_name][r_str]:
                warehouses[w_name][r_str][s_str] = []
            
            bp_str = f"{bp or ''} {bp_no or ''}".strip()
            warehouses[w_name][r_str][s_str].append({"id": pid, "name": pname, "qty": qty or 0, "bin_pallet": bp_str})
            
        return jsonify({"success": True, "map_data": warehouses})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/scan", methods=["GET"])
def api_scan():
    product_code = request.args.get("productCode")
    page = request.args.get("page")
    size = request.args.get("size")

    if page is not None and not str(page).isdigit():
        return jsonify({"error": "Invalid query parameters (page must be numeric)"}), 400
    if size is not None and not str(size).isdigit():
        return jsonify({"error": "Invalid query parameters (size must be numeric)"}), 400

    if not product_code:
        return jsonify({"error": "Invalid query parameters (productCode is required)"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM products WHERE product_id=%s OR barcode=%s", (product_code, product_code))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return jsonify({"error": "No product exists for the given productCode"}), 404

        if page is not None and size is not None:
            p = int(page)
            s = int(size)
            start = (p - 1) * s
            end = start + s
            rows = rows[start:end]

        return jsonify({"data": rows}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory('images', filename)

if __name__ == "__main__":
    import mimetypes
    mimetypes.add_type('text/css', '.css')
    mimetypes.add_type('application/javascript', '.js')
    app.run(host="0.0.0.0", port=5050, debug=True, use_reloader=False)
