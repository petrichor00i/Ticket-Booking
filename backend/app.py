from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from flask_cors import cross_origin
import jwt
import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from database.db_connection import create_connection, execute_query, execute_read_query
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import logging
import os
import json

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
        "origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept-Language"],
        "supports_credentials": True,
        "expose_headers": ["Content-Disposition"],
        "max_age": 3600
    }
})
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'Mosim1991m2')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MESSAGES = {
    'en': {
        'token_missing': 'Token is missing!',
        'token_expired': 'Token has expired!',
        'token_invalid': 'Token is invalid!',
        'no_data': 'No data provided',
        'missing_fields': 'Missing required fields',
        'password_short': 'Password must be at least 8 characters',
        'user_exists': 'Username or email already exists',
        'register_failed': 'Registration failed',
        'user_created': 'User created successfully',
        'invalid_credentials': 'Invalid username or password',
        'login_failed': 'Login failed',
        'flight_search_failed': 'Failed to search flights',
        'flight_id_required': 'Flight ID is required',
        'no_seats': 'No available seats',
        'booking_failed': 'Booking failed',
        'booking_success': 'Flight booked successfully',
        'stats_failed': 'Failed to generate booking stats',
        'bookings_failed': 'Failed to get bookings',
        'not_found': 'Endpoint not found',
        'server_error': 'Internal server error'
    },
    'fa': {
        'token_missing': 'توکن وجود ندارد!',
        'token_expired': 'توکن منقضی شده است!',
        'token_invalid': 'توکن نامعتبر است!',
        'no_data': 'داده‌ای ارائه نشده است',
        'missing_fields': 'فیلدهای مورد نیاز وجود ندارند',
        'password_short': 'رمز عبور باید حداقل ۸ کاراکتر باشد',
        'user_exists': 'نام کاربری یا ایمیل قبلاً ثبت شده است',
        'register_failed': 'ثبت‌نام ناموفق بود',
        'user_created': 'کاربر با موفقیت ایجاد شد',
        'invalid_credentials': 'نام کاربری یا رمز عبور نامعتبر است',
        'login_failed': 'ورود ناموفق بود',
        'flight_search_failed': 'جستجوی پروازها ناموفق بود',
        'flight_id_required': 'شناسه پرواز مورد نیاز است',
        'no_seats': 'صندلی موجود نیست',
        'booking_failed': 'رزرو ناموفق بود',
        'booking_success': 'پرواز با موفقیت رزرو شد',
        'stats_failed': 'تولید آمار رزروها ناموفق بود',
        'bookings_failed': 'دریافت رزروها ناموفق بود',
        'not_found': 'مسیر یافت نشد',
        'server_error': 'خطای داخلی سرور'
    }
}

def get_message(key, lang='en', default=''):
    return MESSAGES.get(lang, {}).get(key, default)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        if not token:
            logger.warning("Attempt to access protected route without token")
            return jsonify({'message': get_message('token_missing', lang)}), 403

        try:
            token_parts = token.split()
            if len(token_parts) != 2 or token_parts[0].lower() != 'bearer':
                raise ValueError("Invalid token format")

            data = jwt.decode(
                token_parts[1], app.config['SECRET_KEY'], algorithms=["HS256"])
            request.user_data = data
        except jwt.ExpiredSignatureError:
            logger.warning("Expired token attempt")
            return jsonify({'message': get_message('token_expired', lang)}), 403
        except Exception as e:
            logger.error(f"Token validation failed: {str(e)}")
            return jsonify({'message': get_message('token_invalid', lang)}), 403

        return f(*args, **kwargs)
    return decorated

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        if not data:
            abort(400, description=get_message('no_data', lang))

        required_fields = ['username', 'email', 'password']
        if not all(field in data for field in required_fields):
            abort(400, description=get_message('missing_fields', lang))

        username = data['username'].strip()
        email = data['email'].strip().lower()
        password = data['password']

        if len(password) < 8:
            abort(400, description=get_message('password_short', lang))

        connection = create_connection()

        check_query = """
        SELECT * FROM users 
        WHERE username = %s OR email = %s
        """
        existing_user = execute_read_query(
            connection, query=check_query, params=(username, email))

        if existing_user:
            logger.info(
                f"Registration attempt with existing credentials: {username}/{email}")
            return jsonify({
                'message': get_message('user_exists', lang),
                'field': 'username' if existing_user[0]['username'] == username else 'email'
            }), 409

        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        logger.info(f"Generated password hash for {username}: {password_hash}")

        query = """
        INSERT INTO users (username, email, password_hash) 
        VALUES (%s, %s, %s)
        """
        execute_query(connection, query, (username, email, password_hash))

        logger.info(f"New user registered: {username}")
        return jsonify({
            'message': get_message('user_created', lang),
            'user': {
                'username': username,
                'email': email
            }
        }), 201

    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'message': get_message('register_failed', lang)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        if not data or 'username' not in data or 'password' not in data:
            abort(400, description=get_message('missing_fields', lang))

        username = data['username'].strip()
        password = data['password']
        logger.info(f"Login attempt for username: {username}")

        connection = create_connection()
        query = """
        SELECT id, username, email, password_hash 
        FROM users 
        WHERE username = %s
        """
        user = execute_read_query(connection, query, (username,))

        if not user:
            logger.warning(f"User not found: {username}")
            return jsonify({'message': get_message('invalid_credentials', lang)}), 401

        stored_hash = user[0]['password_hash']
        logger.info(f"Stored hash for {username}: {stored_hash}")
        is_valid = check_password_hash(stored_hash, password)
        logger.info(f"Password check result for {username}: {is_valid}")

        if not is_valid:
            logger.warning(f"Invalid password for username: {username}")
            return jsonify({'message': get_message('invalid_credentials', lang)}), 401

        token = jwt.encode({
            'user_id': user[0]['id'],
            'username': user[0]['username'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'])

        logger.info(f"Successful login for user: {username}")
        return jsonify({
            'token': token,
            'user': {
                'id': user[0]['id'],
                'username': user[0]['username'],
                'email': user[0]['email']
            }
        })

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'message': get_message('login_failed', lang)}), 500

@app.route('/api/flights', methods=['GET'])
def get_flights():
    try:
        connection = create_connection()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        departure = request.args.get('departure')
        arrival = request.args.get('arrival')
        date = request.args.get('date')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')

        query = """
        SELECT 
            id, airline, flight_number,
            departure_city, arrival_city,
            departure_time, arrival_time,
            price, available_seats
        FROM flights 
        WHERE available_seats > 0
        """
        params = []

        if departure:
            query += " AND departure_city LIKE %s"
            params.append(f"%{departure}%")
        if arrival:
            query += " AND arrival_city LIKE %s"
            params.append(f"%{arrival}%")
        if date:
            query += " AND DATE(departure_time) = %s"
            params.append(date)
        if min_price:
            query += " AND price >= %s"
            params.append(float(min_price))
        if max_price:
            query += " AND price <= %s"
            params.append(float(max_price))

        query += " ORDER BY departure_time ASC"

        flights = execute_read_query(
            connection, query, tuple(params) if params else None)

        formatted_flights = []
        for flight in flights:
            formatted_flight = flight.copy()
            formatted_flight['departure_time'] = flight['departure_time'].isoformat()
            formatted_flight['arrival_time'] = flight['arrival_time'].isoformat()
            formatted_flights.append(formatted_flight)

        return jsonify(formatted_flights)

    except Exception as e:
        logger.error(f"Flight search error: {str(e)}")
        return jsonify({'message': get_message('flight_search_failed', lang)}), 500

@app.route('/api/bookings', methods=['POST'])
@token_required
def book_flight():
    try:
        data = request.get_json()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        if not data or 'flight_id' not in data:
            abort(400, description=get_message('flight_id_required', lang))

        flight_id = data['flight_id']
        user_id = request.user_data['user_id']

        connection = create_connection()

        connection.start_transaction()

        try:
            query = """
            SELECT available_seats 
            FROM flights 
            WHERE id = %s 
            FOR UPDATE
            """
            flight = execute_read_query(connection, query, (flight_id,))

            if not flight or flight[0]['available_seats'] <= 0:
                connection.rollback()
                return jsonify({'message': get_message('no_seats', lang)}), 400

            booking_query = """
            INSERT INTO bookings (user_id, flight_id, status) 
            VALUES (%s, %s, 'confirmed')
            """
            execute_query(connection, booking_query, (user_id, flight_id))

            update_query = """
            UPDATE flights 
            SET available_seats = available_seats - 1 
            WHERE id = %s
            """
            execute_query(connection, update_query, (flight_id,))

            connection.commit()

            logger.info(
                f"Successful booking - User: {user_id}, Flight: {flight_id}")
            return jsonify({
                'message': get_message('booking_success', lang),
                'booking': {
                    'user_id': user_id,
                    'flight_id': flight_id,
                    'status': 'confirmed'
                }
            }), 201

        except Exception as e:
            connection.rollback()
            raise e

    except Exception as e:
        logger.error(f"Booking error: {str(e)}")
        return jsonify({'message': get_message('booking_failed', lang)}), 500

@app.route('/api/booking-stats', methods=['GET'])
@cross_origin(origin='http://localhost:3000')
def booking_stats():
    connection = None
    try:
        connection = create_connection()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        query = """
        SELECT 
            f.departure_city, 
            COUNT(b.id) as bookings,
            AVG(f.price) as avg_price,
            SUM(f.price) as total_revenue
        FROM flights f
        LEFT JOIN bookings b ON f.id = b.flight_id
        GROUP BY f.departure_city
        """

        stats = execute_read_query(connection, query)
        df = pd.DataFrame(stats, columns=['departure_city', 'bookings', 'avg_price', 'total_revenue'])

        df['avg_price'] = pd.to_numeric(df['avg_price'], errors='coerce').fillna(0)
        df['bookings'] = pd.to_numeric(df['bookings'], errors='coerce').fillna(0)
        df['total_revenue'] = pd.to_numeric(df['total_revenue'], errors='coerce').fillna(0)

        if df['bookings'].sum() == 0:
            return jsonify({'message': get_message('no_data_found', lang, 'No data found')}), 404

        plt.style.use('ggplot')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

        df.plot.bar(x='departure_city', y='bookings', ax=ax1, color='#037dd6')
        ax1.set_title(get_message('bookings_by_departure', lang, 'Bookings by Departure City'))
        ax1.set_xlabel('')
        ax1.set_ylabel(get_message('num_bookings', lang, 'Number of Bookings'))
        ax1.tick_params(axis='x', rotation=45)

        df.plot.bar(x='departure_city', y='total_revenue', ax=ax2, color='#28a745')
        ax2.set_title(get_message('revenue_by_departure', lang, 'Revenue by Departure City'))
        ax2.set_xlabel(get_message('departure_city', lang, 'Departure City'))
        ax2.set_ylabel(get_message('total_revenue', lang, 'Total Revenue ($)'))
        ax2.tick_params(axis='x', rotation=45)

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        return jsonify({
            'image': image_base64,
            'stats': stats
        })

    except Exception as e:
        lang = 'en'
        logger.error(f"Booking stats error: {str(e)}")
        return jsonify({'message': get_message('stats_failed', lang, 'Error fetching stats')}), 500

    finally:
        if connection:
            connection.close()


@app.route('/api/my-bookings', methods=['GET'])
@token_required
def get_user_bookings():
    try:
        user_id = request.user_data['user_id']
        connection = create_connection()
        lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()

        query = """
        SELECT 
            b.id as booking_id,
            b.booking_date,
            b.status,
            f.airline,
            f.flight_number,
            f.departure_city,
            f.arrival_city,
            f.departure_time,
            f.arrival_time,
            f.price
        FROM bookings b
        JOIN flights f ON b.flight_id = f.id
        WHERE b.user_id = %s
        ORDER BY b.booking_date DESC
        """
        bookings = execute_read_query(connection, query, (user_id,))

        for booking in bookings:
            booking['booking_date'] = booking['booking_date'].isoformat()
            booking['departure_time'] = booking['departure_time'].isoformat()
            booking['arrival_time'] = booking['arrival_time'].isoformat()

        return jsonify(bookings)

    except Exception as e:
        logger.error(f"Get user bookings error: {str(e)}")
        return jsonify({'message': get_message('bookings_failed', lang)}), 500

@app.errorhandler(404)
def not_found(error):
    lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()
    return jsonify({'message': get_message('not_found', lang)}), 404

@app.errorhandler(500)
def internal_error(error):
    lang = request.headers.get('Accept-Language', 'en').split(',')[0].strip().lower()
    logger.critical(f"Internal server error: {str(error)}")
    return jsonify({'message': get_message('server_error', lang)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)