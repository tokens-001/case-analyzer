# SD 卡备份规则

- 每周日执行
- 先把奇点-current 复制为奇点-YYYY-MM-DD 快照，再 rsync 最新版本到奇点-current
- 命令：`rsync -av --delete ~/奇点/ /Volumes/奇点备份/奇点-current/`
- 沙箱无法读写 SD 卡时提醒用户手动执行
