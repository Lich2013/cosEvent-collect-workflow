import sqlite3
from src.config import settings
from src.utils.backup_helper import auto_backup_db

def get_db_connection():
    """获取本地 SQLite 数据库连接，并启用外键约束及 WAL 模式支撑"""
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db():
    """根据设计规范使用原生 SQL 初始化三张核心数据库表及索引"""
    # 自动在结构初始化或升级前备份数据库
    auto_backup_db()
    
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
        
        # 3. 创建 cosplay_events 表 (外键关联 raw_posts.id, normalized_events.id)
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
            normalized_event_id INTEGER,
            event_type TEXT DEFAULT '漫展',
            created_at TEXT,
            FOREIGN KEY(raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            FOREIGN KEY(normalized_event_id) REFERENCES normalized_events(id) ON DELETE SET NULL,
            CHECK (status IN ('未开始', '已结束', '已取消')),
            CHECK (event_type IN ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'))
        );
        """)

        # 4. 创建 normalized_events 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS normalized_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_fingerprint TEXT UNIQUE,
            standard_name TEXT NOT NULL,
            city TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            event_type TEXT DEFAULT '漫展',
            created_at TEXT,
            CHECK (event_type IN ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'))
        );
        """)

        # 5. 创建 event_aliases 表 (外键关联 normalized_events.id)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_name TEXT NOT NULL,
            city TEXT NOT NULL,
            normalized_event_id INTEGER NOT NULL,
            created_at TEXT,
            FOREIGN KEY(normalized_event_id) REFERENCES normalized_events(id) ON DELETE CASCADE,
            UNIQUE(alias_name, city)
        );
        """)

        # 5.5 创建 event_mappings 表 (中间关联映射表，外键关联 cosplay_events.id)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_event_id INTEGER NOT NULL UNIQUE,
            normalized_event_id VARCHAR(32) NOT NULL,
            created_at TEXT,
            FOREIGN KEY(raw_event_id) REFERENCES cosplay_events(id) ON DELETE CASCADE
        );
        """)

        # 5.6 创建 final_exhibition_view 表 (物化呈现展示表，id 为 32 位 MD5 确定性哈希)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS final_exhibition_view (
            id VARCHAR(32) PRIMARY KEY,
            event_fingerprint TEXT UNIQUE,
            standard_name TEXT NOT NULL,
            city TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            event_type TEXT DEFAULT '漫展',
            is_frozen INTEGER DEFAULT 0,
            created_at TEXT,
            CHECK (event_type IN ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'))
        );
        """)
        
        # 5.7 创建 coser_candidates 表 (新发现 of Coser 候选表)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS coser_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            source_ref TEXT,
            matched_bili_uid TEXT,
            matched_weibo_uid TEXT,
            matched_xhs_uid TEXT,
            match_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            is_verified INTEGER DEFAULT 0,
            verify_reason TEXT,
            created_at TEXT,
            CHECK (status IN ('pending', 'approved', 'ignored'))
        );
        """)

        # 5.7.5 创建 candidate_raw_posts 表 (候选人隔离博文表)
        cursor.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='candidate_raw_posts';")
        row = cursor.fetchone()
        if row:
            old_sql = row[0] or ""
            # 检测旧版本的唯一约束 (去除空格以便匹配)
            if "UNIQUE(platform,post_id)" in old_sql.replace(" ", ""):
                print("\x1b[1;33m[Database Migration] 检测到旧版本的 candidate_raw_posts 唯一约束，准备重建该表以更新约束...\x1b[0m")
                cursor.execute("DROP TABLE candidate_raw_posts;")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS candidate_raw_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            post_id TEXT NOT NULL,
            content TEXT NOT NULL,
            post_url TEXT,
            published_at TEXT,
            scraped_at TEXT,
            FOREIGN KEY(candidate_id) REFERENCES coser_candidates(id) ON DELETE CASCADE,
            UNIQUE(candidate_id, platform, post_id)
        );
        """)
        
        # 5.8 创建 coser_scrape_state 表 (独立平台调度状态表)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS coser_scrape_state (
            coser_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            last_scraped_at TEXT,
            PRIMARY KEY (coser_id, platform),
            FOREIGN KEY(coser_id) REFERENCES cosers(id) ON DELETE CASCADE
        );
        """)

        
        # 6. 自动数据库热升级：检测并追加新列以支持微博编辑次数与发表时间控制
        cursor.execute("PRAGMA table_info(raw_posts);")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "edit_count" not in columns:
            cursor.execute("ALTER TABLE raw_posts ADD COLUMN edit_count INTEGER DEFAULT 0;")
            print("\x1b[1;32m[Database Migration] 成功为 raw_posts 表追加 edit_count 列。\x1b[0m")
            
        if "published_at" not in columns:
            cursor.execute("ALTER TABLE raw_posts ADD COLUMN published_at TEXT;")
            print("\x1b[1;32m[Database Migration] 成功为 raw_posts 表追加 published_at 列。\x1b[0m")
            
        # 自动为 cosplay_events 检测并追加 status 与 normalized_event_id 字段
        cursor.execute("PRAGMA table_info(cosplay_events);")
        ce_columns = [col[1] for col in cursor.fetchall()]
        if "status" not in ce_columns:
            cursor.execute("ALTER TABLE cosplay_events ADD COLUMN status TEXT DEFAULT '未开始';")
            print("\x1b[1;32m[Database Migration] 成功为 cosplay_events 表追加 status 列。\x1b[0m")
        if "normalized_event_id" not in ce_columns:
            cursor.execute("ALTER TABLE cosplay_events ADD COLUMN normalized_event_id INTEGER REFERENCES normalized_events(id) ON DELETE SET NULL;")
            print("\x1b[1;32m[Database Migration] 成功为 cosplay_events 表追加 normalized_event_id 列。\x1b[0m")
        if "event_type" not in ce_columns:
            cursor.execute("ALTER TABLE cosplay_events ADD COLUMN event_type TEXT DEFAULT '漫展';")
            print("\x1b[1;32m[Database Migration] 成功为 cosplay_events 表追加 event_type 列。\x1b[0m")

        # 自动为 normalized_events 检测并追加 event_type 字段
        cursor.execute("PRAGMA table_info(normalized_events);")
        ne_columns = [col[1] for col in cursor.fetchall()]
        if "event_type" not in ne_columns:
            cursor.execute("ALTER TABLE normalized_events ADD COLUMN event_type TEXT DEFAULT '漫展';")
            print("\x1b[1;32m[Database Migration] 成功为 normalized_events 表追加 event_type 列。\x1b[0m")

        # 自动为 coser_candidates 检测并追加 is_verified 与 verify_reason 字段
        cursor.execute("PRAGMA table_info(coser_candidates);")
        cc_columns = [col[1] for col in cursor.fetchall()]
        if "is_verified" not in cc_columns:
            cursor.execute("ALTER TABLE coser_candidates ADD COLUMN is_verified INTEGER DEFAULT 0;")
            print("\x1b[1;32m[Database Migration] 成功为 coser_candidates 表追加 is_verified 列。\x1b[0m")
        if "verify_reason" not in cc_columns:
            cursor.execute("ALTER TABLE coser_candidates ADD COLUMN verify_reason TEXT;")
            print("\x1b[1;32m[Database Migration] 成功为 coser_candidates 表追加 verify_reason 列。\x1b[0m")
            
        conn.commit()
        print("\x1b[1;32m[Database] 数据库表结构初始化及迁移升级成功。\x1b[0m")
    except Exception as e:
        conn.rollback()
        print(f"\x1b[1;31m[Database] 数据库表结构初始化失败: {e}\x1b[0m")
        raise e
    finally:
        conn.close()
