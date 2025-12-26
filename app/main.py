from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import os
import logging
import sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def clean_database_url(database_url):
    """
    Clean DATABASE_URL by removing invalid psycopg2 connection parameters.
    psycopg2 doesn't recognize parameters like read_timeout, write_timeout, etc.
    """
    if not database_url or 'postgresql' not in database_url:
        return database_url

    try:
        # Parse the URL
        parsed = urlparse(database_url)

        # Get query parameters
        query_params = parse_qs(parsed.query)

        # Valid psycopg2 parameters (connection-level)
        valid_params = {
            'connect_timeout', 'sslmode', 'sslrootcert', 'sslcert', 'sslkey',
            'application_name', 'client_encoding', 'options', 'fallback_application_name',
            'keepalives', 'keepalives_idle', 'keepalives_interval', 'keepalives_count',
            'tcp_user_timeout', 'sslcrl', 'requiressl', 'sslcompression'
        }
        
        # Filter out invalid parameters
        cleaned_params = {k: v for k, v in query_params.items() if k in valid_params}
        
        # DO NOT force SSL mode - let connection strategies handle SSL configuration
        # The create_engine_with_fallback function will set appropriate SSL modes
        # Forcing sslmode=require here breaks the no-SSL-first strategy

        # Reconstruct query string
        cleaned_query = urlencode(cleaned_params, doseq=True) if cleaned_params else ''

        # Reconstruct URL
        cleaned_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            cleaned_query,
            parsed.fragment
        ))

        # Log what was removed
        removed_params = set(query_params.keys()) - set(cleaned_params.keys())
        if removed_params:
            logger.info(f"Removed invalid psycopg2 parameters from DATABASE_URL: {removed_params}")

        return cleaned_url

    except Exception as e:
        logger.warning(f"Failed to clean DATABASE_URL: {e}. Using original URL.")
        return database_url

# Apply Render SSL fixes if on Render
if os.getenv('RENDER'):
    # SQLite autonomous mode - no SSL configuration needed
    logger.info("🔧 SQLite autonomous mode - no SSL configuration needed")
    logger.info("✅ Using persistent SQLite database (no external dependencies)")

# Environment validation
is_render = 'RENDER_EXTERNAL_URL' in os.environ
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL and not is_render:
    logger.error("DATABASE_URL environment variable is required")
    raise ValueError("DATABASE_URL environment variable is required")

# Clean DATABASE_URL to remove invalid psycopg2 parameters (skip on Render for SSL flexibility)
if not os.getenv('RENDER'):
    DATABASE_URL = clean_database_url(DATABASE_URL)
else:
    logger.info("🔧 Skipping URL cleaning on Render to preserve SSL strategy flexibility")

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is required")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Database configuration - SQLite persistente per autonomia completa
PERSISTENT_DATA_DIR = "/opt/render/project/src/data"
DATABASE_PATH = os.path.join(PERSISTENT_DATA_DIR, "erixcast.db")
PING_DATABASE_PATH = os.path.join(PERSISTENT_DATA_DIR, "ping_logs.db")

# Assicura che la directory dati esista
os.makedirs(PERSISTENT_DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(PERSISTENT_DATA_DIR, "backups"), exist_ok=True)

# Forza uso SQLite persistente per autonomia completa
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
PING_DATABASE_URL = f"sqlite:///{PING_DATABASE_PATH}"
logger.info(f"🔧 Using persistent SQLite database: {DATABASE_PATH}")
logger.info(f"📊 Using separate ping database: {PING_DATABASE_PATH}")

# SQLite pool configuration ottimizzata per concorrenza
pool_size = 5  # Increased for concurrent access
max_overflow = 10  # Allow overflow connections

def create_sqlite_engine(database_url):
    """Create SQLite engine for autonomous bot operation"""
    
    logger.info("🔧 Creating persistent SQLite database for autonomous operation...")
    
    # Verifica che il file database sia accessibile
    db_path = database_url.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    
    if not os.path.exists(db_dir):
        logger.info(f"📁 Creating database directory: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    
    # Crea engine SQLite ottimizzato per concorrenza
    engine = create_engine(
        database_url,
        pool_size=5,  # Increased from 1 to handle concurrent requests
        max_overflow=10,  # Allow overflow connections
        pool_timeout=60,  # Increased timeout to prevent timeouts
        pool_recycle=3600,  # 1 ora
        pool_pre_ping=False,
        echo=False,
        # Ottimizzazioni SQLite per accesso concorrente
        connect_args={
            "check_same_thread": False,  # Permette accesso multi-thread
            "timeout": 60,  # Increased timeout per lock
        }
    )
    
    # Test connessione SQLite
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            # Test base
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
            
            # Ottimizzazioni SQLite per performance
            conn.execute(text("PRAGMA journal_mode=WAL"))  # Write-Ahead Logging
            conn.execute(text("PRAGMA synchronous=NORMAL"))  # Bilanciamento sicurezza/performance
            conn.execute(text("PRAGMA cache_size=10000"))  # Cache 10MB
            conn.execute(text("PRAGMA temp_store=MEMORY"))  # Temp tables in memoria
            conn.execute(text("PRAGMA mmap_size=268435456"))  # Memory mapping 256MB
            
            logger.info("✅ SQLite database connection successful with optimizations")
            logger.info(f"📊 Database file: {db_path}")
            
            # Verifica dimensione database
            if os.path.exists(db_path):
                size_mb = os.path.getsize(db_path) / 1024 / 1024
                logger.info(f"📈 Database size: {size_mb:.2f} MB")
            
            return engine
            
    except Exception as e:
        logger.error(f"❌ SQLite connection failed: {e}")
        raise

def create_engine_with_fallback(database_url, pool_size, max_overflow):
    """Create engine - now always uses persistent SQLite for autonomy"""
    
    # SOLUZIONE AUTONOMA: Usa sempre SQLite persistente
    logger.info("🚀 Creating autonomous SQLite database (no external dependencies)")
    
    return create_sqlite_engine(database_url)
    


# Create engine with fallback strategies (non-blocking approach)
engine = None
SessionLocal = None
ping_engine = None
PingSessionLocal = None

def create_ping_engine(database_url):
    """Create separate SQLite engine for ping logging to avoid blocking main database"""
    logger.info("📊 Creating separate ping database engine...")

    db_path = database_url.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)

    if not os.path.exists(db_dir):
        logger.info(f"📁 Creating ping database directory: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)

    # Optimized SQLite engine for high-frequency ping logging
    ping_engine = create_engine(
        database_url,
        pool_size=1,  # Single connection for ping logs
        max_overflow=0,  # No overflow
        pool_timeout=5,  # Shorter timeout
        pool_recycle=3600,
        pool_pre_ping=False,
        echo=False,
        connect_args={
            "check_same_thread": False,
            "timeout": 5,  # Shorter timeout for ping operations
        }
    )

    # Test ping database connection
    try:
        with ping_engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT 1"))
            result.fetchone()

            # Performance optimizations for ping logging
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA cache_size=1000"))  # Smaller cache for ping logs
            conn.execute(text("PRAGMA temp_store=MEMORY"))

            logger.info("✅ Ping database connection successful")
            return ping_engine

    except Exception as e:
        logger.error(f"❌ Ping database connection failed: {e}")
        raise

def initialize_database():
    """Initialize database connection with graceful failure handling"""
    global engine, SessionLocal, ping_engine, PingSessionLocal

    try:
        logger.info("🔄 Initializing database connections...")
        engine = create_engine_with_fallback(DATABASE_URL, pool_size, max_overflow)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Initialize separate ping database
        ping_engine = create_ping_engine(PING_DATABASE_URL)
        PingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ping_engine)

        logger.info("✅ Database connections initialized successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        logger.warning("⚠️ Starting without database connection - will retry later")

        # Set SessionLocals to None when database unavailable
        SessionLocal = None
        PingSessionLocal = None
        return False

# Try to initialize database, but don't fail if it doesn't work
database_available = initialize_database()

# Import models directly (with --chdir, the root directory is in Python path)
from .models import UptimePing, create_tables
from . import models
if SessionLocal:
    models.SessionLocal = SessionLocal

# Database retry mechanism
def retry_database_connection():
    """Retry database connection periodically"""
    global engine, SessionLocal, ping_engine, PingSessionLocal, database_available

    if database_available:
        return True  # Already connected

    try:
        logger.info("🔄 Retrying database connections...")
        engine = create_engine_with_fallback(DATABASE_URL, pool_size, max_overflow)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Retry ping database connection
        ping_engine = create_ping_engine(PING_DATABASE_URL)
        PingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ping_engine)

        if models:
            models.SessionLocal = SessionLocal

        # Test the main connection
        if test_database_connection():
            database_available = True
            logger.info("✅ Database reconnection successful!")

            # Try to create tables
            tables_created = create_tables_with_retry(engine)
            if tables_created:
                logger.info("✅ Database tables created after reconnection")

            # Create ping tables
            ping_tables_created = create_ping_tables_with_retry(ping_engine)
            if ping_tables_created:
                logger.info("✅ Ping database tables created after reconnection")

            return True
        else:
            raise Exception("Connection test failed after engine creation")

    except Exception as e:
        logger.warning(f"⚠️ Database reconnection failed: {e}")
        return False

def create_ping_tables_with_retry(engine, max_retries=3):
    """Create ping tables with retry logic"""
    from .models import UptimePing, Base
    for attempt in range(max_retries):
        try:
            # Create only UptimePing table in ping database
            UptimePing.__table__.create(bind=engine, checkfirst=True)
            logger.info("✅ Ping database tables created successfully")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt + 1}/{max_retries} to create ping tables failed: {e}")
            if attempt == max_retries - 1:
                logger.error("❌ Failed to create ping tables after all retries")
                return False
            import time
            time.sleep(1)
    return False

# Create all tables using the centralized function with retry logic
def create_tables_with_retry(engine, max_retries=5):
    """Create tables with retry logic for connection issues"""
    for attempt in range(max_retries):
        try:
            create_tables(engine)
            logger.info("✅ Database tables created successfully")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt + 1}/{max_retries} to create tables failed: {e}")
            if attempt == max_retries - 1:
                logger.error("❌ Failed to create tables after all retries - continuing without table creation")
                return False
            import time
            # Exponential backoff with jitter
            sleep_time = (2 ** attempt) + (attempt * 0.5)
            logger.info(f"Waiting {sleep_time:.1f}s before retry...")
            time.sleep(sleep_time)
    
    return False

# Try to create tables only if database is available
# Sistema di backup automatico per SQLite
def backup_sqlite_database():
    """Backup automatico del database SQLite"""
    try:
        import shutil
        from datetime import datetime

        if not os.path.exists(DATABASE_PATH):
            return False

        backup_dir = os.path.join(PERSISTENT_DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"erixcast_backup_{timestamp}.db")

        shutil.copy2(DATABASE_PATH, backup_path)

        # Mantieni solo gli ultimi 10 backup per risparmiare spazio
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("erixcast_backup_")])
        while len(backups) > 10:
            old_backup = os.path.join(backup_dir, backups.pop(0))
            os.remove(old_backup)

        size_mb = os.path.getsize(backup_path) / 1024 / 1024
        logger.info(f"✅ Database backup created: {backup_path} ({size_mb:.2f} MB)")
        return True

    except Exception as e:
        logger.error(f"❌ Database backup failed: {e}")
        return False

def backup_ping_database():
    """Backup automatico del database ping SQLite"""
    try:
        import shutil
        from datetime import datetime

        if not os.path.exists(PING_DATABASE_PATH):
            return False

        backup_dir = os.path.join(PERSISTENT_DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"ping_backup_{timestamp}.db")

        shutil.copy2(PING_DATABASE_PATH, backup_path)

        # Mantieni solo gli ultimi 5 backup per ping logs
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("ping_backup_")])
        while len(backups) > 5:
            old_backup = os.path.join(backup_dir, backups.pop(0))
            os.remove(old_backup)

        size_mb = os.path.getsize(backup_path) / 1024 / 1024
        logger.info(f"✅ Ping database backup created: {backup_path} ({size_mb:.2f} MB)")
        return True

    except Exception as e:
        logger.error(f"❌ Ping database backup failed: {e}")
        return False

def get_database_stats():
    """Statistiche database per monitoraggio"""
    try:
        stats = {}
        
        if os.path.exists(DATABASE_PATH):
            stats["file_size_mb"] = round(os.path.getsize(DATABASE_PATH) / 1024 / 1024, 2)
            stats["file_exists"] = True
            
            # Conta backup disponibili
            backup_dir = os.path.join(PERSISTENT_DATA_DIR, "backups")
            if os.path.exists(backup_dir):
                backups = [f for f in os.listdir(backup_dir) if f.startswith("erixcast_backup_")]
                stats["backup_count"] = len(backups)
                if backups:
                    latest_backup = sorted(backups)[-1]
                    stats["latest_backup"] = latest_backup
            else:
                stats["backup_count"] = 0
        else:
            stats["file_exists"] = False
            stats["file_size_mb"] = 0
            stats["backup_count"] = 0
        
        return stats
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return {"error": str(e)}

# Crea tabelle e backup iniziale
if database_available and engine and ping_engine:
    tables_created = create_tables_with_retry(engine)
    if not tables_created:
        logger.warning("⚠️ Main tables creation failed - bot will attempt to create them on first use")
    else:
        # Crea backup iniziale dopo creazione tabelle
        backup_sqlite_database()

    # Crea tabelle ping
    ping_tables_created = create_ping_tables_with_retry(ping_engine)
    if not ping_tables_created:
        logger.warning("⚠️ Ping tables creation failed - ping logging disabled")
    else:
        # Crea backup iniziale del database ping
        backup_ping_database()

    # Informazioni database SQLite persistente
    db_stats = get_database_stats()
    logger.info(f"💾 Persistent SQLite databases ready:")
    logger.info(f"   📁 Main DB: {DATABASE_PATH}")
    logger.info(f"   📊 Main DB Size: {db_stats.get('file_size_mb', 0)} MB")
    logger.info(f"   📁 Ping DB: {PING_DATABASE_PATH}")
    logger.info(f"   🔄 Backups: {db_stats.get('backup_count', 0)} available")
    logger.info(f"   ✅ Autonomous operation: Data persists across all redeploys")
    logger.info(f"   📊 Separate ping database: Prevents health check blocking")
else:
    logger.warning("⚠️ Skipping table creation - databases not available")

# Test database connection with SSL
def test_database_connection():
    """Test database connection with proper error handling"""
    # Check if database is available first
    if not database_available or not SessionLocal or not callable(SessionLocal):
        logger.warning("⚠️ Database not available for connection test")
        return False
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            session = SessionLocal()
            from sqlalchemy import text
            # Use SQLite compatible query instead of PostgreSQL version()
            result = session.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            test_result = row[0] if row else None
            session.close()
            if test_result == 1:
                logger.info("Database connection successful - SQLite database operational")
                return True
            else:
                raise Exception("Unexpected test result")
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt == max_retries - 1:
                logger.error("Database connection failed after all retries")
                return False
            import time
            time.sleep(1 + attempt)  # Linear backoff for SQLite
    return False

# Test connection at startup only if database was initialized
if database_available:
    if not test_database_connection():
        logger.error("Critical: Database connection test failed")
        database_available = False
else:
    logger.warning("⚠️ Skipping database connection test - database not initialized")

# Flask app for health checks (always create for Gunicorn compatibility)
try:
    from flask import Flask, jsonify, request
    app = Flask(__name__)
    logger.info("Flask app created for health checks")
except ImportError:
    logger.warning("Flask not available, health check endpoints disabled")
    app = None

# Health check endpoint for Render (only if Flask is available)
if app:
    @app.route('/health')
    def health_check():
        """Enhanced health check with SSL connection recovery"""
        import time
        start_time = time.time()
        logger.info("🏥 Health check started")

        try:
            # Test database connection with multiple strategies
            session = None
            db_status = "disconnected"
            connection_strategy = "unknown"
            db_operation_time = 0

            # Check if database is available
            session = None
            try:
                if not database_available or not SessionLocal:
                    logger.warning("🏥 Health check: database not available, attempting reconnection")
                    # Try to reconnect
                    if retry_database_connection():
                        db_status = "reconnected"
                        connection_strategy = "retry_success"
                    else:
                        db_status = "unavailable"
                        connection_strategy = "no_connection"
                else:
                    # Try primary connection
                    logger.info("🏥 Health check: testing database connection")
                    db_op_start = time.time()
                    session = SessionLocal()
                    from sqlalchemy import text
                    result = session.execute(text("SELECT 1"))
                    result.fetchone()
                    session.commit()
                    db_operation_time = time.time() - db_op_start
                    logger.info(f"🏥 Health check: database operation took {db_operation_time:.3f}s")
                    db_status = "connected"
                    connection_strategy = "primary"
            except Exception as db_e:
                logger.warning(f"🏥 Health check: Primary database connection failed: {db_e}")
                db_operation_time = time.time() - start_time
                logger.warning(f"🏥 Health check: database operation failed after {db_operation_time:.3f}s")

                # Try to reconnect
                if retry_database_connection():
                    db_status = "reconnected"
                    connection_strategy = "retry_success"
                else:
                    db_status = f"failed: {str(db_e)[:50]}"
                    connection_strategy = "failed"
            finally:
                if session:
                    try:
                        session.close()
                    except Exception:
                        pass

            # Test bot connectivity (quick test)
            try:
                # Check bot thread status
                if bot_thread and bot_thread.is_alive():
                    bot_status_value = bot_status
                else:
                    bot_status_value = "bot_thread_dead"
            except Exception as bot_e:
                logger.warning(f"Bot status check failed: {bot_e}")
                bot_status_value = "bot_check_failed"

            # Get resource status
            resource_status = {}
            resource_check_time = 0
            try:
                logger.info("🏥 Health check: checking system resources")
                resource_start = time.time()
                # Use psutil directly instead of importing bot module
                import psutil
                process = psutil.Process()
                resource_status = {
                    'memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
                    'cpu_percent': psutil.cpu_percent(interval=0.1)
                }
                resource_check_time = time.time() - resource_start
                logger.info(f"🏥 Health check: resource check took {resource_check_time:.3f}s")
            except Exception as res_e:
                logger.warning(f"🏥 Health check: resource check failed: {res_e}")
                pass

            # Determine overall health status
            is_healthy = db_status in ['connected', 'connected_fallback', 'reconnected']
            is_degraded = db_status in ['unavailable', 'failed']

            if is_healthy:
                status_code = 200
            elif is_degraded:
                status_code = 503  # Service unavailable but trying to recover
            else:
                status_code = 503

            from datetime import datetime, timezone

            # Determine service status
            if is_healthy:
                service_status = 'healthy'
            elif is_degraded:
                service_status = 'degraded'
            else:
                service_status = 'unhealthy'

            # Get database statistics
            db_stats = {}
            db_stats_time = 0
            try:
                logger.info("🏥 Health check: getting database stats")
                stats_start = time.time()
                db_stats = get_database_stats()
                db_stats_time = time.time() - stats_start
                logger.info(f"🏥 Health check: database stats took {db_stats_time:.3f}s")
            except Exception as stats_e:
                logger.warning(f"🏥 Health check: database stats failed: {stats_e}")
                db_stats = {"error": str(stats_e)}
            
            # Fix timezone issue - use consistent UTC datetime
            current_time = datetime.now(timezone.utc)
            start_of_day = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            uptime_seconds = int((current_time - start_of_day).total_seconds())

            total_time = time.time() - start_time
            logger.info(f"🏥 Health check completed in {total_time:.3f}s (DB: {db_operation_time:.3f}s, Resources: {resource_check_time:.3f}s, Stats: {db_stats_time:.3f}s)")

            return jsonify({
                'status': service_status,
                'timestamp': current_time.isoformat(),
                'database': {
                    'status': db_status,
                    'type': 'sqlite_persistent',
                    'connection_strategy': connection_strategy,
                    'available': database_available,
                    'file_size_mb': db_stats.get('file_size_mb', 0),
                    'backup_count': db_stats.get('backup_count', 0),
                    'latest_backup': db_stats.get('latest_backup', 'none'),
                    'path': DATABASE_PATH if database_available else 'unavailable'
                },
                'bot_status': bot_status_value,
                'uptime_seconds': uptime_seconds,
                'resources': resource_status,
                'performance': {
                    'total_time_seconds': round(total_time, 3),
                    'db_operation_time_seconds': round(db_operation_time, 3),
                    'resource_check_time_seconds': round(resource_check_time, 3),
                    'db_stats_time_seconds': round(db_stats_time, 3)
                },
                'autonomous_operation': {
                    'enabled': True,
                    'persistent_storage': True,
                    'external_dependencies': False,
                    'backup_system': 'automatic'
                }
            }), status_code
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            from datetime import datetime, timezone
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 500

    @app.route('/ping')
    def ping():
        """Lightweight ping endpoint to prevent Render sleep"""
        logger.info("🏓 Ping endpoint called")
        from datetime import datetime, timezone
        response = jsonify({
            'status': 'pong',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        logger.info("🏓 Ping endpoint returning pong")
        return response, 200

    @app.route('/status')
    def status():
        """Detailed status endpoint for monitoring"""
        import psutil
        import os

        try:
            import psutil
            from datetime import datetime, timezone
            memory = psutil.virtual_memory()
            process = psutil.Process(os.getpid())

            return jsonify({
                'status': 'operational',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'memory_usage_mb': round(memory.used / 1024 / 1024, 2),
                'memory_percent': memory.percent,
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'process_memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
                'uptime_seconds': int((datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat('2025-01-01T00:00:00')).total_seconds()) % 86400
            }), 200
        except Exception as e:
            from datetime import datetime, timezone
            return jsonify({
                'status': 'status_check_failed',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 500

    # Webhook endpoint for Telegram (more efficient than polling)
    @app.route(f'/webhook/{TELEGRAM_BOT_TOKEN.split(":")[0]}', methods=['POST'])
    def telegram_webhook():
        """Telegram webhook endpoint - more efficient than polling"""
        try:
            logger.info("📨 WEBHOOK RECEIVED - STARTING PROCESSING")
            # Import here to avoid circular imports
            import asyncio
            from telegram import Update

            # Get application from bot module and ensure it's initialized
            from . import bot
            logger.info(f"🔍 Bot module imported, has application attr: {hasattr(bot, 'application')}")
            logger.info(f"🔍 Bot application current state: {bot.application}")
            logger.info(f"🔍 Bot status: {bot_status}")
            logger.info(f"🔍 Bot thread alive: {bot_thread and bot_thread.is_alive() if 'bot_thread' in globals() else False}")
            logger.info(f"🔍 Global bot_status: {globals().get('bot_status', 'not_set')}")
            logger.info(f"🔍 Bot application type: {type(bot.application) if bot.application else 'None'}")
            logger.info(f"🔍 Bot application bot: {bot.application.bot if bot.application and hasattr(bot.application, 'bot') else 'No bot attr'}")
            logger.info(f"🔍 Bot application handlers: {len(bot.application.handlers) if bot.application and hasattr(bot.application, 'handlers') else 'No handlers attr'}")
            logger.info("🔍 DEBUG: Checking if application is properly initialized...")
            logger.info(f"🔍 DEBUG: hasattr(bot, 'application'): {hasattr(bot, 'application')}")
            if hasattr(bot, 'application'):
                logger.info(f"🔍 DEBUG: bot.application is not None: {bot.application is not None}")
                if bot.application:
                    logger.info(f"🔍 DEBUG: hasattr(bot.application, 'handlers'): {hasattr(bot.application, 'handlers')}")
                    if hasattr(bot.application, 'handlers'):
                        logger.info(f"🔍 DEBUG: len(bot.application.handlers): {len(bot.application.handlers)}")
                        logger.info(f"🔍 DEBUG: bot.application.handlers type: {type(bot.application.handlers)}")
            logger.info("🔍 DEBUG: Application check completed")

            # Check if bot thread is running
            bot_thread_alive = bot_thread and bot_thread.is_alive() if 'bot_thread' in globals() else False
            logger.info(f"🔍 Bot thread alive: {bot_thread_alive}")

            # Check if application is ready
            app_ready = (hasattr(bot, 'application') and bot.application is not None and
                        hasattr(bot.application, 'handlers') and bot.application.handlers)
            logger.info(f"🔍 Application ready: {app_ready}")

            if not app_ready:
                logger.warning("⚠️ Bot application not ready, attempting recovery...")

                # Try to initialize application
                if hasattr(bot, 'initialize_application'):
                    logger.info("🔄 Attempting to initialize application in webhook handler...")
                    init_result = bot.initialize_application()
                    logger.info(f"🔄 Initialization result: {init_result}")

                    if init_result and hasattr(bot, 'application') and bot.application:
                        logger.info("✅ Application initialized successfully in webhook handler")
                        app_ready = True
                    else:
                        logger.error("❌ Application initialization failed in webhook handler")
                        return jsonify({'status': 'error', 'message': 'Bot application not ready'}), 503

            if app_ready:
                logger.info("✅ Bot application is available for processing")

                # Process webhook update
                try:
                    update_data = request.get_json()
                    logger.info(f"📄 Update data received: {update_data is not None}")

                    if not update_data:
                        logger.warning("⚠️ No update data in webhook request")
                        return jsonify({'status': 'error', 'message': 'No update data'}), 400

                    message_text = update_data.get('message', {}).get('text', 'N/A')
                    logger.info(f"📝 Update type: {message_text[:50]}...")
                    logger.info(f"🔍 Full update data keys: {list(update_data.keys())}")

                    # Check if this is a command
                    if 'message' in update_data and 'text' in update_data['message']:
                        text = update_data['message']['text']
                        if text.startswith('/'):
                            logger.info(f"🎯 COMMAND DETECTED: {text}")
                        else:
                            logger.info(f"💬 REGULAR MESSAGE: {text[:50]}...")

                    # Convert to Update object and process
                    try:
                        update = Update.de_json(update_data, bot.application.bot)
                        if not update:
                            logger.warning("⚠️ Failed to create Update object from data")
                            return jsonify({'status': 'error', 'message': 'Invalid update format'}), 400

                        logger.info("✅ Update object created successfully")
                        logger.info(f"📝 Update type: {type(update).__name__}")
                        logger.info(f"📝 Update has message: {hasattr(update, 'message') and update.message is not None}")
                        if hasattr(update, 'message') and update.message:
                            logger.info(f"📝 Message text: '{update.message.text}'")
                            logger.info(f"📝 Message chat ID: {update.message.chat.id}")
                            logger.info(f"📝 Message from user: {update.message.from_user.id if update.message.from_user else 'None'}")
                        logger.info(f"📝 Update has callback_query: {hasattr(update, 'callback_query') and update.callback_query is not None}")
                        if hasattr(update, 'callback_query') and update.callback_query:
                            logger.info(f"📝 Callback data: '{update.callback_query.data}'")

                        # Process in background to avoid timeout
                        import threading
                        def process_update():
                            try:
                                logger.info("🔄 Processing update in background thread")
                                logger.info(f"🔄 Bot application handlers: {len(bot.application.handlers) if hasattr(bot.application, 'handlers') else 'No handlers'}")

                                # Check if there's already an event loop
                                try:
                                    loop = asyncio.get_event_loop()
                                    if loop.is_running():
                                        logger.info("🔄 Event loop already running, using it")
                                        loop.create_task(bot.application.process_update(update))
                                        logger.info("✅ Update queued to running event loop")
                                    else:
                                        logger.info("🔄 Event loop not running, creating new one")
                                        # Create new event loop for this thread
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        loop.run_until_complete(bot.application.process_update(update))
                                        loop.close()
                                        logger.info("✅ Update processed in new event loop")
                                except RuntimeError:
                                    logger.info("🔄 No event loop, creating new one")
                                    # Create new event loop for this thread
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(bot.application.process_update(update))
                                    loop.close()
                                    logger.info("✅ Update processed in fallback event loop")
                                logger.info("✅ Update processing completed")
                            except Exception as e:
                                logger.error(f"❌ Error processing webhook update: {e}")
                                import traceback
                                logger.error(f"❌ Full traceback: {traceback.format_exc()}")

                        thread = threading.Thread(target=process_update, daemon=True)
                        thread.start()
                        logger.info("✅ Background processing thread started")

                        return jsonify({'status': 'ok'}), 200

                    except Exception as update_e:
                        logger.error(f"❌ Error creating/parsing update: {update_e}")
                        return jsonify({'status': 'error', 'message': 'Update processing failed'}), 500

                except Exception as json_e:
                    logger.error(f"❌ Error parsing webhook JSON: {json_e}")
                    return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
            else:
                logger.error("❌ Bot application not available after recovery attempts")
                return jsonify({'status': 'error', 'message': 'Bot not ready'}), 503

            return jsonify({'status': 'error', 'message': 'Bot not ready or invalid update'}), 400
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}")
            import traceback
            logger.error(f"❌ Full webhook traceback: {traceback.format_exc()}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/')
    def root():
        """Root endpoint"""
        return jsonify({
            'service': 'ErixCastBot',
            'status': 'running',
            'version': '2.0.0'
        })

# Global bot status tracking
bot_status = "stopped"
bot_thread = None

# Import and run bot in a separate thread
def run_bot():
    """Run the bot in a separate thread with proper event loop"""
    global bot_status
    try:
        logger.info("🚀 Starting ErixCastBot...")
        logger.info("🔍 DEBUG: run_bot function called")
        bot_status = "starting"
        logger.info("🔍 DEBUG: bot_status set to 'starting'")

        # Crea un nuovo event loop per questo thread
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info("🔍 DEBUG: new event loop created")

        # Import bot modules directly
        logger.info("🔍 DEBUG: importing bot module...")
        from . import bot
        logger.info("🔍 DEBUG: bot module imported successfully")
        logger.info(f"🔍 DEBUG: bot has application attr: {hasattr(bot, 'application')}")
        logger.info(f"🔍 DEBUG: bot application: {bot.application}")

        bot_status = "running"
        logger.info("✅ ErixCastBot status: running")

        # Esegui il bot nel loop
        logger.info("🔍 DEBUG: calling bot.run_bot_main_loop()...")
        loop.run_until_complete(bot.run_bot_main_loop())
        logger.info("✅ Bot main loop completed")

    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
        logger.error(f"🔍 DEBUG: Exception type: {type(e)}")
        import traceback
        logger.error(f"🔍 DEBUG: Full traceback: {traceback.format_exc()}")
        bot_status = "failed"
        raise
    finally:
        bot_status = "stopped"
        logger.info("🔍 DEBUG: bot_status set to 'stopped'")
        # Chiudi il loop quando il bot termina
        try:
            loop.close()
            logger.info("🔍 DEBUG: event loop closed")
        except Exception as close_e:
            logger.error(f"Error closing event loop: {close_e}")

# For production deployment (Gunicorn) - start bot when imported
if __name__ != '__main__':
    # This block runs when imported by Gunicorn
    import threading

    # Initialize bot application synchronously before starting Flask
    logger.info("🔄 Initializing bot application synchronously...")
    bot_app_initialized = False
    try:
        from . import bot
        if hasattr(bot, 'initialize_application'):
            result = bot.initialize_application()
            logger.info(f"✅ Bot application initialization returned: {result}")
            if hasattr(bot, 'application') and bot.application:
                logger.info("✅ Bot application is ready for webhooks")
                bot_app_initialized = True
            else:
                logger.warning("⚠️ Bot application initialized but is None")
        else:
            logger.error("❌ Bot module does not have initialize_application function")
    except Exception as e:
        logger.error(f"❌ Failed to initialize bot application synchronously: {e}")
        import traceback
        logger.error(f"❌ Full initialization traceback: {traceback.format_exc()}")

    # Only start bot thread if initialization was successful
    if bot_app_initialized:
        # Avvia il bot in un thread separato
        bot_thread = threading.Thread(target=run_bot, daemon=True, name="ErixCastBot")
        bot_thread.start()
        logger.info("✅ ErixCastBot thread started successfully in production mode")
    else:
        logger.error("❌ Bot application not initialized - webhook processing will not work")
        logger.error("❌ Bot thread NOT started due to initialization failure")
        bot_status = "initialization_failed"
    
    # Avvia il watchdog per monitorare la stabilità del bot (solo se non in sviluppo)
    if os.getenv('RENDER') == 'true':
        def start_watchdog():
            """Avvia il watchdog per monitorare il bot"""
            try:
                # Aspetta che il bot si avvii
                import time
                time.sleep(180)  # Aspetta 3 minuti per evitare conflitti
                
                # Importa e avvia il watchdog
                try:
                    from bot_watchdog import BotWatchdog
                    watchdog = BotWatchdog()
                    logger.info("🐕 Starting bot watchdog...")
                    watchdog.run_monitoring()
                except ImportError:
                    logger.warning("⚠️ Watchdog module not available, skipping...")
                
            except Exception as e:
                logger.error(f"❌ Watchdog failed to start: {e}")
        
        # Avvia il watchdog in un thread separato solo su Render
        watchdog_thread = threading.Thread(target=start_watchdog, daemon=True)
        watchdog_thread.start()
        logger.info("🐕 Bot watchdog thread started (Render only)")
    else:
        logger.info("🐕 Watchdog disabled in development mode")

    # Start enhanced auto-ping system to prevent Render sleep
    if app is not None:
        # Import models for database tracking
        from .models import UptimePing

        class PingCircuitBreaker:
            """Circuit breaker for ping threads to handle failures gracefully"""
            def __init__(self, failure_threshold=3, recovery_timeout=300):  # 5 minutes
                import time
                self.failure_threshold = failure_threshold
                self.recovery_timeout = recovery_timeout
                self.failure_counts = {}
                self.last_failures = {}
                self.lock = threading.Lock()
                self.time = time

            def record_success(self, thread_name):
                with self.lock:
                    if thread_name in self.failure_counts:
                        self.failure_counts[thread_name] = 0
                        if thread_name in self.last_failures:
                            del self.last_failures[thread_name]

            def record_failure(self, thread_name):
                with self.lock:
                    if thread_name not in self.failure_counts:
                        self.failure_counts[thread_name] = 0
                    self.failure_counts[thread_name] += 1
                    self.last_failures[thread_name] = self.time.time()

            def should_restart(self, thread_name):
                with self.lock:
                    if thread_name not in self.failure_counts:
                        return False
                    if self.failure_counts[thread_name] >= self.failure_threshold:
                        # Check if recovery timeout has passed
                        if thread_name in self.last_failures:
                            if self.time.time() - self.last_failures[thread_name] > self.recovery_timeout:
                                # Reset and allow restart
                                self.failure_counts[thread_name] = 0
                                del self.last_failures[thread_name]
                                return True
                        return False
                    return False

        ping_circuit_breaker = PingCircuitBreaker()

        def create_ping_thread(interval_minutes, thread_name):
            """Create a ping thread with specified interval"""
            def ping_worker():
                import time
                import requests
                from datetime import datetime, timezone

                port = int(os.environ.get('PORT', 10000))
                render_url = f'http://localhost:{port}'
                endpoint = f"{render_url}/health"  # Use health check endpoint
                interval_seconds = interval_minutes * 60

                consecutive_failures = 0
                max_consecutive_failures = 5

                logger.info(f"🔔 Starting ping thread '{thread_name}' with {interval_minutes}min interval")

                while True:
                    start_time = time.time()
                    try:
                        # Attempt ping
                        response = requests.get(endpoint, timeout=10)
                        response_time = int((time.time() - start_time) * 1000)  # ms

                        if response.status_code == 200:
                            consecutive_failures = 0
                            ping_circuit_breaker.record_success(thread_name)

                            # Log success with comprehensive details
                            logger.info(f"✅ Ping '{thread_name}' successful - Response: {response_time}ms - Status: {response.status_code}")
                            
                            # Backup databases ogni ora (solo per ping_5min per evitare backup multipli)
                            if thread_name == "ping_5min":
                                import time
                                current_hour = int(time.time() // 3600)
                                last_backup_hour = getattr(ping_worker, 'last_backup_hour', 0)

                                if current_hour > last_backup_hour:
                                    main_backup_ok = backup_sqlite_database()
                                    ping_backup_ok = backup_ping_database()
                                    if main_backup_ok and ping_backup_ok:
                                        ping_worker.last_backup_hour = current_hour
                                        logger.info("🔄 Hourly database backups completed")
                                    elif main_backup_ok:
                                        logger.warning("⚠️ Main database backup OK, ping database backup failed")
                                    elif ping_backup_ok:
                                        logger.warning("⚠️ Ping database backup OK, main database backup failed")

                            # Record success in ping database (separate from main DB to avoid blocking)
                            if database_available and PingSessionLocal:
                                try:
                                    import time
                                    db_start = time.time()
                                    logger.info(f"📊 Ping '{thread_name}': recording success to ping database")
                                    session = PingSessionLocal()
                                    ping_record = UptimePing(
                                        thread_name=thread_name,
                                        endpoint='/health',
                                        success=True,
                                        response_time_ms=response_time
                                    )
                                    session.add(ping_record)
                                    session.commit()
                                    db_time = time.time() - db_start
                                    logger.info(f"📊 Ping '{thread_name}': ping database write took {db_time:.3f}s")
                                except Exception as db_e:
                                    logger.warning(f"⚠️ Ping '{thread_name}': Failed to record ping success in ping database: {db_e}")
                                finally:
                                    try:
                                        session.close()
                                    except Exception:
                                        pass
                        else:
                            consecutive_failures += 1
                            ping_circuit_breaker.record_failure(thread_name)

                            # Log failure with details
                            logger.warning(f"⚠️ Ping '{thread_name}' failed - Status: {response.status_code} - Response: {response_time}ms - Consecutive: {consecutive_failures}")

                            # Record failure in ping database (separate from main DB to avoid blocking)
                            if database_available and PingSessionLocal:
                                try:
                                    import time
                                    db_start = time.time()
                                    logger.info(f"📊 Ping '{thread_name}': recording failure to ping database")
                                    session = PingSessionLocal()
                                    ping_record = UptimePing(
                                        thread_name=thread_name,
                                        endpoint='/health',
                                        success=False,
                                        response_time_ms=response_time,
                                        error_message=f"HTTP {response.status_code}"
                                    )
                                    session.add(ping_record)
                                    session.commit()
                                    db_time = time.time() - db_start
                                    logger.info(f"📊 Ping '{thread_name}': ping database write took {db_time:.3f}s")
                                except Exception as db_e:
                                    logger.warning(f"⚠️ Ping '{thread_name}': Failed to record ping failure in ping database: {db_e}")
                                finally:
                                    try:
                                        session.close()
                                    except Exception:
                                        pass

                    except requests.exceptions.Timeout:
                        consecutive_failures += 1
                        ping_circuit_breaker.record_failure(thread_name)
                        response_time = int((time.time() - start_time) * 1000)

                        logger.error(f"⏰ Ping '{thread_name}' timeout - Response: {response_time}ms - Consecutive: {consecutive_failures}")

                        # Record timeout in ping database (separate from main DB to avoid blocking)
                        if database_available and PingSessionLocal:
                            try:
                                import time
                                db_start = time.time()
                                logger.info(f"📊 Ping '{thread_name}': recording timeout to ping database")
                                session = PingSessionLocal()
                                ping_record = UptimePing(
                                    thread_name=thread_name,
                                    endpoint='/health',
                                    success=False,
                                    response_time_ms=response_time,
                                    error_message="Timeout"
                                )
                                session.add(ping_record)
                                session.commit()
                                db_time = time.time() - db_start
                                logger.info(f"📊 Ping '{thread_name}': ping database write took {db_time:.3f}s")
                            except Exception as db_e:
                                logger.warning(f"⚠️ Ping '{thread_name}': Failed to record ping timeout in ping database: {db_e}")
                            finally:
                                try:
                                    session.close()
                                except Exception:
                                    pass

                    except Exception as e:
                        consecutive_failures += 1
                        ping_circuit_breaker.record_failure(thread_name)
                        response_time = int((time.time() - start_time) * 1000)

                        logger.error(f"💥 Ping '{thread_name}' error: {str(e)} - Response: {response_time}ms - Consecutive: {consecutive_failures}")

                        # Record error in ping database (separate from main DB to avoid blocking)
                        if database_available and PingSessionLocal:
                            try:
                                import time
                                db_start = time.time()
                                logger.info(f"📊 Ping '{thread_name}': recording error to ping database")
                                session = PingSessionLocal()
                                ping_record = UptimePing(
                                    thread_name=thread_name,
                                    endpoint='/health',
                                    success=False,
                                    response_time_ms=response_time,
                                    error_message=str(e)
                                )
                                session.add(ping_record)
                                session.commit()
                                db_time = time.time() - db_start
                                logger.info(f"📊 Ping '{thread_name}': ping database write took {db_time:.3f}s")
                            except Exception as db_e:
                                logger.warning(f"⚠️ Ping '{thread_name}': Failed to record ping error in ping database: {db_e}")
                            finally:
                                try:
                                    session.close()
                                except Exception:
                                    pass

                    # Check if thread should restart due to circuit breaker
                    if ping_circuit_breaker.should_restart(thread_name):
                        logger.warning(f"🔄 Circuit breaker triggered restart for ping thread '{thread_name}'")
                        break  # Exit loop to restart thread

                    # Check for excessive consecutive failures
                    if consecutive_failures >= max_consecutive_failures:
                        logger.critical(f"💥 Ping thread '{thread_name}' failed {consecutive_failures} times consecutively - triggering restart")
                        break  # Exit loop to restart thread

                    # Sleep until next ping
                    time.sleep(interval_seconds)

                # If we reach here, thread is restarting
                logger.info(f"🔄 Restarting ping thread '{thread_name}' in 30 seconds...")
                time.sleep(30)

                # Restart the thread
                new_thread = threading.Thread(target=ping_worker, daemon=True, name=f"{thread_name}_restart")
                new_thread.start()
                logger.info(f"✅ Ping thread '{thread_name}' restarted successfully")

            return threading.Thread(target=ping_worker, daemon=True, name=thread_name)

        # Create multiple redundant ping threads with different intervals
        ping_threads = []
        intervals = [
            (5, "ping_5min"),
            (7, "ping_7min"),
            (10, "ping_10min")
        ]

        for interval, name in intervals:
            thread = create_ping_thread(interval, name)
            ping_threads.append(thread)
            thread.start()

        logger.info(f"🚀 Enhanced auto-ping system started with {len(ping_threads)} redundant threads - 24/7 availability ensured")

if __name__ == '__main__':
    # For local development only
    import threading
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    if app:
        port = int(os.environ.get('PORT', 10000))
        logger.info(f"Starting Flask server on port {port}")
        app.run(host='0.0.0.0', port=port)
    else:
        logger.info("Flask not available, running bot only")
        bot_thread.join()
