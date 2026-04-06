# Security List 向导补丁代码
# 这个文件包含需要插入到 OCI_Master.py 中的辅助函数和修复逻辑

import ipaddress
import re
from typing import Tuple, Optional

def _parse_cidr_input(cidr_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    解析 CIDR 输入
    返回: (是否合法, 解析后的CIDR, 错误消息)
    """
    cidr_text = cidr_text.strip()
    
    # 尝试解析 IPv4
    try:
        ipaddress.IPv4Network(cidr_text, strict=False)
        return (True, cidr_text, None)
    except (ipaddress.AddressValueError, ValueError):
        pass
    
    # 尝试解析 IPv6
    try:
        ipaddress.IPv6Network(cidr_text, strict=False)
        return (True, cidr_text, None)
    except (ipaddress.AddressValueError, ValueError):
        pass
    
    return (False, None, f"❌ 无效的 CIDR 格式: <code>{cidr_text}</code>\n\n请输入合法的 IPv4 或 IPv6 CIDR，例如：\n• <code>0.0.0.0/0</code>\n• <code>192.168.1.0/24</code>\n• <code>::/0</code>\n• <code>2001:db8::/32</code>")


def _parse_port_input(port_text: str) -> Tuple[bool, Optional[int], Optional[int], Optional[str]]:
    """
    解析端口输入
    返回: (是否合法, port_min, port_max, 错误消息)
    """
    port_text = port_text.strip()
    
    # 范围格式: 25000-25100
    if "-" in port_text:
        parts = port_text.split("-", 1)
        if len(parts) != 2:
            return (False, None, None, "❌ 端口范围格式错误，应为: <code>起始端口-结束端口</code>")
        
        try:
            port_min = int(parts[0].strip())
            port_max = int(parts[1].strip())
        except ValueError:
            return (False, None, None, "❌ 端口必须是数字")
        
        if port_min < 1 or port_min > 65535:
            return (False, None, None, f"❌ 起始端口 {port_min} 超出范围 (1-65535)")
        if port_max < 1 or port_max > 65535:
            return (False, None, None, f"❌ 结束端口 {port_max} 超出范围 (1-65535)")
        if port_min > port_max:
            return (False, None, None, f"❌ 起始端口 {port_min} 不能大于结束端口 {port_max}")
        
        return (True, port_min, port_max, None)
    
    # 单端口格式: 22
    try:
        port = int(port_text)
    except ValueError:
        return (False, None, None, "❌ 端口必须是数字或范围格式 (如 <code>22</code> 或 <code>25000-25100</code>)")
    
    if port < 1 or port > 65535:
        return (False, None, None, f"❌ 端口 {port} 超出范围 (1-65535)")
    
    return (True, port, port, None)


def _protocol_needs_port(protocol: str) -> bool:
    """判断协议是否需要端口"""
    return protocol not in {"1", "58", "all"}


# 渲染步骤函数

def _render_sl_cidr_step_text(state: dict) -> str:
    """生成 CIDR 步骤的提示文本"""
    action = state.get("action", "")
    direction = "来源 CIDR" if action.endswith("ingress") else "目标 CIDR"
    return f"<b>请选择或输入{direction}</b>\n\n示例：\n• <code>0.0.0.0/0</code> (允许所有 IPv4)\n• <code>192.168.1.0/24</code> (私有网段)\n• <code>::/0</code> (允许所有 IPv6)"


def _render_sl_port_step_text() -> str:
    """生成端口步骤的提示文本"""
    return "<b>请选择或输入端口</b>\n\n支持格式：\n• 单端口: <code>22</code>\n• 范围: <code>25000-25100</code>"


def _render_sl_description_step_text() -> str:
    """生成描述步骤的提示文本"""
    return "<b>请输入规则描述</b>\n\n可直接发送描述文本\n若留空请发送: <code>-</code>"


# 返回链路辅助函数

def _get_back_callback_for_step(state: dict, current_step: str) -> str:
    """
    根据当前步骤生成"返回上一步"的 callback_data
    
    步骤流程:
    - protocol -> 返回 SL 动作页
    - cidr -> 返回协议页
    - port -> 返回 CIDR 页
    - description -> 返回端口页(如有) 或 CIDR 页
    """
    action = state.get("action", "")
    sl_token = state.get("sl_token", "")
    
    if current_step == "protocol":
        # 返回到 SL 动作页（选择协议的上一步）
        instance_token = state.get("instance_token", "")
        return f"slm:inst:{action}:{instance_token}"
    
    elif current_step == "cidr":
        # 返回到协议选择
        return f"slm:back:protocol:{action}:{sl_token}"
    
    elif current_step == "port":
        # 返回到 CIDR 选择
        return f"slm:back:cidr:{action}:{sl_token}"
    
    elif current_step == "description":
        protocol = state.get("protocol", "")
        if _protocol_needs_port(protocol):
            # 返回到端口选择
            return f"slm:back:port:{action}:{sl_token}"
        else:
            # 返回到 CIDR 选择
            return f"slm:back:cidr:{action}:{sl_token}"
    
    return "slm:home"


# 测试代码
if __name__ == "__main__":
    # 测试 CIDR 解析
    test_cidrs = [
        "0.0.0.0/0",
        "192.168.1.0/24",
        "::/0",
        "2001:db8::/32",
        "abc",
        "1.1.1.1",
        "999.999.999.999/33",
    ]
    
    print("CIDR 解析测试:")
    for cidr in test_cidrs:
        valid, parsed, error = _parse_cidr_input(cidr)
        print(f"  {cidr:30} -> {'✅' if valid else '❌'} {parsed or error}")
    
    # 测试端口解析
    test_ports = [
        "22",
        "443",
        "25000-25100",
        "0",
        "65536",
        "100-99",
        "abc",
    ]
    
    print("\n端口解析测试:")
    for port in test_ports:
        valid, min_p, max_p, error = _parse_port_input(port)
        if valid:
            print(f"  {port:20} -> ✅ {min_p}-{max_p}")
        else:
            print(f"  {port:20} -> ❌ {error[:50]}")
