import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time
import os

# ==========================
# CONFIGURAÇÕES
# ==========================
TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]
LISTA_FROTAS_ID = st.secrets["LISTA_FROTAS_ID"]

GRAPH_URL = "https://graph.microsoft.com/v1.0"
CAPACIDADE_MAXIMA = 15000
ARQUIVO_LOGO = "logo_ms.png"
ARQUIVO_VIDEO = "abertura.mp4"

USUARIOS = st.secrets["usuarios"]

# ==========================
# FUNÇÕES
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

def obter_dados_sharepoint(token, lista):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{lista}/items?expand=fields&$orderby=fields/Created desc&$top=2000"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers)
        return [item['fields'] for item in r.json().get('value', [])]
    except:
        return []

def enviar_dados_sharepoint(token, lista, dados):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{lista}/items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": dados}
    try:
        r = requests.post(url, headers=headers, json=payload)
        if not r.ok:
            erro = r.json().get("error", {}).get("message", r.text)
            st.error(f"Erro ao salvar ({r.status_code}): {erro}")
            return False
        return True
    except Exception as e:
        st.error(f"Erro de conexao: {e}")
        return False

@st.cache_data(ttl=300)
def carregar_frotas(token):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items?expand=fields&$top=5000"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers)
        itens = r.json().get("value", [])
        frotas = [i["fields"]["Title"] for i in itens if "Title" in i["fields"]]
        return sorted(set(frotas))
    except:
        return []

def preparar_dataframe(dados_sp):
    colunas = ['Tipo_Operacao', 'Litros', 'Frota', 'Horas_Motor',
               'Comboio_Final', 'Comboio_Inicial', 'Created', 'Entrada_Usina', 'Observacao']

    if not dados_sp:
        return pd.DataFrame(columns=colunas + ['Data_Dt', 'Hora'])

    df = pd.DataFrame(dados_sp)

    for col in colunas:
        if col not in df.columns:
            df[col] = 0

    df['Data_Dt'] = pd.to_datetime(df['Created'], errors='coerce').dt.date
    df['Hora'] = pd.to_datetime(df['Created'], errors='coerce').dt.strftime('%H:%M')

    for col in ['Litros', 'Horas_Motor', 'Comboio_Final', 'Comboio_Inicial', 'Entrada_Usina']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    return df

# ==================== NOVA FUNÇÃO ====================
def obter_ultimo_horimetro(df, frota):
    """Retorna o último horímetro registrado para uma frota específica (apenas Saídas)"""
    if df.empty or not frota:
        return 0.0
    df_frota = df[(df['Frota'] == frota) & (df['Tipo_Operacao'] == 'Saida')].copy()
    if df_frota.empty:
        return 0.0
    df_frota = df_frota.sort_values(by='Created', ascending=False)
    return float(df_frota.iloc[0]['Horas_Motor'])

# ==========================
# DESIGN
# ==========================
st.set_page_config(page_title="Gestão de Comboio", page_icon="🚛", layout="wide")

st.markdown("""
<style>
    .card-stock { padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px; }
    .stVideo { border-radius: 15px; width: 100%; max-height: 450px; }
</style>
""", unsafe_allow_html=True)

# ==========================
# LOGIN
# ==========================
if 'logado' not in st.session_state:
    st.session_state['logado'] = False

if not st.session_state['logado']:
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if os.path.exists(ARQUIVO_LOGO):
            st.image(ARQUIVO_LOGO, width=250)
        st.markdown("<h3 style='text-align:center;'>Sistema de Gestão de Comboio</h3>", unsafe_allow_html=True)
        if os.path.exists(ARQUIVO_VIDEO):
            st.video(ARQUIVO_VIDEO, autoplay=True, loop=True, muted=True)
        st.divider()
        u = st.text_input("Usuário", placeholder="ex: central, roraima...")
        s = st.text_input("Senha", type="password", placeholder="••••••••")
        if st.button("ACESSAR", type="primary", use_container_width=True):
            usuario = u.lower().strip()
            if usuario in USUARIOS and USUARIOS[usuario]["senha"] == s:
                st.session_state['logado'] = True
                st.session_state['usuario'] = usuario
                st.session_state['lista'] = USUARIOS[usuario]["lista"]
                st.session_state['nome'] = USUARIOS[usuario]["nome"]
                st.rerun()
            else:
                st.error("Usuário ou senha invalidos!")
    st.stop()

# ==========================
# SISTEMA PRINCIPAL
# ==========================
LISTA_ATUAL = st.session_state['lista']
NOME_UNIDADE = st.session_state['nome']

with st.sidebar:
    if os.path.exists(ARQUIVO_LOGO):
        st.image(ARQUIVO_LOGO, width=150)
    st.markdown(f"**{NOME_UNIDADE}**")
    st.markdown("---")
    if st.button("Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.title(f"Controle de Frotas - {NOME_UNIDADE}")

token = obter_token()
if not token:
    st.error("Erro de conexao com Microsoft Graph")
    st.stop()

dados_sp = obter_dados_sharepoint(token, LISTA_ATUAL)
df = preparar_dataframe(dados_sp)

saldo, ult_fim = 0, 0
if not df.empty and 'Tipo_Operacao' in df.columns:
    ent = df[df['Tipo_Operacao'] == 'Entrada']['Litros'].sum()
    sai = df[df['Tipo_Operacao'] == 'Saida']['Litros'].sum()
    saldo = ent - sai
    try:
        ult_fim = float(df.iloc[0]['Comboio_Final'])
    except:
        ult_fim = 0

# ==========================
# ABAS
# ==========================
aba1, aba2, aba3 = st.tabs(["Abastecer", "Entrada Usina", "Fechamento"])

# ==================== ABA ABASTECER (ATUALIZADA) ====================
with aba1:
    st.subheader("Registrar Saida")
    lista_frotas = [""] + carregar_frotas(token)

    with st.form("f_saida", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            f = st.selectbox("Frota", lista_frotas, key="select_frota")
            
            # Último horímetro registrado (somente leitura)
            ultimo_h = obter_ultimo_horimetro(df, f)
            col_ant1, col_ant2 = st.columns([3, 1])
            with col_ant1:
                st.markdown("**Horímetro Anterior da Frota**")
            with col_ant2:
                st.metric(label="", value=f"{ultimo_h:,.1f}", label_visibility="hidden")
            
            # Horímetro que o usuário digita
            h = st.number_input(
                "Horimetro Final (Atual)",
                min_value=0.0,
                step=0.1,
                format="%.1f"
            )
            
            # PRÉVIA + CHECKBOX DE REGRESSIVO
            aceitar_regressivo = False
            motivo_extra = ""
            
            if f:
                diferenca = h - ultimo_h
                
                if diferenca > 0:
                    st.success(f"✅ **Horas Rodadas:** {diferenca:,.1f} horas")
                
                elif diferenca < 0:
                    st.error(f"⚠️ **Horímetro Regressivo** em {-diferenca:,.1f} horas!")
                    
                    aceitar_regressivo = st.checkbox(
                        "✅ Permitir salvar mesmo com horímetro regressivo",
                        help="Marque APENAS em caso de troca de módulo, defeito ou troca de painel"
                    )
                    
                    if aceitar_regressivo:
                        motivo = st.selectbox(
                            "Motivo do horímetro regressivo:",
                            [
                                "Troca de Módulo / Horímetro",
                                "Horímetro com defeito",
                                "Troca de Painel",
                                "Outro"
                            ]
                        )
                        if motivo == "Outro":
                            motivo_extra = st.text_input("Descreva o motivo:")
                        else:
                            motivo_extra = motivo
                
                else:
                    st.warning("Nenhuma hora rodou ainda")

            l = st.number_input("Litros Abastecidos", min_value=0.0, step=1.0)

        with c2:
            st.info(f"Relogio Inicial: **{ult_fim:05.0f}**")
            sug = prever_odometro_final(ult_fim, l)
            st.caption(f"Sugestao Relogio: {sug:.0f}")
            f_od = st.number_input("Relogio Final (Lido)", format="%.0f", min_value=0.0)
            if f_od > 0:
                dif = calcular_diferenca_odometro(ult_fim, f_od)
                if abs(dif - l) > 2:
                    st.warning("Divergencia no relogio mecanico!")

        obs = st.text_area(
            "Observacao",
            placeholder="Ex: Veiculo terceiro - Transportadora XYZ / Pagamento posterior...",
            height=80
        )

        if st.form_submit_button("Salvar Registro", type="primary", use_container_width=True):
            if not f:
                st.error("Selecione uma frota valida.")
            elif saldo <= 0:
                st.error("Caminhao tanque sem estoque disponivel.")
            elif l > saldo:
                st.error(f"Estoque insuficiente. Saldo atual: {saldo:.0f} L")
            elif l <= 0 or f_od <= 0:
                st.error("Preencha os campos de litros e relógio final.")
            elif h < ultimo_h and not aceitar_regressivo:
                st.error("❌ Horímetro regressivo detectado! Marque o checkbox e informe o motivo.")
            elif h < ultimo_h and aceitar_regressivo and not motivo_extra:
                st.error("É obrigatório informar o motivo quando o horímetro é regressivo.")
            else:
                # Adiciona o motivo automaticamente na observação
                obs_final = obs.strip()
                if h < ultimo_h and aceitar_regressivo and motivo_extra:
                    obs_final = f"[HORÍMETRO REGRESSIVO - {motivo_extra}] {obs_final}".strip()

                with st.spinner("Enviando..."):
                    if enviar_dados_sharepoint(token, LISTA_ATUAL, {
                        "Title": f"Saida - {f}",
                        "Tipo_Operacao": "Saida",
                        "Frota": f,
                        "Litros": l,
                        "Horas_Motor": h,
                        "Comboio_Inicial": ult_fim,
                        "Comboio_Final": f_od,
                        "Observacao": obs_final
                    }):
                        st.success("Registrado com sucesso!")
                        time.sleep(1)
                        st.rerun()

# ==================== ABA ENTRADA USINA (sem alteração) ====================
with aba2:
    st.subheader("Carga do Tanque (Usina)")
    esp = CAPACIDADE_MAXIMA - saldo
    st.info(f"Espaco disponivel no tanque: **{esp:,.0f} L**")
    with st.form("f_ent", clear_on_submit=True):
        le = st.number_input("Quantidade Recebida (L)", min_value=0.0)
        o = st.text_input("Observacao / NF")
        if st.form_submit_button("Confirmar Entrada", use_container_width=True):
            if 0 < le <= esp:
                if enviar_dados_sharepoint(token, LISTA_ATUAL, {
                    "Title": "Entrada",
                    "Tipo_Operacao": "Entrada",
                    "Litros": le,
                    "Entrada_Usina": le,
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": ult_fim
                }):
                    st.success("Estoque Atualizado!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("Quantidade invalida ou acima da capacidade do tanque.")

# ==================== ABA FECHAMENTO (sem alteração) ====================
with aba3:
    st.header("Conferencia do Dia")
    ds = st.date_input("Filtrar Data", datetime.today())

    cor = "#28a745" if saldo > 5000 else "#ffc107" if saldo > 2000 else "#dc3545"
    st.markdown(
        f'<div style="background-color:{cor};" class="card-stock">'
        f'<h2>{saldo:,.0f} L</h2>Estoque Disponivel</div>',
        unsafe_allow_html=True
    )

    if df.empty:
        st.info("Nenhum registro encontrado para esta unidade.")
    else:
        df_d = df[df['Data_Dt'] == ds].copy()

        saidas_dia = df_d[df_d['Tipo_Operacao'] == 'Saida']
        s_sis = saidas_dia['Litros'].sum()
        s_mec = sum(
            calcular_diferenca_odometro(r.get('Comboio_Inicial', 0), r.get('Comboio_Final', 0))
            for _, r in saidas_dia.iterrows()
        )
        div = s_mec - s_sis

        col1, col2 = st.columns(2)
        col1.metric(f"Total Lancado ({ds.strftime('%d/%m')})", f"{s_sis:,.0f} L")
        col2.metric(
            "Diferenca (Mecanico vs Sistema)",
            f"{div:,.0f} L",
            delta="Verificar" if abs(div) > 5 else "OK"
        )

        if df_d.empty:
            st.info(f"Nenhum registro no dia {ds.strftime('%d/%m/%Y')}.")
        else:
            st.subheader("Relatorio de Movimentacao")
            colunas_exibir = [c for c in ['Hora', 'Tipo_Operacao', 'Frota', 'Litros', 'Comboio_Inicial', 'Comboio_Final', 'Observacao'] if c in df_d.columns]
            st.dataframe(df_d[colunas_exibir], use_container_width=True, hide_index=True)