import streamlit as st
import pandas as pd
import ipaddress
import io
import math
import secrets
import string

# --- LOGIC ---

def get_host_bits(hosts: int) -> int:
    bits = 2
    while (1 << bits) - 2 < hosts:
        bits += 1
    return bits

def generate_strong_password(length=16):
    upper = secrets.choice(string.ascii_uppercase)
    lower = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    special = secrets.choice("!@#$%^&*()-_=+[]{}|;:,.<>?")
    remaining = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?") for _ in range(length - 4))
    pwd = list(upper + lower + digit + special + remaining)
    secrets.SystemRandom().shuffle(pwd)
    return ''.join(pwd)

def find_suitable_base(reqs, mode="VLSM"):
    if not reqs:
        return ipaddress.ip_network("10.0.0.0/24")
        
    if mode == "VLSM":
        total_ips_needed = sum(1 << get_host_bits(req['Hosts']) for req in reqs)
    else:
        max_hosts = max(req['Hosts'] for req in reqs)
        size_per_subnet = 1 << get_host_bits(max_hosts)
        total_ips_needed = size_per_subnet * len(reqs)
        
    bits_needed = 0
    while (1 << bits_needed) < total_ips_needed:
        bits_needed += 1
        
    required_prefix = 32 - bits_needed
    
    if required_prefix < 8:
        raise ValueError(f"Requirements are too massive for private IP space (needs /{required_prefix}).")
        
    return ipaddress.ip_network(f"10.0.0.0/{required_prefix}", strict=False)


def calculate_vlsm(base_net: ipaddress.IPv4Network, reqs: list):
    # Sort descending by hosts
    reqs = sorted(reqs, key=lambda x: x['Hosts'], reverse=True)
    
    cursor = int(base_net.network_address)
    end = int(base_net.broadcast_address)
    
    results = []
    for req in reqs:
        bits = get_host_bits(req['Hosts'])
        prefix = 32 - bits
        size = 1 << bits
        
        if prefix < base_net.prefixlen:
            raise ValueError(f"Base network (/{base_net.prefixlen}) is too small to fit the requirement of {req['Hosts']} hosts (needs /{prefix}).")
            
        # align cursor
        if cursor % size != 0:
            cursor += size - (cursor % size)
            
        if cursor + size - 1 > end:
            raise ValueError(f"Address space exhausted before allocating '{req['Name']}'")
            
        net = ipaddress.ip_network((cursor, prefix), strict=True)
        results.append({
            "Name": req['Name'],
            "Requested Hosts": req['Hosts'],
            "Allocated Network": net,
        })
        cursor += size
        
    return results

def calculate_flsm(base_net: ipaddress.IPv4Network, reqs: list):
    max_hosts = max(req['Hosts'] for req in reqs)
    bits = get_host_bits(max_hosts)
    prefix = 32 - bits
    
    if prefix < base_net.prefixlen:
        raise ValueError(f"Base network (/{base_net.prefixlen}) is too small to fit the largest subnet (needs /{prefix}).")
        
    subnets = list(base_net.subnets(new_prefix=prefix))
    if len(subnets) < len(reqs):
        raise ValueError(f"Base network cannot be split into {len(reqs)} subnets of size /{prefix}.")
        
    results = []
    for i, req in enumerate(reqs):
        results.append({
            "Name": req['Name'],
            "Requested Hosts": req['Hosts'],
            "Allocated Network": subnets[i],
        })
    return results

def get_supernet(networks):
    if not networks:
        return None
    return ipaddress.collapse_addresses(networks)

# --- UI ---

st.set_page_config(page_title="NetPlanner Pro", layout="wide", page_icon="🌐")

st.markdown("""
<style>
    .metric-card {
        background-color: #1e1e1e;
        border: 1px solid #333;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
    }
    h1, h2, h3 {
        color: #4a90e2;
    }
</style>
""", unsafe_allow_html=True)

st.title("🌐 NetPlanner Professional")
st.markdown("Advanced Subnetting & Supernetting Tool (Auto-Scaling Base Network)")

with st.sidebar:
    st.header("⚙️ Configuration")
    mode_str = st.radio("Allocation Mode", ["VLSM (Variable Length)", "FLSM (Fixed Length)"], 
                    help="VLSM sizes each subnet to fit. FLSM makes all subnets the same size.")
    mode = "VLSM" if "VLSM" in mode_str else "FLSM"
    start_net = st.text_input("Base Network (Optional)", "", placeholder="e.g. 192.168.1.0/24", help="Leave blank to auto-assign a perfectly sized network.")
    st.markdown("---")
    st.markdown("💡 **Tip**: Add rows dynamically in the table using the `+` icon at the bottom, or select rows and press `Delete`.")

st.subheader("🏢 Subnet Requirements")

if "req_data_v3" not in st.session_state:
    st.session_state.req_data_v3 = pd.DataFrame([
        {"Subnet Name": "", "Hosts Required": None},
        {"Subnet Name": "", "Hosts Required": None},
        {"Subnet Name": "", "Hosts Required": None},
    ])

edited_df = st.data_editor(
    st.session_state.req_data_v3,
    num_rows="dynamic",
    use_container_width=True,
    key="req_editor",
    column_config={
        "Subnet Name": st.column_config.TextColumn("Subnet Name", required=True),
        "Hosts Required": st.column_config.NumberColumn("Hosts Required", min_value=1, step=1, required=True),
    }
)

if st.button("🚀 Generate Architecture", type="primary", use_container_width=True):
    try:
        reqs = []
        for idx, row in edited_df.iterrows():
            name = row.get("Subnet Name")
            hosts = row.get("Hosts Required")
            if pd.isna(name) or pd.isna(hosts) or not str(name).strip():
                continue
            reqs.append({"Name": str(name).strip(), "Hosts": int(hosts)})
            
        if not reqs:
            st.warning("Please add at least one valid subnet requirement with a Name and Hosts Required.")
            st.stop()
            
        if start_net.strip():
            try:
                base_network = ipaddress.ip_network(start_net.strip(), strict=False)
            except ValueError:
                st.error(f"Invalid Base Network format: '{start_net}'. Please use CIDR notation (e.g. 10.0.0.0/16).")
                st.stop()
        else:
            base_network = find_suitable_base(reqs, mode)
        
        if mode == "VLSM":
            allocated = calculate_vlsm(base_network, reqs)
        else:
            allocated = calculate_flsm(base_network, reqs)
            
        res_table = []
        network_objs = []
        for a in allocated:
            net = a["Allocated Network"]
            network_objs.append(net)
            usable = net.num_addresses - 2 if net.prefixlen <= 30 else (2 if net.prefixlen == 31 else 1)
            
            first_ip = net.network_address + 1 if net.prefixlen <= 30 else net.network_address
            last_ip = net.broadcast_address - 1 if net.prefixlen <= 30 else net.broadcast_address
            
            res_table.append({
                "Name": a["Name"],
                "Requested": a["Requested Hosts"],
                "Network Address": str(net.network_address),
                "CIDR": f"/{net.prefixlen}",
                "Subnet Mask": str(net.netmask),
                "Usable Range": f"{first_ip} - {last_ip}",
                "Gateway (First IP)": str(first_ip),
                "Broadcast": str(net.broadcast_address),
                "Total Usable": usable,
                "Utilization": f"{(a['Requested Hosts'] / usable * 100):.1f}%" if usable > 0 else "N/A"
            })
            
        res_df = pd.DataFrame(res_table)
        
        supernets = list(get_supernet(network_objs))
        
        st.markdown("---")
        st.header("📊 Network Plan")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mode", mode)
        c2.metric("Base Network", str(base_network))
        c3.metric("Total Subnets", len(res_table))
        c4.metric("Total Hosts Requested", sum(r['Hosts'] for r in reqs))
        
        if supernets:
            st.subheader("🔗 Supernet (Route Summarization)")
            st.info(f"The optimally summarized route for all allocated subnets is: **{', '.join(str(s) for s in supernets)}**")
        
        st.dataframe(res_df, use_container_width=True, hide_index=True)
        
        # --- User IP Assignment Section ---
        st.markdown("---")
        st.header("👥 User IP Assignments")
        st.caption("Each usable IP is assigned to a user with a unique strong password.")
        
        all_user_dfs = {}
        for a in allocated:
            net = a["Allocated Network"]
            name = a["Name"]
            requested = a["Requested Hosts"]
            
            if net.prefixlen <= 30:
                first_ip = net.network_address + 1
                last_ip = net.broadcast_address - 1
            elif net.prefixlen == 31:
                first_ip = net.network_address
                last_ip = net.broadcast_address
            else:
                first_ip = net.network_address
                last_ip = net.network_address
            
            user_rows = []
            ip_int = int(first_ip)
            end_int = int(last_ip)
            user_num = 1
            while ip_int <= end_int and user_num <= requested:
                user_rows.append({
                    "User": f"User {user_num}",
                    "IP Address": str(ipaddress.IPv4Address(ip_int)),
                    "Password": generate_strong_password(),
                })
                ip_int += 1
                user_num += 1
            
            user_df = pd.DataFrame(user_rows)
            all_user_dfs[name] = user_df
            
            with st.expander(f"📋 {name} — {requested} Users ({first_ip} → {last_ip})", expanded=False):
                st.dataframe(user_df, use_container_width=True, hide_index=True, height=min(400, 35 * len(user_rows) + 38))
        
        # --- Export ---
        st.markdown("---")
        col1, col2 = st.columns(2)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            res_df.to_excel(writer, index=False, sheet_name='Subnet Plan')
            for sheet_name, udf in all_user_dfs.items():
                safe_name = sheet_name[:31]  # Excel sheet name max 31 chars
                udf.to_excel(writer, index=False, sheet_name=safe_name)
        excel_data = output.getvalue()
        
        col1.download_button("⬇️ Export to Excel (.xlsx)", excel_data, "network-architecture.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        
        csv_parts = ["=== Subnet Plan ===\n", res_df.to_csv(index=False), "\n"]
        for sname, udf in all_user_dfs.items():
            csv_parts.append(f"\n=== {sname} - User Assignments ===\n")
            csv_parts.append(udf.to_csv(index=False))
            csv_parts.append("\n")
        csv_data = ''.join(csv_parts).encode('utf-8')
        col2.download_button("⬇️ Export to CSV", csv_data, "network-architecture.csv", "text/csv", use_container_width=True)
            
    except Exception as e:
        st.error(f"Error generating plan: {e}")
