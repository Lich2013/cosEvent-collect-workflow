import sqlite3
from src.config import settings

def get_db_connection():
    """获取本地 SQLite 数据库连接，并启用外键约束支撑"""
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """根据设计规范使用原生 SQL 初始化三张核心数据库表及索引"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. 创建 cosers 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cosers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            weibo_uid TEXT,
            bilibili_uid TEXT,
            xhs_uid TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );
        """)
        
        # 2. 创建 raw_posts 表 (外键关联 cosers.id)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coser_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            post_id TEXT NOT NULL,
            content TEXT NOT NULL,
            post_url TEXT,
            is_analyzed INTEGER DEFAULT 0,
            edit_count INTEGER DEFAULT 0,
            published_at TEXT,
            scraped_at TEXT,
            FOREIGN KEY(coser_id) REFERENCES cosers(id) ON DELETE CASCADE,
            UNIQUE(platform, post_id)
        );
        """)
        
        # 3. 创建 cosplay_events 表 (外键关联 raw_posts.id)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cosplay_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            coser_name TEXT NOT NULL,
            event_name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_place TEXT NOT NULL,
            event_description TEXT,
            confidence REAL DEFAULT 1.0,
            source_url TEXT,
            status TEXT DEFAULT '未开始',
            created_at TEXT,
            FOREIGN KEY(raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            CHECK (status IN ('未开始', '已结束', '已取消'))
        );
        """)
        
        # 4. 自动数据库热升级：检测并追加新列以支持微博编辑次数与发表时间控制
        cursor.execute("PRAGMA table_info(raw_posts);")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "edit_count" not in columns:
            cursor.execute("ALTER TABLE raw_posts ADD COLUMN edit_count INTEGER DEFAULT 0;")
            print("\x1b[1;32m[Database Migration] 成功为 raw_posts 表追加 edit_count 列。\x1b[0m")
            
        if "published_at" not in columns:
            cursor.execute("ALTER TABLE raw_posts ADD COLUMN published_at TEXT;")
            print("\x1b[1;32m[Database Migration] 成功为 raw_posts 表追加 published_at 列。\x1b[0m")
            
        # 自动为 cosplay_events 检测并追加 status 字段
        cursor.execute("PRAGMA table_info(cosplay_events);")
        ce_columns = [col[1] for col in cursor.fetchall()]
        if "status" not in ce_columns:
            cursor.execute("ALTER TABLE cosplay_events ADD COLUMN status TEXT DEFAULT '未开始';")
            print("\x1b[1;32m[Database Migration] 成功为 cosplay_events 表追加 status 列。\x1b[0m")
            
        conn.commit()
        print("\x1b[1;32m[Database] 数据库表结构初始化成功。\x1b[0m")
    except Exception as e:
        conn.rollback()
        print(f"\x1b[1;31m[Database] 数据库表结构初始化失败: {e}\x1b[0m")
        raise e
    finally:
        conn.close()
