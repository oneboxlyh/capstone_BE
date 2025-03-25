import os
import cv2
import numpy as np
import bcrypt
import face_recognition
from flask import Flask, request, jsonify, send_from_directory
import mysql.connector
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
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
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '24A39r98')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'face_detect')
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

@app.route("/health", methods=['GET'])
def health():
    return jsonify({"message": "Health check"}), 200

# ---------------- Authentication ----------------
@app.route('/login', methods=['POST'])
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
@app.route('/employee', methods=['POST'])
def create_employee():
    if 'profile_image' not in request.files:
        return jsonify({"message": "No image uploaded"}), 400

    file = request.files['profile_image']
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    dob = request.form.get('dob')

    if not all([first_name, last_name, dob]):
        return jsonify({"message": "Missing required fields"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    face_id = generate_face_id(file_path)
    if not face_id:
        os.remove(file_path)  # Clean up the saved file
        return jsonify({"message": "No face detected"}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO employees (first_name, last_name, dob, profile_image, face_id) VALUES (%s, %s, %s, %s, %s)",
            (first_name, last_name, dob, file_path, str(face_id)))
        db.commit()
        employee_id = cursor.lastrowid
        return jsonify({
            "message": "Employee added successfully",
            "id": employee_id,
            "face_id": face_id
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error creating employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/employee', methods=['GET'])
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

@app.route('/employee/<int:id>', methods=['GET'])
def get_employee(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM employees WHERE id=%s", (id,))
        employee = cursor.fetchone()
        if not employee:
            return jsonify({"error": "Employee not found"}), 404
        
        return jsonify({
            "id": employee["id"],
            "firstName": employee["first_name"],
            "lastName": employee["last_name"],
            "role": employee.get("role"),
            "profileImage": employee.get("profile_image"),
            "faceId": employee.get("face_id")
        }), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/employee/<int:id>', methods=['PUT'])
def update_employee(id):
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data provided"}), 400

    required_fields = ['first_name', 'last_name', 'dob']
    if not all(field in data for field in required_fields):
        return jsonify({"message": "Missing required fields"}), 400

    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE employees SET first_name=%s, last_name=%s, dob=%s WHERE id=%s",
            (data['first_name'], data['last_name'], data['dob'], id))
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({"message": "Employee not found"}), 404
        return jsonify({"message": "Employee updated successfully"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error updating employee: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/employee/<int:id>', methods=['DELETE'])
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
@app.route('/activity', methods=['POST'])
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

@app.route('/activity/sync', methods=['POST'])
def sync_activity():  # Changed function name to avoid conflict
    return create_activity()  # Reuse the same logic

@app.route('/activity', methods=['GET'])
def get_all_activities():  # Changed function name to avoid conflict
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM activities")
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

@app.route('/activity/<int:empId>', methods=['GET'])
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