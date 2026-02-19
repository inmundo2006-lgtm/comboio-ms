import streamlit as st
import requests
import pandas as pd
from datetime import datetime, date
import time
import os

# ==========================
# CONFIGURAÇÕES DO APLICATIVO
# ==========================

TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]

GRAPH_URL = "https://graph.microsoft.com/v1.0"

CAPACIDADE_MAXIMA = 15000

# ==========================
# USUÁRIOS E LISTAS
# ==========================
USUARIOS = {
    "central": {"senha": "central@123", "lista": "9c32dccb-c6e2-4154-a391-e9a493d49bec"},
    "roraima": {"senha": "roraima@123", "lista": "936bf167-ff54-4031-a267-20faa46a1eee"},
    "helicoptero": {"senha": "helico@123", "lista": "0172a697-5094-4495-96d0-25d4f8dddbcb"},
    "cianorte": {"senha": "cianorte@123", "lista": "d11dc55c-31ff-4c81-bed0-27df39a99bf9"},
    "navirai": {"senha": "navirai@123", "lista": "262f461c-9758-484c-b701-e71f2ade1f3e"},
    "maracaju": {"senha": "maracaju@123", "lista": "f67cc033-80fc-4fef-a859-497676b0b539"},
    "reserva": {"senha": "reserva@123", "lista": "31df8ece-779f-4ca5-a1b6-3bf0e46ffd6f"}
}

ARQUIVO_LOGO = "logo_ms.png"
ARQUIVO_VIDEO = "abertura.mp4"

# ==========================
# FUNÇÕES DE APOIO
# ==========================

def calcular_diferenca_odometro(inicial, final):
    try:
        inicial, final = float(inicial), float(final)
        return final - inicial if final >= inicial else (100000 - inicial) + final
    except:
        return 0.0

def prever_odometro_final(inicial, litros):
    soma = inicial + litros
    return soma - 100000 if soma > 99999 else soma

@st.cache_data(ttl=60)
def obter_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        return r.json().get("access_token")
    except:
        return None

def obter_dados_sharepoint(token, LIST_ID):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items?expand=fields&$orderby=fields/Created desc&$top=2000"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers)
        return [item['fields'] for item in r.json().get('value', [])]
    except:
        return []

def enviar_dados_sharepoint(token, LIST_ID, dados):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "fields": {
            "Title": f"{dados['Tipo_Operacao']} - {dados.get('Frota', 'Tanque')}",
            "Tipo_Operacao": dados['Tipo_Operacao'],
            "Litros": float(dados['Litros']),
            "Frota": dados.get('Frota', ""),
            "Horas_Motor": float(dados.get('Horas_Motor', 0)),
            "Comboio_Final": float(dados.get('Comboio_Final', 0)),
            "Comboio_Inicial": float(dados.get('Comboio_Inicial', 0)),
            "Entrada_Usina": float(dados.get('Entrada_Usina', 0))
        }
    }
    try:
        requests.post(url, headers=headers, json=payload).raise_for_status()
        return True
    except:
        return False

# ==========================
# DESIGN E LOGIN
# ==========================

st.set_page_config(page_title="Gestão de Comboio", page_icon="🚛", layout="wide")

st.markdown("""
<style>
    .card-stock { padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px; }
    .big-font { font-size: 40px; font-weight: bold; }
    .stVideo { border-radius: 15px; width: 100%; max-height: 450px; box-shadow: 0px 4px 15px rgba(0,0,0,0.1); }
</style>
""", unsafe_allow_html=True)

if 'logado' not in st.session_state:
    st.session_state['logado'] = False

# --- TELA DE LOGIN ---
if not st.session_state['logado']:
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if os.path.exists(ARQUIVO_LOGO):
            st.image(ARQUIVO_LOGO, width=250)

        st.markdown("<h3 style='text-align: center; color: #333;'>Sistema de Gestão de Comboio</h3>", unsafe_allow_html=True)

        if os.path.exists(ARQUIVO_VIDEO):
            st.video(ARQUIVO_VIDEO, autoplay=True, loop=True, muted=True)

        st.divider()
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")

        if st.button("ACESSAR", type="primary", use_container_width=True):
            if u in USUARIOS and s == USUARIOS[u]["senha"]:
                st.session_state['logado'] = True
                st.session_state['usuario'] = u
                st.session_state['LIST_ID'] = USUARIOS[u]["lista"]
                st.rerun()
            else:
                st.error("❌ Usuário ou senha inválidos!")
    st.stop()

# ==========================
# SISTEMA PRINCIPAL
# ==========================

LIST_ID = st.session_state["LIST_ID"]

with st.sidebar:
    if os.path.exists(ARQUIVO_LOGO):
        st.image(ARQUIVO_LOGO, width=150)
    st.markdown("---")
    st.write(f"Usuário: **{st.session_state['usuario']}**")
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state['logado'] = False
        st.rerun()

st.title("🚛 Controle de Frotas e Abastecimento")

token = obter_token()
if not token:
    st.error("Erro de Conexão")
    st.stop()

dados_sp = obter_dados_sharepoint(token, LIST_ID)
colunas_esperadas = ['Tipo_Operacao', 'Litros', 'Frota', 'Horas_Motor', 'Comboio_Final', 'Comboio_Inicial', 'Created', 'Entrada_Usina']

if not dados_sp:
    df = pd.DataFrame(columns=colunas_esperadas)
else:
    df = pd.DataFrame(dados_sp)
    for col in colunas_esperadas:
        if col not in df.columns:
            df[col] = 0

saldo, ult_fim = 0, 0
if not df.empty and 'Created' in df.columns and len(dados_sp) > 0:
    df['Data_Dt'] = pd.to_datetime(df['Created']).dt.date
    df['Hora'] = pd.to_datetime(df['Created']).dt.strftime('%H:%M')
    try:
        ult_fim = float(df.iloc[0]['Comboio_Final'])
    except:
        ult_fim = 0
    ent = pd.to_numeric(df[df['Tipo_Operacao'] == 'Entrada']['Litros'], errors='coerce').sum()
    sai = pd.to_numeric(df[df['Tipo_Operacao'] == 'Saida']['Litros'], errors='coerce').sum()
    saldo = ent - sai
else:
    saldo, ult_fim = 0, 0

aba1, aba2, aba3 = st.tabs(["⛽ Abastecer", "📥 Entrada Usina", "📊 Fechamento"])

# === ABA 1: SAÍDA ===
with aba1:
    st.subheader("Registrar Saída")
    with st.form("f_saida", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            f = st.text_input("Frota")
            h = st.number_input("Horímetro Atual", min_value=0.0)
            l = st.number_input("Litros Abastecidos", min_value=0.0, step=1.0)
        with c2:
            st.info(f"Relógio Inicial: **{ult_fim:05.0f}**")
            sug = prever_odometro_final(ult_fim, l)
            st.caption(f"💡 Sugestão Relógio: {sug:.0f}")
            f_od = st.number_input("Relógio Final (Lido)", format="%.0f", min_value=0.0)

            if f_od > 0:
                dif = calcular_diferenca_odometro(ult_fim, f_od)
                if abs(dif - l) > 2:
                    st.warning("⚠️ Divergência no relógio mecânico!")

        if st.form_submit_button("💾 Salvar Registro", type="primary", use_container_width=True):

            # 🚨 BLOQUEIO DE ESTOQUE NEGATIVO
            if l > saldo:
                st.error(f"❌ Estoque insuficiente! Saldo atual: {saldo:.0f} L")
                st.stop()

            if f and l > 0 and f_od > 0:
                with st.spinner("Enviando..."):
                    if enviar_dados_sharepoint(token, LIST_ID, {
                        "Tipo_Operacao": "Saida",
                        "Frota": f,
                        "Litros": l,
                        "Horas_Motor": h,
                        "Comboio_Inicial": ult_fim,
                        "Comboio_Final": f_od
                    }):
                        st.success("✅ Registrado com sucesso!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.error("❌ Preencha todos os campos corretamente.")

# === ABA 2: ENTRADA ===
with aba2:
    st.subheader("Carga do Tanque (Usina)")
    esp = CAPACIDADE_MAXIMA - saldo
    st.info(f"Espaço disponível no tanque: **{esp:,.0f} L**")
    with st.form("f_ent", clear_on_submit=True):
        le = st.number_input("Quantidade Recebida (L)", min_value=0.0)
        o = st.text_input("Observação / NF")
        if st.form_submit_button("📥 Confirmar Entrada", use_container_width=True):
            if 0 < le <= esp:
                if enviar_dados_sharepoint(token, LIST_ID, {
                    "Tipo_Operacao": "Entrada",
                    "Litros": le,
                    "Entrada_Usina": le,
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": ult_fim
                }):
                    st.success("✅ Estoque Atualizado!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("Quantidade inválida ou acima da capacidade do tanque.")

# === ABA 3: DASHBOARD ===
with aba3:
    st.header("Conferência do Dia")
    ds = st.date_input("Filtrar Data", datetime.today())
    df_d = df[df['Data_Dt'] == ds] if not df.empty and 'Data_Dt' in df.columns else pd.DataFrame(columns=colunas_esperadas)

    s_sis = pd.to_numeric(df_d[df_d['Tipo_Operacao'] == 'Saida']['Litros'], errors='coerce').sum()
    s_mec = sum(calcular_diferenca_odometro(r.get('Comboio_Inicial', 0), r.get('Comboio_Final', 0))
                for _, r in df_d[df_d['Tipo_Operacao'] == 'Saida'].iterrows())
    div = s_mec - s_sis

    cor = "#28a745" if saldo > 5000 else "#ffc107" if saldo > 2000 else "#dc3545"
    st.markdown(
        f'<div style="background-color: {cor};" class="card-stock"><h2>{saldo:,.0f} L</h2>Estoque Disponível</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)
    col1.metric(f"Total Lançado ({ds.strftime('%d/%m')})", f"{s_sis:,.0f} L")
    col2.metric("Diferença (Mecânico vs Sistema)", f"{div:,.0f} L",
                delta="⚠️ Verificar" if abs(div) > 5 else "✅ OK")

    if not df_d.empty:
        st.subheader("Relatório de Movimentação")
        st.dataframe(df_d[['Hora', 'Frota', 'Litros', 'Comboio_Final']],
                     use_container_width=True, hide_index=True)
