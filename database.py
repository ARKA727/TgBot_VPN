# database.py
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import config

class Database:
    def __init__(self, db_name=config.DATABASE_NAME):
        self.db_name = db_name
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language TEXT DEFAULT 'ru',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица подписок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    server_id TEXT,
                    config_data TEXT,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            self._migrate_subscriptions(cursor)
            
            # Таблица платежей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    currency TEXT,
                    payment_id TEXT,
                    plan_name TEXT,
                    server_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.commit()

    @staticmethod
    def _migrate_subscriptions(cursor):
        cursor.execute("PRAGMA table_info(subscriptions)")
        names = {row[1] for row in cursor.fetchall()}
        if "xui_client_email" not in names:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN xui_client_email TEXT")
        if "xui_client_uuid" not in names:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN xui_client_uuid TEXT")
        if "xui_sub_id" not in names:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN xui_sub_id TEXT")
        if "xui_inbound_id" not in names:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN xui_inbound_id INTEGER")

    def add_user(self, user_id, username, first_name, last_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()

    def get_user_subscriptions(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM subscriptions 
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
            ''', (user_id,))
            return cursor.fetchall()

    def get_active_xui_subscription(self, user_id, server_id):
        """Последняя активная подписка с клиентом 3x-ui на этом сервере (для продления)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM subscriptions
                WHERE user_id = ? AND LOWER(server_id) = LOWER(?)
                  AND is_active = 1
                  AND end_date > CURRENT_TIMESTAMP
                  AND xui_client_uuid IS NOT NULL AND TRIM(xui_client_uuid) != ''
                ORDER BY end_date DESC
                LIMIT 1
                """,
                (user_id, server_id),
            )
            return cursor.fetchone()

    def update_subscription_renewal(self, subscription_id, config_data, end_date):
        """Обновить текст и дату окончания после продления в панели."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE subscriptions
                SET config_data = ?, end_date = ?
                WHERE id = ?
                """,
                (config_data, end_date, subscription_id),
            )
            conn.commit()

    def add_subscription(
        self,
        user_id,
        server_id,
        config_data,
        duration_days,
        *,
        xui_client_email=None,
        xui_client_uuid=None,
        xui_sub_id=None,
        xui_inbound_id=None,
    ):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            end_date = datetime.now() + timedelta(days=duration_days)
            cursor.execute(
                """
                INSERT INTO subscriptions (
                    user_id, server_id, config_data, end_date,
                    xui_client_email, xui_client_uuid, xui_sub_id, xui_inbound_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    server_id,
                    config_data,
                    end_date,
                    xui_client_email,
                    xui_client_uuid,
                    xui_sub_id,
                    xui_inbound_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def add_payment(self, user_id, amount, currency, payment_id, plan_name, server_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO payments (user_id, amount, currency, payment_id, plan_name, server_id, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            ''', (user_id, amount, currency, payment_id, plan_name, server_id))
            conn.commit()
            return cursor.lastrowid

    def update_payment_status(self, payment_id, status):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments SET status = ? WHERE payment_id = ?
            ''', (status, payment_id))
            conn.commit()

def init_db():
    """Функция для инициализации БД"""
    db = Database()
    return db