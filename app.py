from bson import ObjectId
from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "1234567890"

client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["road-alert"]
users = db["users"]
reports = db["reports"]  # reports collection
policeteams = db["policeteams"]
ambulanceteams = db["ambulanceteams"]  # new collection for ambulance teams
fireteams = db["fireteams"]  # new collection for fire teams

# Static login credentials for police, ambulance, firefighters
STATIC_ACCOUNTS = {
    "police": {"email": "police@gmail.com", "password": "police123", "role": "police"},
    "ambulance": {"email": "ambulance@gmail.com", "password": "ambulance123", "role": "ambulance"},
    "firefighter": {"email": "firefighter@gmail.com", "password": "fire123", "role": "firefighter"}
}

@app.route("/")
def home():
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        if users.find_one({"email": email}):
            return jsonify({"message": "Email already exists"}), 400

        hashed_password = generate_password_hash(password)
        users.insert_one({"name": name, "email": email, "password": hashed_password, "role": "civilian"})

        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        # Check if user is trying to log in as police, ambulance, or firefighter
        for key, account in STATIC_ACCOUNTS.items():
            if email == account["email"] and password == account["password"]:
                session["user"] = {"email": email, "role": key}
                return redirect(url_for("dashboard"))

        # Civilian login
        user = users.find_one({"email": email})
        if user and check_password_hash(user["password"], password):
            session["user"] = {"email": user["email"], "name": user["name"], "role": "civilian"}
            return redirect(url_for("dashboard"))

        return jsonify({"message": "Invalid credentials"}), 401

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = session["user"]
    
    # Redirect users to their respective dashboards
    if user["role"] == "civilian":
        latest_reports = list(reports.find(
            {"reported_by": user["email"]}  # Filter by user's email
        ).sort("_id", -1).limit(2))        # Get 2 most recent reports
        return render_template("userdashboard.html", user=user, reports=latest_reports)
    elif user["role"] == "police":
        # Fetch police-specific reports (vehicle collision, other incidents)
        reports_data = list(reports.find({"incident_type": {"$in": ["Vehicle Collision", "Other"]}}))
        return render_template("policedashboard.html", user=user, reports=reports_data)
    elif user["role"] == "ambulance":
        # Fetch ambulance-specific reports (medical emergency, vehicle collision)
        reports_data = list(reports.find({"incident_type": {"$in": ["Medical Emergency", "Vehicle Collision", "Fire Incident"]}}))
        return render_template("ambulancedashboard.html", user=user, reports=reports_data)
    elif user["role"] == "firefighter":
        # Fetch firefighter-specific reports (fire incident)
        reports_data = list(reports.find({"incident_type": "Fire Incident"}))
        return render_template("firedashboard.html", user=user, reports=reports_data)

    return redirect(url_for("login"))

# API for reporting an accident
@app.route("/report", methods=["POST"])
def report_accident():
    if "user" not in session:
        return jsonify({"message": "You must be logged in to report an accident."}), 401
    
    user = session["user"]

    # Get the data from the form submission (from the user)
    location = request.form.get("location")
    incident_type = request.form.get("incident_type")
    description = request.form.get("description")
    severity = request.form.get("severity")
    
    # Validate the form data
    if not location or not incident_type or not description or not severity:
        return jsonify({"message": "All fields are required."}), 400

    # Create the report document
    report = {
        "reported_by": user["email"],  # who reported (from the session)
        "location": location,
        "incident_type": incident_type,
        "description": description,
        "severity": severity,
        "status": "pending",  # initial status is pending
    }

    # Insert the report into the MongoDB collection
    reports.insert_one(report)

    return jsonify({"message": "Accident reported successfully!"}), 201

@app.route("/user_reports")
def user_reports():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    user_reports = list(reports.find({"reported_by": user["email"]}))  # Fetch all reports for the logged-in user

    return render_template("user_reports.html", user=user, reports=user_reports)


@app.route("/update_status", methods=["POST"])
def update_status():
    if "user" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    report_id = data.get("report_id")
    new_status = data.get("status")

    if not report_id or not new_status:
        return jsonify({"success": False, "error": "Invalid request"}), 400

    # Update the report status
    result = reports.update_one({"_id": ObjectId(report_id)}, {"$set": {"status": new_status}})

    if result.modified_count > 0:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Update failed"}), 500

@app.route("/add_team", methods=["POST"])
def add_team():
    if "user" not in session or session["user"].get("role") != "police":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    team_name = data.get("team_name")
    num_officers = data.get("num_officers")

    if not team_name or not num_officers:
        return jsonify({"success": False, "error": "Team name and number of officers are required"}), 400

    new_team = {
        "team_name": team_name,
        "num_officers": num_officers,
        "status": "active"
    }
    policeteams.insert_one(new_team)

    return jsonify({"success": True, "message": "Team added successfully"}), 201

# API to get all police teams
@app.route("/get_teams", methods=["GET"])
def get_teams():
    if "user" not in session or session["user"].get("role") != "police":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    teams = list(policeteams.find({}, {"_id": 0}))  # Exclude ObjectId from response
    return jsonify({"success": True, "teams": teams})

# API to delete a police team
@app.route("/delete_team", methods=["POST"])
def delete_team():
    if "user" not in session or session["user"].get("role") != "police":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    team_name = data.get("team_name")

    if not team_name:
        return jsonify({"success": False, "error": "Team name is required"}), 400

    result = policeteams.delete_one({"team_name": team_name})

    if result.deleted_count > 0:
        return jsonify({"success": True, "message": "Team deleted successfully"})
    else:
        return jsonify({"success": False, "error": "Team not found"}), 404

# API to add ambulance team
@app.route("/add_ambulance_team", methods=["POST"])
def add_ambulance_team():
    if "user" not in session or session["user"].get("role") != "ambulance":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    team_name = data.get("team_name")
    num_paramedics = data.get("num_paramedics")
    vehicle_id = data.get("vehicle_id")

    if not team_name or not num_paramedics or not vehicle_id:
        return jsonify({"success": False, "error": "All fields are required"}), 400

    new_team = {
        "team_name": team_name,
        "num_paramedics": num_paramedics,
        "vehicle_id": vehicle_id,
        "status": "active"
    }
    ambulanceteams.insert_one(new_team)

    return jsonify({"success": True, "message": "Ambulance team added successfully"}), 201

# API to add fire team
@app.route("/add_fire_team", methods=["POST"])
def add_fire_team():
    if "user" not in session or session["user"].get("role") != "firefighter":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    team_name = data.get("team_name")
    num_firefighters = data.get("num_firefighters")
    vehicle_type = data.get("vehicle_type")

    if not team_name or not num_firefighters or not vehicle_type:
        return jsonify({"success": False, "error": "All fields are required"}), 400

    new_team = {
        "team_name": team_name,
        "num_firefighters": num_firefighters,
        "vehicle_type": vehicle_type,
        "status": "active"
    }
    fireteams.insert_one(new_team)

    return jsonify({"success": True, "message": "Fire team added successfully"}), 201

# API to get all ambulance teams
@app.route("/get_ambulance_teams", methods=["GET"])
def get_ambulance_teams():
    if "user" not in session or session["user"].get("role") != "ambulance":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    teams = list(ambulanceteams.find({}, {"_id": 0}))
    return jsonify({"success": True, "teams": teams})

# API to get all fire teams
@app.route("/get_fire_teams", methods=["GET"])
def get_fire_teams():
    if "user" not in session or session["user"].get("role") != "firefighter":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    teams = list(fireteams.find({}, {"_id": 0}))
    return jsonify({"success": True, "teams": teams})

if __name__ == "__main__":
    app.run(port=3000, debug=True)
