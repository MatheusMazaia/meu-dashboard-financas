import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2 import IntegrityError
import hashlib
from datetime import datetime, timedelta
import calendar
import google.generativeai as genai
import json
from streamlit_mic_recorder import mic_recorder

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Maza Finance", layout="wide")

# --- CONEXÃO COM BANCO DE DADOS E IA ---
@st.cache_resource(ttl=300)
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

conn = init_connection()

try:
    conn.autocommit = True
    c = conn.cursor()
    c.execute("SELECT 1")
except (psycopg2.OperationalError, psycopg2.InterfaceError):
    st.cache_resource.clear()
    conn = init_connection()
    conn.autocommit = True
    c = conn.cursor()

# Configuração da IA Gemini
erro_ia = ""
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    modelo_ia = genai.GenerativeModel('gemini-1.5-pro')
except Exception as e:
    modelo_ia = None
    erro_ia = str(e)

# --- OTIMIZAÇÃO 1: CACHE NAS MIGRAÇÕES (Executa só 1x ao ligar o app) ---
@st.cache_resource
def inicializar_banco_dados():
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')
    c.execute('''CREATE TABLE IF NOT EXISTS investimentos (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), valor REAL, descricao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS va_config (usuario VARCHAR(255) PRIMARY KEY, saldo REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS va_transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), valor REAL, descricao TEXT)''')

    def check_and_add_column(table, column, col_type, default_val):
        c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
        if not c.fetchone():
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

    check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
    check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
    check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')

inicializar_banco_dados()

# --- FUNÇÕES DE SEGURANÇA ---
def gerar_hash(senha): return hashlib.sha256(str.encode(senha)).hexdigest()
def adicionar_usuario(usuario, senha): c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))
def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

# --- OTIMIZAÇÃO 2: CACHE NOS DADOS E LIMPEZA AUTOMÁTICA ---
def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento))
    buscar_transacoes.clear() # Limpa a memória para atualizar o gráfico

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao): 
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))
    buscar_transacoes.clear()

def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, descricao, conta, status, forma_pagamento, id_transacao))
    buscar_transacoes.clear()

def adicionar_investimento(usuario, data, tipo, valor, descricao): 
    c.execute("INSERT INTO investimentos (usuario, data, tipo, valor, descricao) VALUES (%s, %s, %s, %s, %s)", (usuario, data, tipo, valor, descricao))
    buscar_investimentos.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_investimentos(usuario):
    c.execute("SELECT id, data, tipo, valor, descricao FROM investimentos WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Tipo', 'Valor', 'Descrição'])

def deletar_investimento(id_inv): 
    c.execute("DELETE FROM investimentos WHERE id = %s", (id_inv,))
    buscar_investimentos.clear()

def salvar_config_va(usuario, saldo): 
    c.execute("INSERT INTO va_config (usuario, saldo) VALUES (%s, %s) ON CONFLICT (usuario) DO UPDATE SET saldo = EXCLUDED.saldo", (usuario, saldo))
    buscar_config_va.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_config_va(usuario):
    c.execute("SELECT saldo FROM va_config WHERE usuario = %s", (usuario,))
    res = c.fetchone()
    return res[0] if res else 0.0

def adicionar_transacao_va(usuario, data, valor, descricao): 
    c.execute("INSERT INTO va_transacoes (usuario, data, valor, descricao) VALUES (%s, %s, %s, %s)", (usuario, data, valor, descricao))
    buscar_transacoes_va.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes_va(usuario):
    c.execute("SELECT id, data, valor, descricao FROM va_transacoes WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Valor', 'Descrição'])

def deletar_transacao_va(id_transacao): 
    c.execute("DELETE FROM va_transacoes WHERE id = %s", (id_transacao,))
    buscar_transacoes_va.clear()

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day).date()

# --- SISTEMA DE SESSÃO ---
if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state: st.session_state['usuario_atual'] = ""

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Maza Finance")
    aba_login, aba_cadastro = st.tabs(["Fazer Login", "Criar Conta"])
    
    with aba_login:
        st.subheader("Acesso")
        # Criamos um 'form' para que a tecla ENTER funcione automaticamente
        with st.form("form_login"):
            usuario_login = st.text_input("Utilizador", key="login_user")
            senha_login = st.text_input("Palavra-passe", type="password", key="login_pass")
            botao_entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)
            
            if botao_entrar:
                user_limpo = usuario_login.strip().lower()
                if verificar_login(user_limpo, senha_login):
                    st.session_state['logado'] = True
                    st.session_state['usuario_atual'] = user_limpo
                    st.rerun()
                else: 
                    st.error("Credenciais incorretas!")
                
    with aba_cadastro:
        st.subheader("Nova Conta")
        # Aplicamos a mesma lógica de form para o registo
        with st.form("form_cadastro"):
            novo_usuario = st.text_input("Novo Utilizador")
            nova_senha = st.text_input("Nova Palavra-passe", type="password")
            botao_registar = st.form_submit_button("Registar", type="primary", use_container_width=True)
            
            if botao_registar:
                novo_user_limpo = novo_usuario.strip().lower()
                if novo_user_limpo == "" or nova_senha == "": 
                    st.warning("Preencha todos os campos.")
                else:
                    try:
                        adicionar_usuario(novo_user_limpo, nova_senha)
                        st.session_state['logado'] = True
                        st.session_state['usuario_atual'] = novo_user_limpo
                        st.success("Conta criada! A carregar...")
                        st.rerun()
                    except IntegrityError: 
                        st.error("Utilizador já existe.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    
    aba_ia, aba_lancamento, aba_va, aba_investimento = st.sidebar.tabs(["🤖 IA", "💸 Manual", "🍔 VA", "📈 Investir"])
    
    with aba_ia:
        st.subheader("🤖 Assistente Inteligente")
        texto_usuario = st.text_input("Digite a transação (Ex: 'Gastei 50 no mercado no crédito')")
        
        if st.button("Processar com IA", type="primary"):
            if texto_usuario:
                with st.spinner("A pensar..."):
                    try:
                        # Voltamos ao modelo super estável focado em texto
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        
                        prompt_sistema = f'''
                        Você é um assistente financeiro. Extraia os dados da transação.
                        Devolva APENAS um JSON no seguinte formato:
                        {{"valor": 0.0, "categoria": "Alimentação", "tipo": "Despesa", "descricao": "Mercado", "metodo": "Cartão de Crédito"}}
                        Texto do usuário: {texto_usuario}
                        '''
                        resposta = model.generate_content(prompt_sistema)
                        st.success("Processado com sucesso!")
                        st.json(resposta.text) # Pronto para ser ligado à função de gravar na base de dados
                    except Exception as e:
                        st.error(f"Erro na IA: {e}")

    with aba_lancamento:
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"], key="tipo_lanc")
        categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"], key="cat_lanc")
        conta_lancamento = st.selectbox("Conta", ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"], key="conta_lanc")
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"], key="forma_pag")
        status_lancamento = st.selectbox("Status", ["Pago", "Pendente"], key="status_lanc")
        data_lancamento = st.date_input("Data", datetime.today(), format="DD/MM/YYYY", key="data_lanc")
        valor_lancamento = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", key="valor_lanc")
        descricao_lancamento = st.text_input("Descrição", key="desc_lanc")
        
        eh_parcelado = st.checkbox("Compra Parcelada?", key="chk_parcela") if tipo_lancamento == "Despesa" else False
        parcelas = st.number_input("Parcelas", 2, 72, 2, key="num_parcelas") if eh_parcelado else 1
        
        if st.button("Guardar Manual", type="primary", use_container_width=True):
            valor_parcela = valor_lancamento / parcelas
            for i in range(parcelas):
                desc_parcela = f"{descricao_lancamento} ({i+1}/{parcelas})" if parcelas > 1 else descricao_lancamento
                adicionar_transacao(usuario, str(add_months(data_lancamento, i) if parcelas > 1 else data_lancamento), tipo_lancamento, categoria, valor_parcela, desc_parcela, conta_lancamento, status_lancamento, forma_pagamento)
            st.success("Lançamento guardado!")
            st.rerun()

    with aba_va:
        st.markdown("**1. Recarga do Mês**")
        novo_saldo_va = st.number_input("Valor Recebido VA (R$)", min_value=0.0, format="%.2f", value=float(buscar_config_va(usuario)), key="input_saldo_va")
        if st.button("Atualizar VA", use_container_width=True):
            salvar_config_va(usuario, novo_saldo_va)
            st.success("Atualizado!")
            st.rerun()
            
        st.markdown("---")
        data_va, valor_va, desc_va = st.date_input("Data Compra", datetime.today(), format="DD/MM/YYYY", key="d_va"), st.number_input("Valor (R$)", 0.01, format="%.2f", key="v_va"), st.text_input("Estabelecimento", key="des_va")
        if st.button("Guardar Gasto VA", type="primary", use_container_width=True):
            adicionar_transacao_va(usuario, str(data_va), valor_va, desc_va)
            st.success("Registado!")
            st.rerun()

    with aba_investimento:
        tipo_inv, data_inv, valor_inv, desc_inv = st.selectbox("Tipo", ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "FIIs", "Cripto", "Outros"]), st.date_input("Data", datetime.today(), format="DD/MM/YYYY"), st.number_input("Valor", 0.01, format="%.2f"), st.text_input("Descrição", key="d_inv")
        if st.button("Guardar Investimento", type="primary", use_container_width=True):
            adicionar_investimento(usuario, str(data_inv), tipo_inv, valor_inv, desc_inv)
            st.success("Investimento guardado!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Maza Finance")
    aba_visao_geral, aba_modulo_va, aba_carteira, aba_saude = st.tabs(["💰 Fluxo de Caixa", "🍔 Vale Alimentação", "💼 Investimentos", "🏆 Saúde Financeira"])
    
    with aba_visao_geral:
        df = buscar_transacoes(usuario)
        if df.empty: st.info("Sem lançamentos. Use o menu para adicionar!")
        else:
            df['Valor'] = df['Valor'].astype(float)
            df['Data_dt'] = pd.to_datetime(df['Data'])
            df['MesAno'] = df['Data_dt'].dt.strftime('%m/%Y')
            mes_selecionado = st.selectbox("📅 Mês", ["Todos os Meses"] + sorted(df['MesAno'].unique().tolist(), reverse=True))
            
            df_pendentes = df[df['Status'] == 'Pendente'].copy()
            if not df_pendentes.empty:
                df_pendentes['Data_Real'] = pd.to_datetime(df_pendentes['Data']).dt.date
                hoje = datetime.today().date()
                atrasadas, vencem_hoje, prox = df_pendentes[df_pendentes['Data_Real'] < hoje], df_pendentes[df_pendentes['Data_Real'] == hoje], df_pendentes[(df_pendentes['Data_Real'] > hoje) & (df_pendentes['Data_Real'] <= hoje + timedelta(days=5))]
                if not atrasadas.empty or not vencem_hoje.empty or not prox.empty:
                    st.subheader("📅 Central de Vencimentos")
                    c1, c2, c3 = st.columns(3)
                    with c1: 
                        if not atrasadas.empty: st.error(f"🔴 {len(atrasadas)} Atrasadas!\nR$ {atrasadas['Valor'].sum():.2f}")
                    with c2: 
                        if not vencem_hoje.empty: st.warning(f"🟡 {len(vencem_hoje)} Vencem HOJE!\nR$ {vencem_hoje['Valor'].sum():.2f}")
                    with c3: 
                        if not prox.empty: st.info(f"🔵 {len(prox)} em 5 dias\nR$ {prox['Valor'].sum():.2f}")
                    st.markdown("---")

            df_filtrado = df[df['MesAno'] == mes_selecionado] if mes_selecionado != "Todos os Meses" else df
            if not df_filtrado.empty:
                entradas_pagas, despesas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Entrada') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum(), df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("Entradas", f"R$ {entradas_pagas:,.2f}")
                with c2: st.metric("Despesas", f"R$ {despesas_pagas:,.2f}")
                with c3: st.metric("Saldo Atual", f"R$ {entradas_pagas - despesas_pagas:,.2f}")
                with c4: st.metric("⚠️ A Pagar", f"R$ {df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pendente')]['Valor'].sum():,.2f}")
                
                df_desp = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
                with st.expander("📉 Análise de Despesas", expanded=False):
                    g1, g2 = st.columns(2)
                    if not df_desp.empty:
                        res = df_desp.groupby('Categoria')['Valor'].sum().reset_index()
                        with g1: st.plotly_chart(px.pie(res, values='Valor', names='Categoria', hole=0.5, template="plotly_dark"), use_container_width=True)
                        with g2: st.plotly_chart(px.bar(res, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark"), use_container_width=True)
                            
                st.subheader("📋 Extrato")
                df_edit = df_filtrado.copy()
                df_edit['Data'] = pd.to_datetime(df_edit['Data']).dt.date
                st.data_editor(df_edit.drop(columns=['Data_dt', 'MesAno', 'Data_Real'], errors='ignore'), hide_index=True, use_container_width=True, disabled=True)

    with aba_modulo_va:
        st.subheader("🍔 Vale Alimentação")
        s_va, df_va = buscar_config_va(usuario), buscar_transacoes_va(usuario)
        df_va_f = df_va.copy()
        if not df_va.empty:
            df_va_f['MesAno'] = pd.to_datetime(df_va_f['Data']).dt.strftime('%m/%Y')
            m_va = st.selectbox("📅 Mês VA", ["Todos"] + sorted(df_va_f['MesAno'].unique().tolist(), reverse=True))
            df_va_f = df_va_f[df_va_f['MesAno'] == m_va] if m_va != "Todos" else df_va_f
        
        t_gasto = df_va_f['Valor'].sum() if not df_va_f.empty else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Recarga", f"R$ {s_va:.2f}")
        with c2: st.metric("Gasto", f"R$ {t_gasto:.2f}")
        with c3: st.metric("Disponível", f"R$ {s_va - t_gasto:.2f}")
        
        if s_va > 0:
            pct = min((t_gasto / s_va) * 100, 100)
            st.plotly_chart(px.bar(pd.DataFrame({'S': ['Gasto', 'Disp'], 'P': [pct, 100-pct]}), x='P', y=['VA','VA'], color='S', orientation='h', template="plotly_dark").update_layout(xaxis=dict(range=[0, 100])), use_container_width=True)
        if not df_va_f.empty: st.data_editor(df_va_f.drop(columns=['MesAno'], errors='ignore'), hide_index=True, use_container_width=True, disabled=True)

    with aba_carteira:
        st.subheader("💼 Património")
        df_inv = buscar_investimentos(usuario)
        if df_inv.empty: st.info("Sem investimentos.")
        else:
            st.metric("Total", f"R$ {df_inv['Valor'].sum():,.2f}")
            c1, c2 = st.columns([1, 1])
            with c1: st.plotly_chart(px.pie(df_inv.groupby('Tipo')['Valor'].sum().reset_index(), values='Valor', names='Tipo', hole=0.4, template="plotly_dark"), use_container_width=True)
            with c2: st.data_editor(df_inv, hide_index=True, use_container_width=True, disabled=True)

    with aba_saude:
        st.subheader("🏆 Raio-X Financeiro")
        df_s = buscar_transacoes(usuario)
        if not df_s.empty:
            df_s['MesAno'] = pd.to_datetime(df_s['Data']).dt.strftime('%m/%Y')
            df_mes = df_s[df_s['MesAno'] == st.selectbox("Mês Saúde", sorted(df_s['MesAno'].unique().tolist(), reverse=True))]
            e, d = df_mes[df_mes['Tipo'] == 'Entrada']['Valor'].astype(float).sum(), df_mes[df_mes['Tipo'] == 'Despesa']['Valor'].astype(float).sum()
            
            # Cálculo da pontuação
            sc = max(0, min(100, 50 + (30 if d <= e else -30) + (20 if (e - d) >= (e * 0.20) else 0) if e > 0 else 0))
            
            # Colocamos a mensagem de status no topo para não ser esmagada
            if e == 0: st.warning("Adicione Entradas para calcular a saúde.")
            elif sc >= 70: st.success("✅ Saúde Financeira Excelente!")
            elif sc >= 40: st.warning("⚠️ Saúde no limite. Atenção aos gastos.")
            else: st.error("🚨 Estado Crítico. Reduza as despesas!")
            
            # Gráfico com margens ajustadas para não cortar em ecrãs pequenos
            fig = go.Figure(go.Indicator(
                mode="gauge+number", 
                value=sc, 
                gauge={
                    'axis': {'range': [None, 100]}, 
                    'steps': [
                        {'range': [0, 40], 'color': "#EF553B"}, 
                        {'range': [40, 70], 'color': "#FFA15A"}, 
                        {'range': [70, 100], 'color': "#00CC96"}
                    ]
                }
            ))
            
            fig.update_layout(
                template="plotly_dark", 
                height=350,
                margin=dict(l=20, r=20, t=30, b=20) # Proteção contra cortes laterais
            )
            
            st.plotly_chart(fig, use_container_width=True)
