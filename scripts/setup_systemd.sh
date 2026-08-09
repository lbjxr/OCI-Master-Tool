#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=""
CONFIG_PATH=""
SERVICE_NAME="oci-master-telegram"
RUN_USER="oci-master"
ENV_FILE="/etc/oci-master.env"
ENABLE_NOW=0
SYSTEMD_DIR="/etc/systemd/system"
DRY_RUN=0
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$BASE_DIR/.venv/bin/python}"
READ_ONLY_PATHS="${READ_ONLY_PATHS:-$BASE_DIR /etc/oci-master}"

usage() {
  cat <<'EOF'
用法:
  scripts/setup_systemd.sh --install-dir DIR --config-path PATH [选项]

必选参数:
  --install-dir DIR        OCI Master 项目部署目录(需包含 OCI_Master.py)
  --config-path PATH       OCI_MASTER_APP_CONFIG 指向的配置文件路径

可选参数:
  --service-name NAME      systemd 服务名(默认: oci-master-telegram)
  --user USER              运行服务的系统用户(默认: oci-master)
  --env-file PATH          EnvironmentFile 路径(默认: /etc/oci-master.env)
  --enable-now             生成后执行 daemon-reload 并 enable --now
  --systemd-dir DIR        service 文件输出目录(默认: /etc/systemd/system)
  --python-bin PATH        Python 可执行文件(默认: /usr/bin/python3)
  --read-only-paths PATHS  只读路径(默认: 项目目录和 /etc/oci-master)
  --dry-run                仅显示目标路径、service 内容和将执行的动作，不写文件、不执行 systemctl
  -h, --help               显示帮助
EOF
}

log() {
  printf '[setup_systemd] %s\n' "$*"
}

require_value() {
  local flag="$1"
  local value="${2-}"
  if [[ -z "$value" ]]; then
    echo "参数 $flag 需要一个值" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      require_value "$1" "${2-}"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --config-path)
      require_value "$1" "${2-}"
      CONFIG_PATH="$2"
      shift 2
      ;;
    --service-name)
      require_value "$1" "${2-}"
      SERVICE_NAME="$2"
      shift 2
      ;;
    --user)
      require_value "$1" "${2-}"
      RUN_USER="$2"
      shift 2
      ;;
    --env-file)
      require_value "$1" "${2-}"
      ENV_FILE="$2"
      shift 2
      ;;
    --systemd-dir)
      require_value "$1" "${2-}"
      SYSTEMD_DIR="$2"
      shift 2
      ;;
    --python-bin)
      require_value "$1" "${2-}"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --read-only-paths)
      require_value "$1" "${2-}"
      READ_ONLY_PATHS="$2"
      shift 2
      ;;
    --enable-now)
      ENABLE_NOW=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$INSTALL_DIR" || -z "$CONFIG_PATH" ]]; then
  echo "--install-dir 与 --config-path 为必填参数" >&2
  usage >&2
  exit 1
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "安装目录不存在: $INSTALL_DIR" >&2
  exit 1
fi

INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
APP_ENTRY="$INSTALL_DIR/OCI_Master.py"

if [[ ! -f "$APP_ENTRY" ]]; then
  echo "未找到入口文件: $APP_ENTRY" >&2
  exit 1
fi

SERVICE_FILE="$SYSTEMD_DIR/${SERVICE_NAME}.service"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${SERVICE_FILE}.bak.${TIMESTAMP}"

if [[ "$DRY_RUN" -eq 0 && "$SYSTEMD_DIR" != "/etc/systemd/system" ]]; then
  log "警告: 当前将写入非默认 systemd 目录: $SYSTEMD_DIR"
  log "请确认这是你的预期目录。若只是演练，建议追加 --dry-run"
fi

SERVICE_CONTENT=$(cat <<EOF
[Unit]
Description=OCI Master Telegram runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment=OCI_MASTER_APP_CONFIG=$CONFIG_PATH
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN $APP_ENTRY telegram
Restart=always
RestartSec=5s
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
User=$RUN_USER
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=$READ_ONLY_PATHS

[Install]
WantedBy=multi-user.target
EOF
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "dry-run: 不创建目录、不备份、不写入 service 文件、不执行 systemctl"
  printf '%s\n' "目标 service: $SERVICE_FILE"
  printf '%s\n' "目标备份: $BACKUP_FILE"
  printf '%s\n' '--- service 内容 ---'
  printf '%s\n' "$SERVICE_CONTENT"
  exit 0
fi

mkdir -p "$SYSTEMD_DIR"

if [[ -e "$SERVICE_FILE" ]]; then
  cp -a "$SERVICE_FILE" "$BACKUP_FILE"
  log "已备份现有 service: $BACKUP_FILE"
fi

printf '%s\n' "$SERVICE_CONTENT" > "$SERVICE_FILE"

log "已生成 service 文件: $SERVICE_FILE"

systemctl daemon-reload
log "已执行: systemctl daemon-reload"

if [[ "$ENABLE_NOW" -eq 1 ]]; then
  systemctl enable --now "${SERVICE_NAME}.service"
  log "已执行: systemctl enable --now ${SERVICE_NAME}.service"
else
  log "未指定 --enable-now，可手动执行: systemctl enable --now ${SERVICE_NAME}.service"
fi

systemctl --no-pager -l status "${SERVICE_NAME}.service" || true
