import os
import sys
import shutil
import datetime
from pathlib import Path
from src.config import settings

def auto_backup_db(max_backups: int = 10):
    """
    自动为 active database 物理复制到备份目录，并维护最多 max_backups 个滚动快照。
    如果检测到测试环境或数据库文件尚不存在，则安全跳过。
    """
    # 1. 检查是否处于测试环境
    is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "1"
    if is_testing:
        return

    db_path = Path(settings.db_path)
    # 2. 如果数据库文件尚不存在，无需备份
    if not db_path.exists():
        return

    backup_dir = db_path.parent / "backups"
    
    try:
        # 3. 确保备份目录存在
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 4. 自动删除最老的备份，腾出空间
        existing_backups = sorted(backup_dir.glob("cosevent_*.db"))
        if len(existing_backups) >= max_backups:
            # 保留最近的 max_backups - 1 个，删除其余较老的
            for old_backup in existing_backups[:-(max_backups - 1)]:
                try:
                    old_backup.unlink()
                except Exception as e:
                    print(f"\x1b[1;33m[Warning] Pruning old backup {old_backup.name} failed: {e}\x1b[0m", file=sys.stderr)

        # 5. 执行备份
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        new_backup_file = backup_dir / f"cosevent_{timestamp}.db"

        # 优先使用 sqlite3 原生 backup 接口以保证并发安全，异常时退回 shutil 物理文件拷贝
        try:
            import sqlite3
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(new_backup_file))
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
        except Exception:
            # 物理文件拷贝兜底
            shutil.copy2(db_path, new_backup_file)

        # 确保打印信息使用非显式颜色以便于日志追踪
        print(f"\x1b[1;32m[Database Backup] Successfully created backup snapshot: {new_backup_file.name}\x1b[0m")
    except Exception as e:
        print(f"\x1b[1;33m[Warning] Database auto-backup failed: {e}\x1b[0m", file=sys.stderr)
