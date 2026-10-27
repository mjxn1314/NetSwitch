# -*- coding: utf-8 -*-
"""
NetSwitch（IP 快切）Windows v1.4
================================
功能：
  1. 快速枚举网卡（CIM，约 0.5 秒），显示 IP / 掩码 / 网关 / DNS / DHCP 状态
  2. 一键切换为「自动获取 IP（DHCP）」
  3. 设置静态 IP：主 IP、子网掩码、默认网关、首选/备用 DNS
  4. 支持【同一张网卡绑定多个 IP】，可添加任意数量的附加 IP
  5. 档案不绑定网卡，可对当前选定的任意网卡一键应用
  6. 档案右键菜单：编辑（独立窗口）、一键应用、删除
  7. 安全写入：netsh 即时生效，设置失败不破坏现有配置
  8. 【静态路由】查看系统/网卡的永久、临时路由，可添加、删除永久或临时路由
  9. 配置文件统一存放在「文档\\NetSwitch\\」，程序目录不再显示
 10. 窗口自适应屏幕大小，可自由缩放

注意：
  - 修改 IP / 路由需要【管理员权限】，请使用同目录下的「启动工具.bat」运行
  - 附加 IP 不设置默认网关（一张网卡只有一个默认网关，作用于主 IP）
  - 档案文件 ip_profiles.json 存放在「文档\\NetSwitch\\」目录
"""

import os
import sys
import json
import base64
import subprocess
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
APP_TITLE = "NetSwitch - IP 快切 v1.4"

# 现代浅色配色
BG = "#eef2f8"          # 窗口背景（浅蓝灰）
CARD = "#ffffff"        # 卡片背景
PRIMARY = "#2563eb"     # 主色（蓝）
PRIMARY_DARK = "#1d4ed8"
ACCENT = "#06b6d4"       # 强调（青）
TEXT = "#1e293b"
MUTED = "#64748b"
BORDER = "#d7dee9"
HEADER_BG = "#f1f5f9"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_documents_dir():
    """获取系统『文档』文件夹（SHGetKnownFolderPath，兼容文档被重定向到 OneDrive 等）。"""
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                   (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85,
                                        0x48, 0x03, 0x69, 0xC7))
        path = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(path)) == 0:
            return path.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


# 配置统一存放在 文档\NetSwitch\ 下，程序目录不再显示配置文件
APP_DATA_DIR = os.path.join(get_documents_dir(), "NetSwitch")
try:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
except Exception:
    pass
CONFIG_PATH = os.path.join(APP_DATA_DIR, "ip_profiles.json")


def migrate_old_config():
    """首次运行：若程序目录存在旧 ip_profiles.json，迁移到文档目录。"""
    old = os.path.join(BASE_DIR, "ip_profiles.json")
    if os.path.exists(old) and not os.path.exists(CONFIG_PATH):
        try:
            os.replace(old, CONFIG_PATH)
        except Exception:
            pass


migrate_old_config()

COMMON_MASKS = [
    "255.255.255.0",
    "255.255.255.128",
    "255.255.255.192",
    "255.255.255.224",
    "255.255.255.240",
    "255.255.255.248",
    "255.255.255.252",
    "255.255.254.0",
    "255.255.252.0",
    "255.255.248.0",
    "255.255.240.0",
    "255.255.224.0",
    "255.255.192.0",
    "255.255.128.0",
    "255.255.0.0",
    "255.254.0.0",
    "255.252.0.0",
    "255.240.0.0",
]


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# 子进程隐藏窗口参数：CREATE_NO_WINDOW + STARTUPINFO(SW_HIDE)，避免刷新/操作时闪黑框/蓝框
def hidden_startup():
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {
        "creationflags": 0x08000000,  # CREATE_NO_WINDOW
        "startupinfo": si,
    }


def run_ps(script: str, timeout: int = 60):
    """以 EncodedCommand 方式执行 PowerShell。"""
    full = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$ProgressPreference='SilentlyContinue'; "
        + script
    )
    encoded = base64.b64encode(full.encode("utf-16-le")).decode("ascii")
    try:
        p = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **hidden_startup(),
        )
        text = (p.stdout or "").strip()
        if not text:
            text = (p.stderr or "").strip()
        return p.returncode, text
    except subprocess.TimeoutExpired:
        return -1, "PowerShell 执行超时"
    except Exception as e:
        return -1, f"无法启动 PowerShell：{e}"


def run_netsh(args, timeout: int = 60):
    """执行 netsh 命令，返回 (returncode, output)。"""
    try:
        p = subprocess.run(
            ["netsh"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="gbk",
            errors="replace",
            **hidden_startup(),
        )
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return -1, "netsh 执行超时"
    except Exception as e:
        return -1, f"无法启动 netsh：{e}"


def run_route(args, timeout: int = 60):
    """执行 route.exe 命令，返回 (returncode, output)。"""
    try:
        p = subprocess.run(
            ["route"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="gbk",
            errors="replace",
            **hidden_startup(),
        )
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return -1, "route 执行超时"
    except Exception as e:
        return -1, f"无法启动 route：{e}"


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def valid_ipv4(s):
    """校验 IPv4 地址（每段 0-255，不允许前导 0）"""
    if not s:
        return False
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for x in parts:
        if not x.isdigit() or len(x) > 3:
            return False
        if len(x) > 1 and x[0] == "0":
            return False
        if not 0 <= int(x) <= 255:
            return False
    return True


def mask_to_prefix(mask):
    """子网掩码转前缀长度，非法掩码返回 None。"""
    if not valid_ipv4(mask):
        return None
    bits = "".join("{:08b}".format(int(x)) for x in mask.split("."))
    if "01" in bits:
        return None
    return bits.count("1")


def prefix_to_mask(prefix):
    """前缀长度转子网掩码。"""
    try:
        p = int(prefix)
    except Exception:
        return ""
    if not 0 <= p <= 32:
        return ""
    bits = "1" * p + "0" * (32 - p)
    return ".".join(str(int(bits[i:i + 8], 2)) for i in range(0, 32, 8))


def set_widget_enabled(w, enabled):
    """
    启用/禁用控件。
    注意：ttk.Treeview 没有 -state 配置项，需用 state(['disabled']) 方式。
    """
    try:
        if isinstance(w, ttk.Treeview):
            w.state(["!disabled"] if enabled else ["disabled"])
        else:
            w.configure(state="normal" if enabled else "disabled")
    except tk.TclError:
        try:
            w.state(["!disabled"] if enabled else ["disabled"])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 读取网卡（CIM，快速）
# ---------------------------------------------------------------------------
GET_ADAPTERS_PS = r"""
# 一次性获取所有网卡，用哈希表按 DeviceID 匹配（避免循环内多次 CIM 查询导致极慢）
$allAdapters = Get-CimInstance Win32_NetworkAdapter
$adapterMap = @{}
foreach ($aa in $allAdapters) { $adapterMap[[int]$aa.DeviceID] = $aa }

$list = @()
foreach ($c in (Get-CimInstance Win32_NetworkAdapterConfiguration)) {
    $a = $adapterMap[[int]$c.Index]
    if (-not $a) { continue }
    if (-not $a.NetConnectionID) { continue }

    $rawIPs = @($c.IPAddress)
    $rawMasks = @($c.IPSubnet)
    $ipv4 = @()
    for ($i=0; $i -lt $rawIPs.Count; $i++) {
        $ip = [string]$rawIPs[$i]
        if ($ip -like '*.*' -and $ip -notlike '169.254.*') {
            $m = ''
            if ($i -lt $rawMasks.Count) { $m = [string]$rawMasks[$i] }
            $ipv4 += [PSCustomObject]@{ ip=$ip; mask=$m }
        }
    }

    $dns = @()
    if ($c.DNSServerSearchOrder) { $dns = @($c.DNSServerSearchOrder) }

    $gw = ''
    if ($c.DefaultIPGateway) { $gw = [string]@($c.DefaultIPGateway)[0] }

    $status = [int]$a.NetConnectionStatus
    $statusText = switch ($status) {
        2 { 'Up' }
        5 { 'Disabled' }
        4 { 'Not Present' }
        7 { 'Disconnected' }
        default { 'Disconnected' }
    }

    $list += [PSCustomObject]@{
        name=[string]$a.NetConnectionID
        desc=[string]$a.Description
        status=$statusText
        dhcp=if ($c.DHCPEnabled) { 'Enabled' } else { 'Disabled' }
        gateway=$gw
        dns=$dns
        ipv4=$ipv4
    }
}
if ($list.Count -gt 0) { $list | ConvertTo-Json -Depth 5 -Compress } else { '[]' }
"""


def get_adapters():
    """返回 (list[dict], error)"""
    code, out = run_ps(GET_ADAPTERS_PS, timeout=30)
    if code != 0:
        return [], out
    try:
        data = json.loads(out)
    except Exception as e:
        return [], f"解析网卡数据失败：{e}"
    if isinstance(data, dict):
        data = [data]

    result = []
    for a in data:
        dns = a.get("dns") or []
        if isinstance(dns, str):
            dns = [dns]

        ipv4 = a.get("ipv4") or []
        if isinstance(ipv4, dict):
            ipv4 = [ipv4]

        ips = []
        for x in ipv4:
            mask = x.get("mask", "")
            prefix = mask_to_prefix(mask)
            if prefix is None:
                prefix = 0
            ips.append({"ip": x.get("ip", ""), "mask": mask, "prefix": prefix})

        result.append({
            "name": a.get("name", ""),
            "desc": a.get("desc", ""),
            "status": a.get("status", ""),
            "dhcp": a.get("dhcp", ""),
            "gateway": a.get("gateway", ""),
            "dns": dns,
            "ips": ips,
            "ip": ips[0]["ip"] if ips else "",
            "prefix": ips[0]["prefix"] if ips else 0,
        })
    return result, ""


# ---------------------------------------------------------------------------
# 静态路由（读取 / 添加 / 删除）
# ---------------------------------------------------------------------------
ROUTE_MASKS = [
    "255.255.255.255",
    "255.255.255.0",
    "255.255.255.252",
    "255.255.255.248",
    "255.255.255.240",
    "255.255.255.224",
    "255.255.255.192",
    "255.255.255.128",
    "255.255.254.0",
    "255.255.255.0",
    "255.255.0.0",
    "255.0.0.0",
]

GET_ROUTES_PS = r"""
# 永久路由：直接读注册表 PersistentRoutes（值名格式：目标,掩码,网关）
$persist = @{}
$pr = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\PersistentRoutes' -ErrorAction SilentlyContinue
if ($pr) {
    foreach ($prop in $pr.PSObject.Properties) {
        if ($prop.Name -notmatch '^[^,]+,[^,]+,[^,]+$') { continue }
        $parts = $prop.Name -split ','
        $key = ($parts[0] + '|' + $parts[1] + '|' + $parts[2])
        $persist[$key] = $true
    }
}

# 活动路由（ActiveStore）
$active = Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction SilentlyContinue
$list = @()
foreach ($r in $active) {
    $dp = [string]$r.DestinationPrefix
    $seg = $dp -split '/'
    $dest = $seg[0]
    $prefix = 0
    [void][int]::TryParse($seg[1], [ref]$prefix)

    $gw = [string]$r.NextHop
    $mask = ''
    if ($seg[1] -match '^\d+$') {
        $bits = '1' * [int]$seg[1] + '0' * (32 - [int]$seg[1])
        $oct = @()
        for ($i=0; $i -lt 32; $i += 8) { $oct += [string]([Convert]::ToInt32($bits.Substring($i,8),2)) }
        $mask = $oct -join '.'
    }

    $key = ($dest + '|' + $mask + '|' + $gw)
    $isPersist = $persist.ContainsKey($key)
    # 若掩码未完全匹配，再用 目标+网关 兜底判断
    if (-not $isPersist) {
        foreach ($k in $persist.Keys) {
            $ks = $k -split '\|'
            if ($ks[0] -eq $dest -and $ks[2] -eq $gw) { $isPersist = $true; break }
        }
    }

    $list += [PSCustomObject]@{
        dest=$dest
        prefix=$prefix
        mask=$mask
        gw=$gw
        iface=[string]$r.InterfaceAlias
        ifIndex=[int]$r.InterfaceIndex
        metric=[int]$r.RouteMetric
        persist=[bool]$isPersist
    }
}
if ($list.Count -gt 0) { $list | ConvertTo-Json -Depth 4 -Compress } else { '[]' }
"""


def get_routes():
    """返回 (list[dict], error)。每条为活动路由，persist 标记是否为永久路由。"""
    code, out = run_ps(GET_ROUTES_PS, timeout=30)
    if code != 0:
        return [], out
    try:
        data = json.loads(out)
    except Exception as e:
        return [], f"解析路由数据失败：{e}"
    if isinstance(data, dict):
        data = [data]
    routes = []
    for r in data:
        mask = r.get("mask", "")
        prefix = r.get("prefix", 0)
        if not mask and prefix:
            mask = prefix_to_mask(prefix)
        routes.append({
            "dest": r.get("dest", ""),
            "prefix": prefix,
            "mask": mask,
            "gw": r.get("gw", ""),
            "iface": r.get("iface", ""),
            "ifIndex": r.get("ifIndex", 0),
            "metric": r.get("metric", 0),
            "persist": bool(r.get("persist", False)),
        })
    return routes, ""


def add_route(dest, mask, gw, metric, if_index, persist, log):
    """添加静态路由。返回 (ok, msg)。"""
    args = ["add", dest, "mask", mask, gw]
    if metric:
        args += ["metric", str(metric)]
    if if_index:
        args += ["if", str(if_index)]
    if persist:
        args = ["-p"] + args
    code, out = run_route(args)
    if code != 0:
        kind = "永久" if persist else "临时"
        return False, f"添加{kind}路由失败：{out}"
    kind = "永久" if persist else "临时"
    log(f"已添加{kind}路由：{dest} / {mask} → {gw}"
        + (f"（metric {metric}）" if metric else ""))
    return True, ""


def delete_route(route, log):
    """删除路由（永久路由会同时删除持久条目）。返回 (ok, msg)。"""
    dest = route.get("dest", "")
    gw = route.get("gw", "")
    args = ["delete", dest]
    if gw and gw != "0.0.0.0":
        args.append(gw)
    code, out = run_route(args)
    if code != 0:
        return False, f"删除路由失败：{out}"
    kind = "永久" if route.get("persist") else "临时"
    log(f"已删除{kind}路由：{dest} → {gw or '任意网关'}")
    return True, ""


# ---------------------------------------------------------------------------
# 写入配置（netsh，安全）
# ---------------------------------------------------------------------------
def apply_dhcp(adapter_name, log):
    """切换为 DHCP。返回 (ok, msg)"""
    code, out = run_netsh(["interface", "ip", "set", "address",
                           f"name={adapter_name}", "dhcp"])
    if code != 0:
        return False, "设置 DHCP 失败：" + out
    log("已设置 IP 为 DHCP 自动获取")
    code, out = run_netsh(["interface", "ip", "set", "dnsservers",
                           f"name={adapter_name}", "dhcp"])
    if code != 0:
        log("DNS 自动获取设置失败：" + out)
    else:
        log("已设置 DNS 为 DHCP 自动获取")
    return True, ""


def apply_static(adapter_name, primary_ip, mask, gateway, dns1, dns2, extras, log):
    """设置静态 IP（含附加 IP）。返回 (ok, msg)"""
    # 1) 主地址（netsh set 会替换旧配置；失败则旧配置保留）
    args = ["interface", "ip", "set", "address",
            f"name={adapter_name}", "static", primary_ip, mask]
    if gateway:
        args.append(gateway)
    code, out = run_netsh(args)
    if code != 0:
        return False, "主地址设置失败（现有配置未改动）：" + out
    log(f"已设置主 IP {primary_ip} / {mask}" + (f"，网关 {gateway}" if gateway else ""))

    # 2) 附加 IP（逐个 add，失败不影响主地址）
    for e in extras:
        code, out = run_netsh(["interface", "ip", "add", "address",
                               f"name={adapter_name}", e["ip"], e["mask"]])
        if code != 0:
            log(f'附加 IP {e["ip"]} 添加失败：{out}')
        else:
            log(f'已添加附加 IP {e["ip"]} / {e["mask"]}')

    # 3) DNS
    if dns1:
        code, out = run_netsh(["interface", "ip", "set", "dnsservers",
                               f"name={adapter_name}", "static", dns1, "primary"])
        if code != 0:
            log("首选 DNS 设置失败：" + out)
        else:
            log(f"已设置首选 DNS {dns1}")
            if dns2:
                code, out = run_netsh(["interface", "ip", "add", "dnsservers",
                                       f"name={adapter_name}", dns2, "index=2"])
                if code != 0:
                    log("备用 DNS 设置失败：" + out)
                else:
                    log(f"已添加备用 DNS {dns2}")
    else:
        # 无 DNS：清空静态 DNS 列表
        code, out = run_ps(
            f"Set-DnsClientServerAddress -InterfaceAlias {ps_quote(adapter_name)}"
            " -ServerAddresses @()"
        )
        if code != 0:
            log("清空 DNS 失败：" + out)
        else:
            log("已清空 DNS")
    return True, ""


# ---------------------------------------------------------------------------
# 档案存取
# ---------------------------------------------------------------------------
def load_profiles():
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        profiles = data.get("profiles", [])
        return profiles if isinstance(profiles, list) else []
    except Exception:
        return []


def save_profiles(profiles):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"profiles": profiles}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ---------------------------------------------------------------------------
# 档案编辑对话框（独立小窗口）
# ---------------------------------------------------------------------------
class ProfileEditDialog(tk.Toplevel):
    def __init__(self, master, profile):
        super().__init__(master)
        self.title("编辑档案")
        self.resizable(False, False)
        self.result = None
        self.extra_ips = []

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        # 名称
        r0 = ttk.Frame(frm)
        r0.pack(fill="x", pady=3)
        ttk.Label(r0, text="档案名称：").pack(side="left")
        self.name_entry = ttk.Entry(r0, width=22)
        self.name_entry.pack(side="left", padx=6)
        self.name_entry.insert(0, profile.get("name", ""))

        # 模式
        self.mode_var = tk.StringVar(value=profile.get("mode", "dhcp"))
        r1 = ttk.Frame(frm)
        r1.pack(fill="x", pady=3)
        ttk.Radiobutton(r1, text="自动获取（DHCP）", variable=self.mode_var,
                        value="dhcp", command=self._toggle).pack(side="left")
        ttk.Radiobutton(r1, text="静态 IP", variable=self.mode_var,
                        value="static", command=self._toggle).pack(side="left", padx=18)

        # 静态参数
        frm_static = ttk.LabelFrame(frm, text=" 静态参数 ")
        frm_static.pack(fill="x", pady=6)
        self.ip_entry = self._add_field(frm_static, 0, "主 IP：", profile.get("ip", ""))
        self.mask_combo = self._add_combo(frm_static, 1, "掩码：", profile.get("mask", ""))
        self.gw_entry = self._add_field(frm_static, 2, "网关：", profile.get("gateway", ""))
        self.dns1_entry = self._add_field(frm_static, 3, "首选 DNS：", profile.get("dns1", ""))
        self.dns2_entry = self._add_field(frm_static, 4, "备用 DNS：", profile.get("dns2", ""))

        # 附加 IP
        frm_extra = ttk.LabelFrame(frm, text=" 附加 IP（可选） ")
        frm_extra.pack(fill="x", pady=6)
        rx = ttk.Frame(frm_extra, style="Card.TFrame")
        rx.pack(fill="x", padx=6, pady=4)
        ttk.Label(rx, text="IP：", style="Card.TLabel").pack(side="left")
        self.extra_ip_entry = ttk.Entry(rx, width=13)
        self.extra_ip_entry.pack(side="left", padx=4)
        ttk.Label(rx, text="掩码：", style="Card.TLabel").pack(side="left")
        self.extra_mask_combo = ttk.Combobox(rx, values=COMMON_MASKS, width=13)
        self.extra_mask_combo.pack(side="left", padx=4)
        self.extra_mask_combo.set("255.255.255.0")
        ttk.Button(rx, text="添加", width=5, command=self._add_extra).pack(side="left", padx=5)
        ttk.Button(rx, text="删除选中", width=8, command=self._del_extra).pack(side="left")

        self.extra_tree = ttk.Treeview(frm_extra, columns=("ip", "mask"),
                                       show="headings", height=3)
        self.extra_tree.heading("ip", text="附加 IP")
        self.extra_tree.heading("mask", text="掩码")
        self.extra_tree.column("ip", width=200, anchor="center")
        self.extra_tree.column("mask", width=180, anchor="center")
        self.extra_tree.pack(fill="x", padx=6, pady=4)

        loaded = []
        for e in profile.get("extra_ips", []):
            m = e.get("mask", "")
            loaded.append({"ip": e.get("ip", ""), "mask": m,
                           "prefix": mask_to_prefix(m)})
        self._set_extra(loaded)

        # 确定 / 取消
        rb = ttk.Frame(frm)
        rb.pack(fill="x", pady=(8, 0))
        ttk.Button(rb, text="确定", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=6)
        ttk.Button(rb, text="取消", width=10, command=self.destroy).pack(side="right")

        self.static_widgets = [
            self.ip_entry, self.mask_combo, self.gw_entry,
            self.dns1_entry, self.dns2_entry,
            self.extra_ip_entry, self.extra_mask_combo, self.extra_tree,
        ]

        # 模态 + 相对主窗口居中
        self.transient(master)
        self.grab_set()
        self._toggle()
        self.update_idletasks()
        mx, my = master.winfo_rootx(), master.winfo_rooty()
        mw, mh = master.winfo_width(), master.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry("+%d+%d" % (mx + (mw - w) // 2, my + (mh - h) // 2))

    def _add_field(self, parent, row, label, value):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="e", padx=4, pady=2)
        e = ttk.Entry(parent, width=18)
        e.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        e.insert(0, value)
        return e

    def _add_combo(self, parent, row, label, value):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="e", padx=4, pady=2)
        c = ttk.Combobox(parent, values=COMMON_MASKS, width=16)
        c.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        c.set(value)
        return c

    def _toggle(self):
        static = self.mode_var.get() == "static"
        for w in self.static_widgets:
            set_widget_enabled(w, static)

    def _set_extra(self, extras):
        self.extra_ips = extras
        for i in self.extra_tree.get_children():
            self.extra_tree.delete(i)
        for e in extras:
            self.extra_tree.insert("", "end", values=(e["ip"], e["mask"]))

    def _used_ips(self):
        used = set()
        if self.ip_entry.get().strip():
            used.add(self.ip_entry.get().strip())
        for e in self.extra_ips:
            used.add(e["ip"])
        return used

    def _add_extra(self):
        ip = self.extra_ip_entry.get().strip()
        mask = self.extra_mask_combo.get().strip()
        if not valid_ipv4(ip):
            messagebox.showerror("错误", "IP 格式不正确。", parent=self)
            return
        prefix = mask_to_prefix(mask)
        if prefix is None:
            messagebox.showerror("错误", "掩码不正确。", parent=self)
            return
        if ip in self._used_ips():
            messagebox.showwarning("重复", "该 IP 已存在。", parent=self)
            return
        self.extra_ips.append({"ip": ip, "mask": mask, "prefix": prefix})
        self._set_extra(self.extra_ips)
        self.extra_ip_entry.delete(0, "end")

    def _del_extra(self):
        item = self.extra_tree.focus()
        if not item:
            messagebox.showwarning("提示", "请先选中一条附加 IP。", parent=self)
            return
        ip = self.extra_tree.item(item, "values")[0]
        self.extra_ips = [e for e in self.extra_ips if e["ip"] != ip]
        self._set_extra(self.extra_ips)

    def _ok(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入档案名称。", parent=self)
            return
        mode = self.mode_var.get()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if mode == "dhcp":
            self.result = {
                "name": name, "mode": "dhcp",
                "ip": "", "mask": "", "gateway": "",
                "dns1": "", "dns2": "", "extra_ips": [],
                "saved_at": now,
            }
            self.destroy()
            return

        ip = self.ip_entry.get().strip()
        mask = self.mask_combo.get().strip()
        gw = self.gw_entry.get().strip()
        dns1 = self.dns1_entry.get().strip()
        dns2 = self.dns2_entry.get().strip()

        if not valid_ipv4(ip):
            messagebox.showerror("错误", "主 IP 格式不正确。", parent=self)
            return
        prefix = mask_to_prefix(mask)
        if prefix is None:
            messagebox.showerror("错误", "掩码不正确。", parent=self)
            return
        if gw and not valid_ipv4(gw):
            messagebox.showerror("错误", "网关格式不正确。", parent=self)
            return
        if dns1 and not valid_ipv4(dns1):
            messagebox.showerror("错误", "首选 DNS 格式不正确。", parent=self)
            return
        if dns2 and not valid_ipv4(dns2):
            messagebox.showerror("错误", "备用 DNS 格式不正确。", parent=self)
            return

        self.result = {
            "name": name, "mode": "static",
            "ip": ip, "mask": mask, "gateway": gw,
            "dns1": dns1, "dns2": dns2,
            "extra_ips": [{"ip": e["ip"], "mask": e["mask"]} for e in self.extra_ips],
            "saved_at": now,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------
class IpChangerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)

        # 自适应屏幕：窗口不超过屏幕的 90%，并居中
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(860, sw - 40)
        h = min(880, sh - 60)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 10)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(660, 540)

        self.configure(bg=BG)
        try:
            style = ttk.Style(self)
            style.theme_use("clam")

            # 全局
            style.configure(".", background=BG, foreground=TEXT,
                            font=("Microsoft YaHei UI", 9))
            style.configure("TFrame", background=BG)
            style.configure("TLabel", background=BG, foreground=TEXT)
            style.configure("Muted.TLabel", background=BG, foreground=MUTED)

            # 卡片式 LabelFrame（白色）
            style.configure("TLabelframe", background=CARD, bordercolor=BORDER,
                            relief="solid", borderwidth=1)
            style.configure("TLabelframe.Label", background=CARD,
                            foreground=PRIMARY,
                            font=("Microsoft YaHei UI", 9, "bold"))
            # 卡片内部控件（白色背景）
            style.configure("Card.TFrame", background=CARD)
            style.configure("Card.TLabel", background=CARD, foreground=TEXT)
            style.configure("Card.Muted.TLabel", background=CARD, foreground=MUTED)
            style.configure("Card.TRadiobutton", background=CARD, foreground=TEXT)
            style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT)

            # 普通按钮
            style.configure("TButton", background="#e2e8f0", foreground=TEXT,
                            bordercolor="#cbd5e1", focusthickness=0,
                            font=("Microsoft YaHei UI", 9), padding=3)
            style.map("TButton",
                      background=[("active", "#cbd5e1"),
                                  ("disabled", "#f1f5f9")],
                      foreground=[("disabled", "#94a3b8")])
            # 主按钮（蓝色）
            style.configure("Accent.TButton", background=PRIMARY,
                            foreground="white", bordercolor=PRIMARY,
                            font=("Microsoft YaHei UI", 9, "bold"), padding=4)
            style.map("Accent.TButton",
                      background=[("active", PRIMARY_DARK),
                                  ("disabled", "#93c5fd")],
                      foreground=[("disabled", "#eff6ff")])

            # 单选/复选（窗口背景）
            style.configure("TRadiobutton", background=BG, foreground=TEXT)
            style.configure("TCheckbutton", background=BG, foreground=TEXT)

            # Notebook：未选中又小又暗，选中又大又亮
            style.configure("TNotebook", background=BG, borderwidth=0,
                            tabmargins=(8, 6, 8, 0))
            style.configure("TNotebook.Tab", background="#d4dce9",
                            foreground=MUTED, padding=(12, 4),
                            font=("Microsoft YaHei UI", 9))
            style.map("TNotebook.Tab",
                      background=[("selected", PRIMARY), ("active", "#e7ecf4")],
                      foreground=[("selected", "#ffffff"), ("active", TEXT)],
                      padding=[("selected", (26, 9))],
                      font=[("selected", ("Microsoft YaHei UI", 11, "bold"))])

            # 输入框
            style.configure("TEntry", fieldbackground="white",
                            bordercolor=BORDER, lightcolor=BORDER,
                            darkcolor=BORDER, insertcolor=TEXT)
            style.configure("TCombobox", fieldbackground="white",
                            background="white", arrowcolor=PRIMARY,
                            bordercolor=BORDER, lightcolor=BORDER,
                            darkcolor=BORDER, insertcolor=TEXT)

            # Treeview
            style.configure("Treeview", background="white", fieldbackground="white",
                            foreground=TEXT, rowheight=24, bordercolor=BORDER,
                            borderwidth=1)
            style.configure("Treeview.Heading", background=HEADER_BG,
                            foreground="#334155",
                            font=("Microsoft YaHei UI", 9, "bold"),
                            borderwidth=1, relief="flat")
            style.map("Treeview",
                      background=[("selected", "#dbeafe")],
                      foreground=[("selected", "#1e40af")])
            style.map("Treeview.Heading", background=[("active", "#e2e8f0")])

            # 复选框：自定义指示器（选中显示对勾，而非 clam 默认的 ×）
            self._build_check_indicator(style)
        except Exception:
            pass

    def _build_check_indicator(self, style):
        s = 16

        def make(fill, border, check=None):
            img = tk.PhotoImage(width=s, height=s)
            img.put(fill, to=(0, 0, s - 1, s - 1))
            for i in range(s):
                img.put(border, (i, 0)); img.put(border, (i, s - 1))
                img.put(border, (0, i)); img.put(border, (s - 1, i))
            if check:
                def line(x0, y0, x1, y1):
                    dx, dy = x1 - x0, y1 - y0
                    steps = max(abs(dx), abs(dy))
                    for i in range(steps + 1):
                        x = round(x0 + dx * i / steps)
                        y = round(y0 + dy * i / steps)
                        for ox in (-1, 0):
                            for oy in (-1, 0):
                                xx, yy = x + ox, y + oy
                                if 0 <= xx < s and 0 <= yy < s:
                                    img.put(check, (xx, yy))
                line(3, 8, 6, 12)
                line(6, 12, 12, 4)
            return img

        img_off = make("#ffffff", BORDER)
        img_on = make(PRIMARY, PRIMARY_DARK, check="#ffffff")
        img_off_dis = make("#f1f5f9", "#cbd5e1")
        img_on_dis = make("#93c5fd", "#93c5fd", check="#eff6ff")
        # 保持引用，防止被垃圾回收
        self._check_imgs = [img_off, img_on, img_off_dis, img_on_dis]

        style.element_create(
            "Custom.checkindicator", "image", img_off,
            (("selected",), img_on),
            (("disabled",), img_off_dis),
            (("selected", "disabled"), img_on_dis),
        )
        style.layout("TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Custom.checkindicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w",
                                       "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])

        self.adapters = []
        self.profiles = load_profiles()
        self.extra_ips = []
        self._busy = False

        self._build_ui()

        if not is_admin():
            self._set_warn("当前不是管理员权限，无法修改 IP！请关闭后使用「启动工具.bat」以管理员身份运行（档案仍可编辑）。")
        else:
            self._set_warn("")

        self.refresh_adapters()
        self.refresh_profiles()
        self.refresh_routes()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # 顶部渐变横幅
        self.banner = tk.Canvas(self, height=76, highlightthickness=0, bd=0)
        self.banner.pack(fill="x")
        self.banner.bind("<Configure>", self._draw_banner)

        self.warn_var = tk.StringVar(value="")
        self.warn_label = tk.Label(
            self, textvariable=self.warn_var, fg="white", bg="#c0392b",
            font=("Microsoft YaHei UI", 9, "bold"), wraplength=760,
        )

        # 主体：标签页（IP 切换 / 路由管理）
        self.nb = ttk.Notebook(self)
        self.tab_ip = ttk.Frame(self.nb)
        self.tab_route = ttk.Frame(self.nb)
        self.nb.add(self.tab_ip, text="  IP 切换  ")
        self.nb.add(self.tab_route, text="  路由管理  ")
        self.nb.pack(fill="both", expand=True, padx=6, pady=4)

        # 1. 网卡选择
        frm_a = ttk.LabelFrame(self.tab_ip, text=" 网卡选择 ")
        frm_a.pack(fill="x", **pad)

        r1 = ttk.Frame(frm_a, style="Card.TFrame")
        r1.pack(fill="x", padx=6, pady=5)
        ttk.Label(r1, text="网卡：", style="Card.TLabel").pack(side="left")
        self.adapter_combo = ttk.Combobox(r1, state="readonly")
        self.adapter_combo.pack(side="left", fill="x", expand=True, padx=6)
        self.adapter_combo.bind("<<ComboboxSelected>>", lambda e: self._on_adapter_selected())
        self.btn_refresh = ttk.Button(r1, text="刷新", width=7, command=self.refresh_adapters)
        self.btn_refresh.pack(side="left")

        self.info_var = tk.StringVar(value="正在读取网卡……")
        ttk.Label(frm_a, textvariable=self.info_var, style="Card.TLabel",
                  foreground="#2c3e50", justify="left")\
            .pack(anchor="w", padx=8, pady=(0, 5))

        # 2. 可滚动区域（网卡选择固定；IP 设置 / 配置档案均可上下滚动翻看）
        scroll_holder = ttk.Frame(self.tab_ip)
        scroll_holder.pack(fill="both", expand=True, padx=6, pady=(0, 3))
        self.ip_canvas = tk.Canvas(scroll_holder, highlightthickness=0,
                                   bd=0, bg=BG)
        ip_vsb = ttk.Scrollbar(scroll_holder, orient="vertical",
                               command=self.ip_canvas.yview)
        self.ip_canvas.configure(yscrollcommand=ip_vsb.set)
        ip_vsb.pack(side="right", fill="y")
        self.ip_canvas.pack(side="left", fill="both", expand=True)

        self.scroll_inner = ttk.Frame(self.ip_canvas)
        self._ip_win = self.ip_canvas.create_window(
            (0, 0), window=self.scroll_inner, anchor="nw")
        self.scroll_inner.bind(
            "<Configure>",
            lambda e: self.ip_canvas.configure(
                scrollregion=self.ip_canvas.bbox("all")))
        self.ip_canvas.bind("<Configure>", self._on_ip_canvas_config)
        self.ip_canvas.bind("<Enter>",
                            lambda e: self.ip_canvas.bind_all(
                                "<MouseWheel>", self._on_ip_wheel))
        self.ip_canvas.bind("<Leave>",
                            lambda e: self.ip_canvas.unbind_all("<MouseWheel>"))

        # ---- IP 设置（横向分布，少占纵向空间）----
        frm_ip = ttk.LabelFrame(self.scroll_inner, text=" IP 设置 ")
        frm_ip.pack(fill="x", padx=2, pady=3)

        self.mode_var = tk.StringVar(value="dhcp")
        r2 = ttk.Frame(frm_ip, style="Card.TFrame")
        r2.pack(fill="x", padx=8, pady=(5, 2))
        ttk.Radiobutton(r2, text="自动获取 IP（DHCP）", variable=self.mode_var,
                        value="dhcp", command=self._toggle_mode,
                        style="Card.TRadiobutton").pack(side="left")
        ttk.Radiobutton(r2, text="使用下面的静态 IP", variable=self.mode_var,
                        value="static", command=self._toggle_mode,
                        style="Card.TRadiobutton").pack(side="left", padx=18)

        # 静态参数：横向两行
        self.frm_static = ttk.Frame(frm_ip, style="Card.TFrame")
        self.frm_static.pack(fill="x", padx=12, pady=3)

        rowA = ttk.Frame(self.frm_static, style="Card.TFrame")
        rowA.pack(fill="x", pady=2)
        ttk.Label(rowA, text="主 IP：", style="Card.TLabel").pack(side="left")
        self.ip_entry = ttk.Entry(rowA, width=14, font=("Consolas", 9))
        self.ip_entry.pack(side="left", padx=(2, 12))
        ttk.Label(rowA, text="掩码：", style="Card.TLabel").pack(side="left")
        self.mask_combo = ttk.Combobox(rowA, values=COMMON_MASKS, width=13)
        self.mask_combo.pack(side="left", padx=(2, 12))
        ttk.Label(rowA, text="网关：", style="Card.TLabel").pack(side="left")
        self.gw_entry = ttk.Entry(rowA, width=14, font=("Consolas", 9))
        self.gw_entry.pack(side="left", padx=(2, 0))

        rowB = ttk.Frame(self.frm_static, style="Card.TFrame")
        rowB.pack(fill="x", pady=2)
        ttk.Label(rowB, text="首选 DNS：", style="Card.TLabel").pack(side="left")
        self.dns1_entry = ttk.Entry(rowB, width=14, font=("Consolas", 9))
        self.dns1_entry.pack(side="left", padx=(2, 12))
        ttk.Label(rowB, text="备用 DNS：", style="Card.TLabel").pack(side="left")
        self.dns2_entry = ttk.Entry(rowB, width=14, font=("Consolas", 9))
        self.dns2_entry.pack(side="left", padx=(2, 0))

        # 附加 IP
        frm_extra = ttk.LabelFrame(frm_ip, text=" 附加 IP（同一网卡绑定多个 IP，可选） ")
        frm_extra.pack(fill="x", padx=12, pady=(3, 4))

        r_extra = ttk.Frame(frm_extra, style="Card.TFrame")
        r_extra.pack(fill="x", padx=6, pady=4)
        ttk.Label(r_extra, text="IP：", style="Card.TLabel").pack(side="left")
        self.extra_ip_entry = ttk.Entry(r_extra, width=14, font=("Consolas", 9))
        self.extra_ip_entry.pack(side="left", padx=(2, 6))
        ttk.Label(r_extra, text="掩码：", style="Card.TLabel").pack(side="left")
        self.extra_mask_combo = ttk.Combobox(r_extra, values=COMMON_MASKS, width=13)
        self.extra_mask_combo.pack(side="left", padx=2)
        self.extra_mask_combo.set("255.255.255.0")
        self.btn_extra_add = ttk.Button(r_extra, text="添加", width=5, command=self._add_extra)
        self.btn_extra_add.pack(side="left", padx=5)
        self.btn_extra_del = ttk.Button(r_extra, text="删除选中", width=8, command=self._del_extra)
        self.btn_extra_del.pack(side="left")

        extra_wrap = ttk.Frame(frm_extra, style="Card.TFrame")
        extra_wrap.pack(fill="x", padx=6, pady=(0, 4))
        self.extra_tree = ttk.Treeview(extra_wrap, columns=("ip", "mask"),
                                       show="headings", selectmode="browse", height=3)
        self.extra_tree.heading("ip", text="附加 IP 地址")
        self.extra_tree.heading("mask", text="子网掩码")
        self.extra_tree.column("ip", width=280, anchor="center")
        self.extra_tree.column("mask", width=240, anchor="center")
        extra_vsb = ttk.Scrollbar(extra_wrap, orient="vertical",
                                  command=self.extra_tree.yview)
        self.extra_tree.configure(yscrollcommand=extra_vsb.set)
        extra_vsb.pack(side="right", fill="y")
        self.extra_tree.pack(side="left", fill="both", expand=True)

        r3 = ttk.Frame(frm_ip, style="Card.TFrame")
        r3.pack(fill="x", padx=8, pady=(1, 6))
        self.btn_apply = ttk.Button(r3, text="应用配置", style="Accent.TButton",
                                   width=11, command=self._on_apply)
        self.btn_apply.pack(side="left")

        self.static_controls = [
            self.ip_entry, self.mask_combo, self.gw_entry,
            self.dns1_entry, self.dns2_entry,
            self.extra_ip_entry, self.extra_mask_combo,
            self.btn_extra_add, self.btn_extra_del, self.extra_tree,
        ]

        # 3. 档案
        frm_p = ttk.LabelFrame(self.scroll_inner,
                               text=" 配置档案（不绑定网卡；右键档案可编辑/应用/删除） ")
        frm_p.pack(fill="x", padx=2, pady=3)

        r4 = ttk.Frame(frm_p, style="Card.TFrame")
        r4.pack(fill="x", padx=6, pady=5)
        ttk.Label(r4, text="档案名称：", style="Card.TLabel").pack(side="left")
        self.prof_name_entry = ttk.Entry(r4, width=14)
        self.prof_name_entry.pack(side="left", padx=6)
        self.btn_save = ttk.Button(r4, text="保存/覆盖", width=9, command=self._on_save)
        self.btn_save.pack(side="left", padx=3)
        self.btn_apply_p = ttk.Button(r4, text="一键应用", style="Accent.TButton",
                                      width=9, command=self._on_apply_profile)
        self.btn_apply_p.pack(side="left", padx=3)
        self.btn_del = ttk.Button(r4, text="删除", width=7, command=self._on_delete)
        self.btn_del.pack(side="left", padx=3)
        ttk.Label(r4, text="（提示：在档案上点鼠标右键）", style="Card.Muted.TLabel")\
            .pack(side="left", padx=8)

        cols = ("name", "mode", "ip", "gw", "time")
        tree_wrap = ttk.Frame(frm_p, style="Card.TFrame")
        tree_wrap.pack(fill="x", padx=6, pady=(0, 4))
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings",
                                 selectmode="browse", height=8)
        self.tree.heading("name", text="档案名称")
        self.tree.heading("mode", text="模式")
        self.tree.heading("ip", text="IP（主 IP + 附加数量）")
        self.tree.heading("gw", text="网关")
        self.tree.heading("time", text="更新时间")
        self.tree.column("name", width=130, anchor="w")
        self.tree.column("mode", width=60, anchor="center")
        self.tree.column("ip", width=280, anchor="w")
        self.tree.column("gw", width=120, anchor="w")
        self.tree.column("time", width=130, anchor="center")
        # 右侧垂直滚动条
        prof_vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                                 command=self.tree.yview)
        self.tree.configure(yscrollcommand=prof_vsb.set)
        prof_vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="x")
        self.tree.bind("<Double-1>", lambda e: self._on_apply_profile())

        # 右键菜单
        self.ctx_menu = tk.Menu(self, tearoff=0)
        self.ctx_menu.add_command(label="编辑档案（修改 IP/掩码/网关等）", command=self._on_edit)
        self.ctx_menu.add_command(label="一键应用到当前网卡", command=self._on_apply_profile)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="删除档案", command=self._on_delete)
        self.tree.bind("<Button-3>", self._on_right_click)

        # 4. 日志
        frm_log = ttk.LabelFrame(self, text=" 操作日志 ")
        frm_log.pack(fill="x", **pad)
        self.log_text = tk.Text(
            frm_log, height=5, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", relief="flat", state="disabled",
        )
        self.log_text.pack(fill="x", padx=6, pady=4)

        self.action_buttons = [
            self.btn_apply, self.btn_save, self.btn_apply_p, self.btn_del,
        ]

        # 路由管理标签页
        self._build_route_tab()

    # ------------------------------------------------- 可滚动区域
    def _on_ip_canvas_config(self, event):
        # 让内部框架宽度跟随画布，保证横向填满
        self.ip_canvas.itemconfigure(self._ip_win, width=event.width)

    def _on_ip_wheel(self, event):
        self.ip_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------- 渐变横幅
    def _draw_banner(self, event=None):
        c = self.banner
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            return

        # 横向渐变：深蓝 → 主蓝 → 青
        stops = [(0x1e, 0x3a, 0x8a), (0x25, 0x63, 0xeb), (0x06, 0xb6, 0xd4)]
        for x in range(w):
            t = x / max(1, w - 1)
            if t < 0.5:
                k = t / 0.5
                a, b = stops[0], stops[1]
            else:
                k = (t - 0.5) / 0.5
                a, b = stops[1], stops[2]
            r = int(a[0] + (b[0] - a[0]) * k)
            g = int(a[1] + (b[1] - a[1]) * k)
            bl = int(a[2] + (b[2] - a[2]) * k)
            c.create_line(x, 0, x, h, fill="#%02x%02x%02x" % (r, g, bl))

        # 装饰：右侧网络节点 + 连线（科技感）
        import random
        random.seed(42)
        nodes = []
        for i in range(9):
            nx = w * 0.55 + random.random() * w * 0.42
            ny = 12 + random.random() * (h - 24)
            nodes.append((nx, ny))
        # 连线（每个节点连最近的 1-2 个）
        for i, (x1, y1) in enumerate(nodes):
            dists = sorted(
                (( (x2 - x1) ** 2 + (y2 - y1) ** 2, j)
                 for j, (x2, y2) in enumerate(nodes) if j != i))
            for d, j in dists[:2]:
                if d < (w * 0.16) ** 2:
                    c.create_line(x1, y1, nodes[j][0], nodes[j][1],
                                  fill="#ffffff", stipple="gray50", width=1)
        for (nx, ny) in nodes:
            c.create_oval(nx - 4, ny - 4, nx + 4, ny + 4,
                          fill="#ffffff", outline="")
            c.create_oval(nx - 8, ny - 8, nx + 8, ny + 8,
                          fill="", outline="#ffffff", stipple="gray75")

        # 标题文字
        c.create_text(22, h / 2 - 12, text="NetSwitch", anchor="w",
                      fill="#ffffff", font=("Segoe UI", 17, "bold"))
        c.create_text(24, h / 2 + 14, text="IP 快切 · 静态路由管理", anchor="w",
                      fill="#dbeafe", font=("Microsoft YaHei UI", 9))

    # ------------------------------------------------------- 路由标签页 UI
    def _build_route_tab(self):
        tab = self.tab_route

        # 顶部：筛选 + 刷新
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=6, pady=(6, 3))
        ttk.Label(top, text="网卡筛选：").pack(side="left")
        self.route_filter_combo = ttk.Combobox(top, state="readonly", width=30)
        self.route_filter_combo.pack(side="left", padx=6)
        self.route_filter_combo.bind("<<ComboboxSelected>>",
                                     lambda e: self._refresh_route_tree())
        self.route_static_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="仅显示静态路由（网关非 0.0.0.0）",
                        variable=self.route_static_only,
                        command=self._refresh_route_tree).pack(side="left", padx=8)
        self.btn_route_refresh = ttk.Button(top, text="刷新", width=7,
                                            command=self.refresh_routes)
        self.btn_route_refresh.pack(side="right")

        # 路由列表
        cols = ("dest", "mask", "gw", "iface", "metric", "kind")
        frm_list = ttk.LabelFrame(tab, text=" 路由表（永久 / 临时） ")
        frm_list.pack(fill="both", expand=True, padx=6, pady=3)
        self.route_tree = ttk.Treeview(frm_list, columns=cols, show="headings",
                                       selectmode="browse")
        self.route_tree.heading("dest", text="目标网络")
        self.route_tree.heading("mask", text="子网掩码")
        self.route_tree.heading("gw", text="网关（下一跳）")
        self.route_tree.heading("iface", text="网卡")
        self.route_tree.heading("metric", text="度量值")
        self.route_tree.heading("kind", text="类型")
        self.route_tree.column("dest", width=150, anchor="center")
        self.route_tree.column("mask", width=140, anchor="center")
        self.route_tree.column("gw", width=150, anchor="center")
        self.route_tree.column("iface", width=150, anchor="w")
        self.route_tree.column("metric", width=70, anchor="center")
        self.route_tree.column("kind", width=80, anchor="center")
        vsb = ttk.Scrollbar(frm_list, orient="vertical",
                            command=self.route_tree.yview)
        self.route_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.route_tree.pack(fill="both", expand=True, padx=(6, 0), pady=4)

        # 添加路由表单
        frm_add = ttk.LabelFrame(tab, text=" 添加静态路由 ")
        frm_add.pack(fill="x", padx=6, pady=(3, 4))

        g1 = ttk.Frame(frm_add, style="Card.TFrame")
        g1.pack(fill="x", padx=8, pady=4)
        ttk.Label(g1, text="目标网络：", style="Card.TLabel").pack(side="left")
        self.rt_dest_entry = ttk.Entry(g1, width=15, font=("Consolas", 9))
        self.rt_dest_entry.pack(side="left", padx=(2, 10))
        ttk.Label(g1, text="子网掩码：", style="Card.TLabel").pack(side="left")
        self.rt_mask_combo = ttk.Combobox(g1, values=ROUTE_MASKS, width=14,
                                          font=("Microsoft YaHei UI", 9))
        self.rt_mask_combo.pack(side="left", padx=(2, 10))
        self.rt_mask_combo.set("255.255.255.0")
        ttk.Label(g1, text="网关：", style="Card.TLabel").pack(side="left")
        self.rt_gw_entry = ttk.Entry(g1, width=15, font=("Consolas", 9))
        self.rt_gw_entry.pack(side="left", padx=(2, 10))

        g2 = ttk.Frame(frm_add, style="Card.TFrame")
        g2.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(g2, text="度量值：", style="Card.TLabel").pack(side="left")
        self.rt_metric_entry = ttk.Entry(g2, width=6, font=("Consolas", 9))
        self.rt_metric_entry.pack(side="left", padx=(2, 10))
        ttk.Label(g2, text="出接口网卡：", style="Card.TLabel").pack(side="left")
        self.rt_if_combo = ttk.Combobox(g2, state="readonly", width=30)
        self.rt_if_combo.pack(side="left", padx=(2, 10))
        self.rt_persist = tk.BooleanVar(value=True)
        ttk.Checkbutton(g2, text="永久路由（重启保留）",
                        variable=self.rt_persist,
                        style="Card.TCheckbutton").pack(side="left", padx=8)
        self.btn_route_add = ttk.Button(g2, text="添加路由", style="Accent.TButton",
                                        width=10, command=self._on_add_route)
        self.btn_route_add.pack(side="right")
        self.btn_route_del = ttk.Button(g2, text="删除选中路由", width=12,
                                        command=self._on_del_route)
        self.btn_route_del.pack(side="right", padx=6)

        self.routes = []
        self.route_buttons = [
            self.btn_route_refresh, self.btn_route_add, self.btn_route_del,
        ]

    # ------------------------------------------------------- 路由读取/显示
    def refresh_routes(self):
        if self._busy:
            return
        self.btn_route_refresh.configure(state="disabled")

        def task():
            try:
                routes, err = get_routes()
                self.after(0, self._update_routes, routes, err)
            except Exception as e:
                self.after(0, self._update_routes, [], f"读取路由出错：{e}")

        threading.Thread(target=task, daemon=True).start()

    def _update_routes(self, routes, err):
        self.routes = routes
        if err:
            self.log("读取路由失败：" + err[:300])
        # 网卡筛选下拉
        names = sorted({r["iface"] for r in routes if r["iface"]})
        filter_values = ["全部网卡"] + names
        self.route_filter_combo["values"] = filter_values
        if self.route_filter_combo.current() < 0:
            self.route_filter_combo.current(0)
        self._refresh_route_tree()
        self.btn_route_refresh.configure(state="normal")

    def _refresh_route_tree(self):
        for i in self.route_tree.get_children():
            self.route_tree.delete(i)

        fidx = self.route_filter_combo.current()
        if fidx < 0:
            fidx = 0
        values = self.route_filter_combo["values"]
        filter_iface = values[fidx] if fidx < len(values) else "全部网卡"
        static_only = self.route_static_only.get()

        for r in self.routes:
            if filter_iface != "全部网卡" and r["iface"] != filter_iface:
                continue
            if static_only and (not r["gw"] or r["gw"] == "0.0.0.0"):
                continue
            kind = "永久" if r["persist"] else "临时"
            self.route_tree.insert(
                "", "end",
                values=(r["dest"], r["mask"], r["gw"], r["iface"],
                        r["metric"], kind),
            )

    def _selected_route(self):
        item = self.route_tree.focus()
        if not item:
            return None
        vals = self.route_tree.item(item, "values")
        dest, mask, gw = vals[0], vals[1], vals[2]
        for r in self.routes:
            if (r["dest"] == dest and r["mask"] == mask
                    and r["gw"] == gw):
                return r
        return None

    # ------------------------------------------------------- 路由增删
    def _on_add_route(self):
        if self._busy:
            return
        if not is_admin():
            messagebox.showerror("权限不足", "需要管理员权限，请使用「启动工具.bat」运行。")
            return
        dest = self.rt_dest_entry.get().strip()
        mask = self.rt_mask_combo.get().strip()
        gw = self.rt_gw_entry.get().strip()
        metric = self.rt_metric_entry.get().strip()
        persist = self.rt_persist.get()

        if not valid_ipv4(dest):
            messagebox.showerror("配置错误", "目标网络格式不正确（示例：10.0.0.0）。")
            return
        if mask_to_prefix(mask) is None:
            messagebox.showerror("配置错误", "子网掩码不正确。")
            return
        if not valid_ipv4(gw):
            messagebox.showerror("配置错误", "网关格式不正确（示例：192.168.1.1）。")
            return
        if metric:
            if not metric.isdigit():
                messagebox.showerror("配置错误", "度量值必须是数字；不需要可留空。")
                return
        if_index = None
        if self.rt_if_combo.current() > 0:
            a = self._route_if_adapter()
            if a:
                if_index = a.get("ifIndex")

        kind = "永久" if persist else "临时"
        if not messagebox.askyesno(
            "确认",
            f"将添加{kind}路由：\n{dest} / {mask} → {gw}"
            + (f"\nmetric {metric}" if metric else "")
            + (f"\n出接口：{self.rt_if_combo.get()}" if if_index else "")
            + "\n是否继续？",
        ):
            return

        self._run_route_op(
            lambda: add_route(dest, mask, gw, metric, if_index,
                              persist, self.log))

    def _route_if_adapter(self):
        idx = self.rt_if_combo.current()
        values = self.rt_if_combo["values"]
        if idx <= 0 or idx >= len(values):
            return None
        # 下拉文本为 "名称 — 描述 [状态]"，按名称匹配
        text = values[idx]
        for a in self.adapters:
            if text.startswith(a["name"] + " "):
                return a
        return None

    def _on_del_route(self):
        if self._busy:
            return
        if not is_admin():
            messagebox.showerror("权限不足", "需要管理员权限，请使用「启动工具.bat」运行。")
            return
        r = self._selected_route()
        if not r:
            messagebox.showwarning("提示", "请先在列表中选中要删除的路由。")
            return
        kind = "永久" if r["persist"] else "临时"
        if not messagebox.askyesno(
            "确认",
            f"确定删除{kind}路由吗？\n{r['dest']} / {r['mask']} → {r['gw']}",
        ):
            return
        self._run_route_op(lambda: delete_route(r, self.log))

    def _run_route_op(self, op):
        self.set_busy(True)

        def task():
            try:
                ok, msg = op()
                if not ok:
                    self.log(msg)
                    self.after(0, lambda: messagebox.showerror("失败", msg))
                else:
                    self.log("路由操作完成。")
            except Exception as e:
                self.log(f"发生错误：{e}")
            finally:
                self.set_busy(False)
                self.after(800, self.refresh_routes)

        threading.Thread(target=task, daemon=True).start()

    # ------------------------------------------------------------ 小工具
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.after(0, self._append_log, f"[{ts}] {msg}")

    def _append_log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_warn(self, text):
        self.warn_var.set(text)
        if text:
            self.warn_label.pack(fill="x", padx=6, pady=(5, 0))
        else:
            self.warn_label.pack_forget()

    def set_busy(self, busy):
        self._busy = busy
        self.after(0, self._apply_busy, busy)

    def _apply_busy(self, busy):
        st = "disabled" if busy else "normal"
        for b in self.action_buttons:
            b.configure(state=st)
        self.btn_refresh.configure(state=st)
        self.adapter_combo.configure(state="disabled" if busy else "readonly")
        if hasattr(self, "route_buttons"):
            for b in self.route_buttons:
                b.configure(state=st)
            self.route_filter_combo.configure(state="disabled" if busy else "readonly")
            self.rt_if_combo.configure(state="disabled" if busy else "readonly")

    def selected_adapter(self):
        idx = self.adapter_combo.current()
        if 0 <= idx < len(self.adapters):
            return self.adapters[idx]
        return None

    def _toggle_mode(self):
        static = self.mode_var.get() == "static"
        for w in self.static_controls:
            set_widget_enabled(w, static)

    # ------------------------------------------------------------ 右键菜单
    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.ctx_menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------ 附加 IP
    def _all_used_ips(self):
        used = set()
        primary = self.ip_entry.get().strip()
        if primary:
            used.add(primary)
        for e in self.extra_ips:
            used.add(e["ip"])
        return used

    def _add_extra(self):
        ip = self.extra_ip_entry.get().strip()
        mask = self.extra_mask_combo.get().strip()
        if not valid_ipv4(ip):
            messagebox.showerror("格式错误", "请输入正确的附加 IP 地址。")
            return
        prefix = mask_to_prefix(mask)
        if prefix is None:
            messagebox.showerror("格式错误", "请选择正确的子网掩码。")
            return
        if ip in self._all_used_ips():
            messagebox.showwarning("重复", f"IP {ip} 已存在，不能重复添加。")
            return
        self.extra_ips.append({"ip": ip, "mask": mask, "prefix": prefix})
        self._refresh_extra_tree()
        self.extra_ip_entry.delete(0, "end")
        self.log(f"已添加附加 IP：{ip} / {mask}")

    def _del_extra(self):
        item = self.extra_tree.focus()
        if not item:
            messagebox.showwarning("提示", "请先选中一条附加 IP。")
            return
        ip = self.extra_tree.item(item, "values")[0]
        self.extra_ips = [e for e in self.extra_ips if e["ip"] != ip]
        self._refresh_extra_tree()
        self.log(f"已移除附加 IP：{ip}")

    def _refresh_extra_tree(self):
        for i in self.extra_tree.get_children():
            self.extra_tree.delete(i)
        for e in self.extra_ips:
            self.extra_tree.insert("", "end", values=(e["ip"], e["mask"]))

    def _set_extra_ips(self, extras):
        result = []
        for e in extras:
            ip = e.get("ip", "")
            mask = e.get("mask", "")
            prefix = e.get("prefix")
            if not mask and prefix is not None:
                mask = prefix_to_mask(prefix)
            if prefix is None:
                prefix = mask_to_prefix(mask)
            result.append({"ip": ip, "mask": mask, "prefix": prefix})
        self.extra_ips = result
        self._refresh_extra_tree()

    # ------------------------------------------------------------ 刷新网卡
    def refresh_adapters(self):
        if self._busy:
            return
        self.btn_refresh.configure(state="disabled")
        self.info_var.set("正在读取网卡……")

        def task():
            try:
                adapters, err = get_adapters()
                self.after(0, self._update_adapters, adapters, err)
            except Exception as e:
                self.after(0, self._update_adapters, [], f"读取网卡出错：{e}")

        threading.Thread(target=task, daemon=True).start()

    def _update_adapters(self, adapters, err):
        keep_desc = None
        cur = self.selected_adapter()
        if cur:
            keep_desc = cur["desc"]
        self.adapters = adapters

        if err:
            self.info_var.set("读取失败：" + err[:200])
            self.log("读取网卡失败：" + err[:300])
        else:
            adapter_labels = [
                f'{a["name"]}  —  {a["desc"]}  [{a["status"]}]' for a in adapters
            ]
            self.adapter_combo["values"] = adapter_labels
            # 路由出接口下拉（"自动" + 各网卡）
            if hasattr(self, "rt_if_combo"):
                self.rt_if_combo["values"] = ["自动（不指定）"] + adapter_labels
                if self.rt_if_combo.current() < 0:
                    self.rt_if_combo.current(0)
            sel = 0
            if keep_desc:
                for i, a in enumerate(adapters):
                    if a["desc"] == keep_desc:
                        sel = i
                        break
            else:
                for i, a in enumerate(adapters):
                    if a["status"] == "Up" and a.get("gateway"):
                        sel = i
                        break
            if adapters:
                self.adapter_combo.current(sel)
                self._fill_from_adapter(adapters[sel])
            else:
                self.info_var.set("未发现可配置的网卡。")
        self.btn_refresh.configure(state="normal")

    def _fill_from_adapter(self, a):
        ips = a.get("ips", [])
        if ips:
            primary = ips[0]
            extras = ips[1:]
        else:
            primary = None
            extras = []

        dns = a.get("dns") or []
        dns1 = dns[0] if len(dns) >= 1 else ""
        dns2 = dns[1] if len(dns) >= 2 else ""
        mode = "dhcp" if a.get("dhcp") == "Enabled" else "static"

        self.mode_var.set(mode)
        self._set_entry(self.ip_entry, primary["ip"] if primary else "")
        self._set_combo(self.mask_combo,
                        prefix_to_mask(primary["prefix"]) if primary else "")
        self._set_entry(self.gw_entry, a.get("gateway", ""))
        self._set_entry(self.dns1_entry, dns1)
        self._set_entry(self.dns2_entry, dns2)
        self._set_extra_ips(extras)
        self._toggle_mode()

        if ips:
            ip_text = ", ".join(f'{x["ip"]}/{x["prefix"]}' for x in ips)
        else:
            ip_text = "无 IP"
        dns_text = ", ".join(dns) if dns else "无"
        self.info_var.set(
            f'{a["name"]} | {a["status"]} | {"DHCP" if mode == "dhcp" else "静态"}\n'
            f'IP（{len(ips)} 个）：{ip_text}\n'
            f'网关：{a.get("gateway", "无")}  DNS：{dns_text}'
        )

    def _on_adapter_selected(self):
        a = self.selected_adapter()
        if a:
            self._fill_from_adapter(a)

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, value or "")

    def _set_combo(self, combo, value):
        combo.set(value or "")

    # ------------------------------------------------------------ 读取表单
    def read_form(self):
        mode = self.mode_var.get()
        if mode == "dhcp":
            return "dhcp", {}, ""

        ip = self.ip_entry.get().strip()
        mask = self.mask_combo.get().strip()
        gw = self.gw_entry.get().strip()
        dns1 = self.dns1_entry.get().strip()
        dns2 = self.dns2_entry.get().strip()

        if not valid_ipv4(ip):
            return None, None, "主 IP 格式不正确（示例：192.168.1.50）"
        prefix = mask_to_prefix(mask)
        if prefix is None:
            return None, None, "子网掩码不正确（示例：255.255.255.0）"
        if gw and not valid_ipv4(gw):
            return None, None, "默认网关格式不正确；不需要可留空"
        if dns1 and not valid_ipv4(dns1):
            return None, None, "首选 DNS 格式不正确；不需要可留空"
        if dns2 and not valid_ipv4(dns2):
            return None, None, "备用 DNS 格式不正确；不需要可留空"

        data = {
            "ip": ip, "mask": mask, "prefix": prefix,
            "gateway": gw, "dns1": dns1, "dns2": dns2,
            "extra_ips": list(self.extra_ips),
        }
        if not gw:
            return "static", data, "NO_GW"
        return "static", data, ""

    # ------------------------------------------------------------ 应用
    def _on_apply(self):
        if self._busy:
            return
        if not is_admin():
            messagebox.showerror("权限不足", "需要管理员权限，请使用「启动工具.bat」运行。")
            return
        a = self.selected_adapter()
        if not a:
            messagebox.showwarning("提示", "请先选择网卡。")
            return

        mode, data, err = self.read_form()
        if err and err != "NO_GW":
            messagebox.showerror("配置错误", err)
            return
        if err == "NO_GW":
            if not messagebox.askyesno("确认", "未填写默认网关，将无法访问外网（仅局域网），是否继续？"):
                return

        n_extra = len(data.get("extra_ips", [])) if mode == "static" else 0
        if mode == "dhcp":
            desc = "切换为 DHCP 自动获取"
        else:
            desc = (f'主 {data["ip"]}（掩码 {data["mask"]}，网关 '
                    f'{data["gateway"] or "无"}），附加 {n_extra} 个')
        if not messagebox.askyesno("确认", f'网卡「{a["name"]}」将{desc}，是否继续？'):
            return

        self._run_change(a, mode, data)

    def _run_change(self, adapter, mode, data):
        self.set_busy(True)
        if mode == "dhcp":
            self.log(f'网卡「{adapter["name"]}」→ DHCP …')
            worker = lambda: apply_dhcp(adapter["name"], self.log)
        else:
            self.log(f'网卡「{adapter["name"]}」→ 静态 {data["ip"]}，'
                     f'附加 {len(data.get("extra_ips", []))} 个 …')
            worker = lambda: apply_static(
                adapter["name"], data["ip"], data["mask"],
                data.get("gateway", ""), data.get("dns1", ""),
                data.get("dns2", ""), data.get("extra_ips", []), self.log)

        def task():
            try:
                ok, msg = worker()
                if not ok:
                    self.log(msg)
                    self.after(0, lambda: messagebox.showerror("失败", msg))
                else:
                    self.log("配置流程完成。")
            except Exception as e:
                self.log(f"发生错误：{e}")
            finally:
                self.set_busy(False)
                self.after(2000, self._refresh_after)

        threading.Thread(target=task, daemon=True).start()

    def _refresh_after(self):
        def task():
            try:
                adapters, err = get_adapters()
                self.after(0, self._update_adapters, adapters, err)
            except Exception as e:
                self.log(f"刷新失败：{e}")
        threading.Thread(target=task, daemon=True).start()

    # ------------------------------------------------------------ 档案
    def refresh_profiles(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for p in self.profiles:
            if p.get("mode") == "static":
                mode = "静态"
                n_extra = len(p.get("extra_ips", []))
                ip = f'{p.get("ip", "")} / {p.get("mask", "")}'
                if n_extra:
                    ip += f"（+{n_extra}）"
            else:
                mode = "DHCP"
                ip = "自动获取"
            self.tree.insert(
                "", "end",
                values=(p.get("name", ""), mode, ip,
                        p.get("gateway", ""), p.get("saved_at", "")),
            )

    def _on_save(self):
        if self._busy:
            return
        name = self.prof_name_entry.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入档案名称。")
            return
        mode, data, err = self.read_form()
        if err and err != "NO_GW":
            messagebox.showerror("配置错误", err)
            return

        if mode == "dhcp":
            record = {
                "name": name, "mode": "dhcp",
                "ip": "", "mask": "", "gateway": "",
                "dns1": "", "dns2": "", "extra_ips": [],
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        else:
            record = {
                "name": name, "mode": "static",
                "ip": data["ip"], "mask": data["mask"],
                "gateway": data.get("gateway", ""),
                "dns1": data.get("dns1", ""), "dns2": data.get("dns2", ""),
                "extra_ips": [
                    {"ip": e["ip"], "mask": e["mask"]}
                    for e in data.get("extra_ips", [])
                ],
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }

        for p in self.profiles:
            if p.get("name") == name:
                if not messagebox.askyesno("确认覆盖", f"档案「{name}」已存在，是否覆盖？"):
                    return
                p.update(record)
                save_profiles(self.profiles)
                self.refresh_profiles()
                self.log(f"已覆盖档案「{name}」")
                return

        self.profiles.append(record)
        save_profiles(self.profiles)
        self.refresh_profiles()
        self.log(f"已保存档案「{name}」")

    def _selected_profile(self):
        item = self.tree.focus()
        if not item:
            return None
        name = self.tree.item(item, "values")[0]
        for p in self.profiles:
            if p.get("name") == name:
                return p
        return None

    def _on_edit(self):
        """右键编辑：弹出独立小窗口，确定后回写档案。"""
        prof = self._selected_profile()
        if not prof:
            messagebox.showwarning("提示", "请先选择档案。")
            return

        old_name = prof.get("name", "")
        dlg = ProfileEditDialog(self, prof)
        self.wait_window(dlg)
        result = dlg.result
        if not result:
            return

        new_name = result.get("name", "")
        # 名称未改：替换原记录；名称改了：若新名称已存在则提示，否则重命名
        found = False
        for i, p in enumerate(self.profiles):
            if p.get("name") == old_name:
                if new_name != old_name and any(x.get("name") == new_name for x in self.profiles):
                    messagebox.showerror("重命名失败", f"已存在名为「{new_name}」的档案。")
                    return
                self.profiles[i] = result
                found = True
                break
        if not found:
            self.profiles.append(result)
        save_profiles(self.profiles)
        self.refresh_profiles()
        self.log(f'已更新档案「{new_name}」')

    def _on_apply_profile(self):
        if self._busy:
            return
        if not is_admin():
            messagebox.showerror("权限不足", "需要管理员权限，请使用「启动工具.bat」运行。")
            return
        a = self.selected_adapter()
        if not a:
            messagebox.showwarning("提示", "请先在上方选择要应用到哪张网卡。")
            return
        prof = self._selected_profile()
        if not prof:
            messagebox.showwarning("提示", "请先选择一个档案。")
            return

        if prof.get("mode") == "dhcp":
            mode, data = "dhcp", {}
            desc = "DHCP 自动获取"
        else:
            mode = "static"
            mask = prof.get("mask", "")
            extras = [{
                "ip": e["ip"], "mask": e.get("mask", ""),
                "prefix": mask_to_prefix(e.get("mask", "")),
            } for e in prof.get("extra_ips", [])]
            data = {
                "ip": prof["ip"], "mask": mask,
                "prefix": mask_to_prefix(mask),
                "gateway": prof.get("gateway", ""),
                "dns1": prof.get("dns1", ""), "dns2": prof.get("dns2", ""),
                "extra_ips": extras,
            }
            desc = f'静态 {prof["ip"]} + {len(extras)} 个附加'

        if not messagebox.askyesno(
            "一键应用",
            f'档案：{prof["name"]}\n应用到：{a["name"]}\n配置：{desc}\n\n是否继续？',
        ):
            return

        self._run_change(a, mode, data)

    def _on_delete(self):
        if self._busy:
            return
        prof = self._selected_profile()
        if not prof:
            messagebox.showwarning("提示", "请先选择要删除的档案。")
            return
        if messagebox.askyesno("确认", f'确定删除档案「{prof["name"]}」吗？'):
            self.profiles = [p for p in self.profiles if p.get("name") != prof["name"]]
            save_profiles(self.profiles)
            self.refresh_profiles()
            self.log(f'已删除档案「{prof["name"]}」')


def main():
    app = IpChangerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
