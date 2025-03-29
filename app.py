import os
import numpy as np
import bcrypt
import face_recognition
import json
import time
from flask import Flask, request, jsonify, send_from_directory
import mysql.connector
from flask_jwt_extended import JWTManager, create_access_token
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True, allow_headers=["Content-Type", "Authorization"])

# Configurations
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your_secret_key')  # Better to use env variable
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'root')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'face_detect')
app.config['SERVER_URL'] = os.getenv('SERVER_URL', 'http://127.0.0.1:5000/')
app.config['UPLOAD_FOLDER'] = 'uploads'

jwt = JWTManager(app)

# Database connection function
def get_db_connection():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB']
    )

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route("/api/health", methods=['GET'])
def health():
    return jsonify({"message": "Health check"}), 200

@app.route('/uploads/<path:filename>')
@cross_origin()  # Allow all origins — you can restrict this if needed
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ---------------- Authentication ----------------
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data:
        return jsonify({"message": "No data provided"}), 400
        
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        access_token = create_access_token(identity={'id': user['id'], 'username': user['username']})
        return jsonify({"token": access_token}), 200
    else:
        return jsonify({"message": "Invalid credentials"}), 401

# ---------------- Face Recognition Function ----------------
def generate_face_id(image_path):
    try:
        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)

        if len(encodings) > 0:
            return np.array(encodings[0]).tolist()
        return None
    except Exception as e:
        print(f"Error generating face ID: {str(e)}")
        return None

# ---------------- Employee CRUD ----------------
@app.route('/api/employee', methods=['POST'])
def create_employee():
    print("[EMPLOYEE] Creating new employee...")

    if 'file' not in request.files:
        return jsonify({"message": "No image uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No selected file"}), 400

    # Extract form data
    first_name = request.form.get('firstName')
    last_name = request.form.get('lastName')
    role = request.form.get('role')

    if not all([first_name, last_name, role]):
        return jsonify({"message": "Missing required fields"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1]
    timestamp = int(time.time())
    unique_filename = f"{os.path.splitext(filename)[0]}_{timestamp}{ext}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(file_path)

    face_id = generate_face_id(file_path)
    if not face_id:
        os.remove(file_path)
        return jsonify({"message": "No face detected in uploaded image"}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO employees (first_name, last_name, role, profile_image, face_id) VALUES (%s, %s, %s, %s, %s)",
            (first_name, last_name, role, app.config["SERVER_URL"] + file_path, json.dumps(face_id))
        )
        db.commit()
        employee_id = cursor.lastrowid

        print(f"[EMPLOYEE] Created employee {first_name} {last_name} (ID: {employee_id})")

        return jsonify({
            "message": "Employee added successfully",
            "id": employee_id,
            "face_id": face_id
        }), 201
    except Exception as e:
        db.rollback()
        print(f"[EMPLOYEE] Error inserting employee: {str(e)}")
        return jsonify({"message": f"Error creating employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/employee', methods=['GET'])
def get_employees():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM employees")
        employees = cursor.fetchall()
        return jsonify([{
            "id": emp["id"],
            "firstName": emp["first_name"],
            "lastName": emp["last_name"],
            "role": emp.get("role"),
            "profileImage": emp.get("profile_image"),
            "faceId": emp.get("face_id")
        } for emp in employees]), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching employees: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard_summary():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Get total attendance count
        cursor.execute("SELECT COUNT(*) AS total_attendance FROM activities")
        total_attendance = cursor.fetchone()["total_attendance"]

        # Get total employee count
        cursor.execute("SELECT COUNT(*) AS total_employees FROM employees")
        total_employees = cursor.fetchone()["total_employees"]

        # Get total machine count
        cursor.execute("SELECT COUNT(*) AS total_machines FROM machines")
        total_machines = cursor.fetchone()["total_machines"]

        return jsonify({
            "totalAttendance": total_attendance,
            "totalEmployees": total_employees,
            "totalMachines": total_machines
        }), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching dashboard summary: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/employee/<int:id>', methods=['GET'])
def get_employee(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM employees WHERE id=%s", (id,))
        employee = cursor.fetchone()
        if not employee:
            return jsonify({"error": "Employee not found"}), 404
        
        # Fetch attendance records for this employee
        cursor.execute("""
            SELECT a.id, a.status, a.created_at, m.description 
            FROM activities a
            LEFT JOIN machines m ON a.machine_id = m.id
            WHERE a.employee_id = %s 
            ORDER BY a.created_at DESC
        """, (id,))
        attendance = cursor.fetchall()
        
        return jsonify({
            "id": employee["id"],
            "firstName": employee["first_name"],
            "lastName": employee["last_name"],
            "role": employee.get("role"),
            "profileImage": employee.get("profile_image"),
            "attendance": [
                {
                    "id": record["id"],
                    "machine": record["description"],
                    "status": record["status"],
                    "timestamp": record["created_at"].strftime("%Y-%m-%d %H:%M:%S") if record["created_at"] else None
                }
                for record in attendance
            ]
        }), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()


@app.route('/api/employee/<int:id>', methods=['PUT'])
def update_employee(id):
    print(f"[EMPLOYEE] Updating employee ID: {id}")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Handle form data and file
    first_name = request.form.get('firstName')
    last_name = request.form.get('lastName')
    role = request.form.get('role')
    file = request.files.get('file')

    if not all([first_name, last_name, role]):
        return jsonify({"message": "Missing required fields"}), 400

    # Fetch existing employee to retain current image if no new file provided
    cursor.execute("SELECT * FROM employees WHERE id=%s", (id,))
    employee = cursor.fetchone()

    if not employee:
        return jsonify({"message": "Employee not found"}), 404

    profile_image = employee['profile_image']
    face_id = employee['face_id']

    # If a new file is uploaded, update the image and regenerate face_id
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1]
        timestamp = int(time.time())
        unique_filename = f"{os.path.splitext(filename)[0]}_{timestamp}{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)

        new_face_id = generate_face_id(file_path)
        if not new_face_id:
            os.remove(file_path)
            return jsonify({"message": "No face detected in uploaded image"}), 400

        profile_image = file_path
        face_id = json.dumps(new_face_id)

    try:
        cursor.execute(
            "UPDATE employees SET first_name=%s, last_name=%s, role=%s, profile_image=%s, face_id=%s WHERE id=%s",
            (first_name, last_name, role, app.config["SERVER_URL"] + profile_image, face_id, id)
        )
        db.commit()

        print(f"[EMPLOYEE] Updated employee {first_name} {last_name} (ID: {id})")
        return jsonify({"message": "Employee updated successfully"}), 200
    except Exception as e:
        db.rollback()
        print(f"[EMPLOYEE] Error updating employee: {str(e)}")
        return jsonify({"message": f"Error updating employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/employee/<int:id>', methods=['DELETE'])
def delete_employee(id):
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM employees WHERE id=%s", (id,))
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"message": "Employee not found"}), 404
        return jsonify({"message": "Employee deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error deleting employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

# ---------------- Employee Activity CRUD ----------------
@app.route('/api/activity', methods=['POST'])
def create_activity():
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data provided"}), 400

    required_fields = ['employee_id', 'status']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields"}), 400

    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO activities (employee_id, status, created_at) VALUES (%s, %s, NOW())",
            (data['employee_id'], data['status']))
        db.commit()
        return jsonify({"message": "Activity recorded"}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error recording activity: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/activity/sync', methods=['POST'])
# @jwt_required()
def sync_activity():
    data = request.json
    activities = data.get('activities', [])

    if not isinstance(activities, list):
        return jsonify({"message": "Invalid payload"}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    report_cursor = db.cursor()

    for activity in activities:
        try:
            employee_id = activity.get('employee_id')
            machine_id = activity.get('machine_id')
            status = activity.get('status')
            timestamp = activity.get('created_at')  # Optional

            if not all([employee_id, machine_id, status]):
                continue

            if timestamp:
                cursor.execute(
                    "INSERT INTO activities (employee_id, machine_id, status, created_at, updated_at) VALUES (%s, %s, %s, %s, NOW())",
                    (employee_id, machine_id, status, timestamp)
                )
            else:
                cursor.execute(
                    "INSERT INTO activities (employee_id, machine_id, status, created_at, updated_at) VALUES (%s, %s, %s, NOW(), NOW())",
                    (employee_id, machine_id, status)
                )
        except Exception as e:
            try:
                report_cursor.execute(
                    "INSERT INTO report (endpoint, input, exception) VALUES (%s, %s, %s)",
                    ('/activity/sync', json.dumps(activity), str(e))
                )
                db.commit()
            except:
                pass  # Avoid blocking if logging to report also fails

    db.commit()
    cursor.close()
    report_cursor.close()

    return jsonify({"message": "Activities synced with fallback logging.", "count": len(activities)}), 201


@app.route('/api/activity', methods=['GET'])
def get_all_activities():  # Changed function name to avoid conflict
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT a.id, a.machine_id, a.status, a.created_at, e.first_name, e.last_name FROM activities a LEFT JOIN employees e ON a.employee_id = e.id ORDER BY a.created_at DESC")
        activities = cursor.fetchall()
        return jsonify([{
            "id": act["id"],
            "employee_name": act["first_name"] + " " + act["last_name"] if act["first_name"] else "-",
            "machine_id": act["machine_id"],
            "status": act["status"],
            "created_at": act["created_at"].isoformat() if act["created_at"] else None
        } for act in activities]), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching activities: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/api/activity/<int:empId>', methods=['GET'])
def get_employee_activities(empId):  # Changed function name to avoid conflict
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM activities WHERE employee_id = %s", (empId,))
        activities = cursor.fetchall()
        return jsonify([{
            "id": act["id"],
            "employee_id": act["employee_id"],
            "status": act["status"],
            "created_at": act["created_at"].isoformat() if act["created_at"] else None
        } for act in activities]), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching activities: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

# ---------------- Start Server ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)