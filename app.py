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
from cryptography.fernet import Fernet
import base64

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
    modelo_ia = genai.GenerativeModel('gemini-3.6-flash')
except Exception as e:
    modelo_ia = None
    erro_ia = str(e)

# --- MOTOR DE CRIPTOGRAFIA ---
try:
    fernet = Fernet(st.secrets["ENCRYPTION_KEY"])
except Exception:
    fernet = None

def criptografar(texto):
    if fernet and texto:
        return fernet.encrypt(str(texto).encode()).decode()
    return texto

def descriptografar(texto):
    if fernet and texto:
        try:
            return fernet.decrypt(str(texto).encode()).decode()
        except Exception:
            return texto 
    return texto

# --- OTIMIZAÇÃO 1: CACHE NAS MIGRAÇÕES E NOVAS TABELAS ---
@st.cache_resource
def inicializar_banco_dados():
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')
    c.execute('''CREATE TABLE IF NOT EXISTS investimentos (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), valor REAL, descricao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS va_config (usuario VARCHAR(255) PRIMARY KEY, saldo REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS va_transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), valor REAL, descricao TEXT)''')
    
    # NOVAS TABELAS PARA ASSINATURAS AUTOMÁTICAS
    c.execute('''CREATE TABLE IF NOT EXISTS assinaturas (id SERIAL PRIMARY KEY, usuario VARCHAR(255), nome VARCHAR(255), categoria VARCHAR(255), valor REAL, dia_vencimento INTEGER, conta VARCHAR(255), forma_pagamento VARCHAR(50))''')
    c.execute('''CREATE TABLE IF NOT EXISTS controle_assinaturas (usuario VARCHAR(255), mes_ano VARCHAR(20), PRIMARY KEY(usuario, mes_ano))''')

    def check_and_add_column(table, column, col_type, default_val):
        c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
        if not c.fetchone():
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

    check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
    check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
    check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')

inicializar_banco_dados()

# --- FUNÇÕES DE SEGURANÇA E DADOS ---
def gerar_hash(senha): return hashlib.sha256(str.encode(senha)).hexdigest()
def adicionar_usuario(usuario, senha): c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))
def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, desc_segura, conta, status, forma_pagamento))
    buscar_transacoes.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        linha_lista[5] = descriptografar(linha_lista[5])
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao): 
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))
    buscar_transacoes.clear()

def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    desc_segura = criptografar(descricao)
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, desc_segura, conta, status, forma_pagamento, id_transacao))
    buscar_transacoes.clear()

# FUNÇÕES DE ASSINATURAS RECORRENTES
def adicionar_assinatura(usuario, nome, categoria, valor, dia, conta, forma_pagamento):
    c.execute("INSERT INTO assinaturas (usuario, nome, categoria, valor, dia_vencimento, conta, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
              (usuario, nome, categoria, valor, dia, conta, forma_pagamento))
    buscar_assinaturas.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_assinaturas(usuario):
    c.execute("SELECT id, nome, categoria, valor, dia_vencimento, conta, forma_pagamento FROM assinaturas WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Nome', 'Categoria', 'Valor', 'Dia Venc.', 'Conta', 'Forma de Pagamento'])

def deletar_assinatura(id_ass): 
    c.execute("DELETE FROM assinaturas WHERE id = %s", (id_ass,))
    buscar_assinaturas.clear()

def verificar_e_lancar_assinaturas(usuario):
    hoje = datetime.today()
    mes_ano_atual = hoje.strftime('%m/%Y')
    
    # O GATILHO: Verifica se as assinaturas deste mês já foram lançadas
    c.execute("SELECT 1 FROM controle_assinaturas WHERE usuario = %s AND mes_ano = %s", (usuario, mes_ano_atual))
    if not c.fetchone():
        assinaturas = buscar_assinaturas(usuario)
        if not assinaturas.empty:
            for _, row in assinaturas.iterrows():
                dia = int(row['Dia Venc.'])
                ultimo_dia_mes = calendar.monthrange(hoje.year, hoje.month)[1]
                dia_real = min(dia, ultimo_dia_mes) # Proteção (Ex: se puser dia 31 e estivermos em fevereiro)
                data_lanc = f"{hoje.year}-{hoje.month:02d}-{dia_real:02d}"
                
                # Criptografar para a base de dados
                desc_segura = criptografar(row['Nome'] + " (Assinatura)")
                
                # Injeta automaticamente como pendente
                c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                          (usuario, data_lanc, "Despesa", row['Categoria'], row['Valor'], desc_segura, row['Conta'], "Pendente", row['Forma de Pagamento']))
            buscar_transacoes.clear()
        
        # Regista na tabela de controlo para não lançar 2 vezes no mesmo mês
        c.execute("INSERT INTO controle_assinaturas (usuario, mes_ano) VALUES (%s, %s)", (usuario, mes_ano_atual))

# Resto das funções
def adicionar_investimento(usuario, data, tipo, valor, descricao):
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO investimentos (usuario, data, tipo, valor, descricao) VALUES (%s, %s, %s, %s, %s)", (usuario, data, tipo, valor, desc_segura))
    buscar_investimentos.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_investimentos(usuario):
    c.execute("SELECT id, data, tipo, valor, descricao FROM investimentos WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        linha_lista[4] = descriptografar(linha_lista[4])
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Tipo', 'Valor', 'Descrição'])

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
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO va_transacoes (usuario, data, valor, descricao) VALUES (%s, %s, %s, %s)", (usuario, data, valor, desc_segura))
    buscar_transacoes_va.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes_va(usuario):
    c.execute("SELECT id, data, valor, descricao FROM va_transacoes WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        linha_lista[3] = descriptografar(linha_lista[3])
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Valor', 'Descrição'])

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
    
    # MOTOR AUTOMÁTICO DE ASSINATURAS! (Roda no milésimo de segundo que você entra)
    verificar_e_lancar_assinaturas(usuario)
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    
    # NOVA ABA "Fixas" NO MENU LATERAL
    aba_ia, aba_lancamento, aba_assinaturas, aba_va, aba_investimento = st.sidebar.tabs(["🤖 IA", "💸 Lançamentos", "🔄 Assinaturas", "🍔 VA", "📈 Investimentos"])
    
    with aba_ia:
        st.subheader("🤖 Assistente Inteligente")
        texto_usuario = st.text_input("Digite a transação (Ex: 'Gastei 50 no mercado no crédito')")
        
        if st.button("Processar com IA", type="primary"):
            if texto_usuario:
                with st.spinner("A pensar..."):
                    try:
                        model = genai.GenerativeModel('gemini-3.6-flash')
                        prompt_sistema = f'''
                        Você é um assistente financeiro. Extraia os dados da transação.
                        Devolva APENAS um JSON no seguinte formato:
                        {{"valor": 0.0, "categoria": "Alimentação", "tipo": "Despesa", "descricao": "Mercado", "metodo": "Cartão de Crédito"}}
                        Texto do usuário: {texto_usuario}
                        '''
                        resposta = model.generate_content(prompt_sistema)
                        texto_limpo = resposta.text.strip().replace("```json", "").replace("```", "")
                        dados_ia = json.loads(texto_limpo)
                        data_hoje = str(datetime.today().date())
                        
                        adicionar_transacao(
                            usuario=usuario, data=data_hoje, tipo=dados_ia.get("tipo", "Despesa"),
                            categoria=dados_ia.get("categoria", "Outros"), valor=float(dados_ia.get("valor", 0.0)),
                            descricao=dados_ia.get("descricao", "Lançamento Inteligente"), conta="Geral", 
                            status="Pago", forma_pagamento=dados_ia.get("metodo", "Débito")
                        )
                        st.success("Lançamento guardado e enviado para a tabela!")
                        st.rerun() 
                    except Exception as e:
                        st.error(f"Erro ao processar e guardar: {e}")

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
            
    # MENU LATERAL: CADASTRO DE ASSINATURAS
    with aba_assinaturas:
        st.subheader("🔄 Nova Assinatura")
        nome_ass = st.text_input("Serviço (Ex: Netflix)")
        val_ass = st.number_input("Mensalidade (R$)", min_value=0.01, format="%.2f", key="val_ass")
        dia_ass = st.number_input("Dia de Vencimento", min_value=1, max_value=31, value=10, key="dia_ass")
        cat_ass = st.selectbox("Categoria", ["Lazer", "Moradia", "Educação", "Saúde", "Outros"], key="cat_ass")
        conta_ass = st.selectbox("Conta", ["Nubank", "Itaú", "Inter", "Santander", "Caixa", "Geral"], key="conta_ass")
        forma_ass = st.selectbox("Forma de Pagto", ["Crédito", "Débito", "Pix", "Boleto"], key="forma_ass")
        
        if st.button("Registar Serviço", type="primary", use_container_width=True):
            if nome_ass:
                adicionar_assinatura(usuario, nome_ass, cat_ass, val_ass, dia_ass, conta_ass, forma_ass)
                st.success("Registado! Será lançado auto todo mês.")
                st.rerun()
            else:
                st.warning("Preencha o nome do serviço.")

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

    # --- CORPO DO DASHBOARD (AGORA COM ABA ASSINATURAS) ---
    st.title("📊 Maza Finance")
    aba_visao_geral, aba_assinaturas, aba_modulo_va, aba_carteira, aba_saude = st.tabs(["💰 Fluxo de Caixa", "🔄 Assinaturas", "🍔 Vale Alimentação", "💼 Investimentos", "🏆 Saúde Financeira"])
    
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
                with c4: st.metric("⚠️ A Pagar (Pendentes)", f"R$ {df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pendente')]['Valor'].sum():,.2f}")
                
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

                st.markdown("---")
                st.subheader("📄 Relatório Mensal em PDF")
                st.write("Exporte o seu extrato do mês com o resumo de indicadores para arquivo ou impressão.")
                
                from fpdf import FPDF
                import unicodedata

                def remover_acentos(texto):
                    return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn')

                try:
                    pdf = FPDF()
                    pdf.add_page()
                    
                    pdf.set_font("Arial", 'B', 16)
                    pdf.cell(200, 10, txt="Relatorio Financeiro Mensal", ln=True, align='C')
                    pdf.set_font("Arial", '', 12)
                    pdf.cell(200, 10, txt=f"Mes de Referencia: {mes_selecionado} | Maza Finance", ln=True, align='C')
                    pdf.ln(5)

                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(200, 8, txt=f"Total de Entradas: R$ {entradas_pagas:.2f}", ln=True)
                    pdf.cell(200, 8, txt=f"Total de Despesas: R$ {despesas_pagas:.2f}", ln=True)
                    pdf.cell(200, 8, txt=f"Saldo Liquido: R$ {entradas_pagas - despesas_pagas:.2f}", ln=True)
                    pdf.ln(5)

                    pdf.set_font("Arial", 'B', 10)
                    pdf.cell(22, 8, "Data", border=1, align='C')
                    pdf.cell(22, 8, "Tipo", border=1, align='C')
                    pdf.cell(40, 8, "Categoria", border=1, align='C')
                    pdf.cell(25, 8, "Valor", border=1, align='C')
                    pdf.cell(55, 8, "Descricao", border=1, align='C')
                    pdf.cell(26, 8, "Conta", border=1, align='C')
                    pdf.ln()

                    pdf.set_font("Arial", '', 8)
                    for idx, row in df_filtrado.iterrows():
                        data_f = pd.to_datetime(row['Data']).strftime('%d/%m/%Y')
                        pdf.cell(22, 8, data_f, border=1, align='C')
                        pdf.cell(22, 8, remover_acentos(row['Tipo']), border=1, align='C')
                        pdf.cell(40, 8, remover_acentos(row['Categoria'])[:20], border=1, align='C')
                        pdf.cell(25, 8, f"R$ {row['Valor']:.2f}", border=1, align='C')
                        pdf.cell(55, 8, remover_acentos(row['Descrição'])[:35], border=1, align='L')
                        pdf.cell(26, 8, remover_acentos(row['Conta'])[:12], border=1, align='C')
                        pdf.ln()

                    pdf_bytes = pdf.output(dest='S').encode('latin-1')

                    st.download_button(
                        label="⬇️ Baixar Relatório Mensal",
                        data=pdf_bytes,
                        file_name=f"Maza_Finance_Relatorio_{mes_selecionado.replace('/', '_')}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                except Exception as e:
                    st.error(f"Erro ao gerar PDF: {e}")

                st.markdown("---")
                with st.expander("✏️ Gerir Lançamentos (Editar ou Excluir)", expanded=False):
                    opcoes = df_filtrado['ID'].astype(str) + " - " + df_filtrado['Descrição'] + " (R$ " + df_filtrado['Valor'].astype(str) + ")"
                    escolha = st.selectbox("Selecione o Lançamento pelo ID ou Nome:", opcoes.tolist())
                    
                    if escolha:
                        id_selecionado = int(escolha.split(" - ")[0])
                        linha = df_filtrado[df_filtrado['ID'] == id_selecionado].iloc[0]
                        
                        aba_editar, aba_excluir = st.tabs(["✏️ Atualizar Dados", "🗑️ Apagar Registo"])
                        
                        with aba_editar:
                            c1, c2 = st.columns(2)
                            with c1:
                                n_tipo = st.selectbox("Tipo", ["Despesa", "Entrada"], index=0 if linha['Tipo']=="Despesa" else 1, key=f"tipo_{id_selecionado}")
                                
                                ops_cat = ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"]
                                n_cat = st.selectbox("Categoria", ops_cat, index=ops_cat.index(linha['Categoria']) if linha['Categoria'] in ops_cat else 10, key=f"cat_{id_selecionado}")
                                
                                n_valor = st.number_input("Valor (R$)", min_value=0.01, value=float(linha['Valor']), key=f"val_{id_selecionado}")
                                n_data = st.date_input("Data", pd.to_datetime(linha['Data']).date(), key=f"data_{id_selecionado}")
                                
                            with c2:
                                n_desc = st.text_input("Descrição", value=linha['Descrição'], key=f"desc_{id_selecionado}")
                                
                                ops_conta = ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra", "Geral"]
                                n_conta = st.selectbox("Conta", ops_conta, index=ops_conta.index(linha['Conta']) if linha['Conta'] in ops_conta else 9, key=f"conta_{id_selecionado}")
                                
                                n_status = st.selectbox("Status", ["Pago", "Pendente"], index=0 if linha['Status']=="Pago" else 1, key=f"status_{id_selecionado}")
                                
                                ops_forma = ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"]
                                n_forma = st.selectbox("Forma de Pagamento", ops_forma, index=ops_forma.index(linha['Forma de Pagamento']) if linha['Forma de Pagamento'] in ops_forma else 0, key=f"forma_{id_selecionado}")
                                
                            if st.button("💾 Guardar Alterações", type="primary", use_container_width=True, key=f"btn_salvar_{id_selecionado}"):
                                atualizar_transacao(id_selecionado, str(n_data), n_tipo, n_cat, n_valor, n_desc, n_conta, n_status, n_forma)
                                st.success("Atualizado com sucesso!")
                                st.rerun()
                                
                        with aba_excluir:
                            st.warning(f"Tem a certeza que quer apagar permanentemente **{linha['Descrição']}** (R$ {linha['Valor']})?")
                            if st.button("Sim, Excluir Lançamento", type="primary", use_container_width=True, key=f"btn_excluir_{id_selecionado}"):
                                deletar_transacao(id_selecionado)
                                st.error("Lançamento apagado!")
                                st.rerun()

    # NOVA ABA PRINCIPAL: GESTÃO DE ASSINATURAS
    with aba_assinaturas:
        st.subheader("🔄 Gestão de Contas Fixas e Assinaturas")
        st.write("Os serviços registados aqui serão lançados automaticamente no seu Extrato no início de cada mês com o status 'Pendente'.")
        
        df_ass = buscar_assinaturas(usuario)
        if df_ass.empty:
            st.info("Nenhuma assinatura registada. Use o menu lateral (🔄 Assinaturas) para adicionar a Netflix, Internet, Academia, etc.")
        else:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.metric("Total de Custos Fixos (Mês)", f"R$ {df_ass['Valor'].sum():,.2f}")
            with c2:
                st.data_editor(df_ass, hide_index=True, use_container_width=True, disabled=True)
                
            st.markdown("---")
            with st.expander("🗑️ Excluir Assinatura Automática", expanded=False):
                ops_ass = df_ass['ID'].astype(str) + " - " + df_ass['Nome']
                escolha_ass = st.selectbox("Selecione o serviço que deseja cancelar:", ops_ass.tolist())
                
                if escolha_ass:
                    id_ass_del = int(escolha_ass.split(" - ")[0])
                    st.warning("Ao apagar, este serviço não será mais lançado automaticamente nos próximos meses.")
                    if st.button("Confirmar Exclusão", type="primary", use_container_width=True):
                        deletar_assinatura(id_ass_del)
                        st.success("Assinatura removida do sistema automágico!")
                        st.rerun()

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
        if df_inv.empty: 
            st.info("Sem investimentos registados na sua carteira.")
        else:
            st.metric("Total Acumulado", f"R$ {df_inv['Valor'].sum():,.2f}")
            c1, c2 = st.columns([1, 1])
            with c1: 
                st.plotly_chart(px.pie(df_inv.groupby('Tipo')['Valor'].sum().reset_index(), values='Valor', names='Tipo', hole=0.4, template="plotly_dark"), use_container_width=True)
            with c2: 
                st.data_editor(df_inv, hide_index=True, use_container_width=True, disabled=True)

        st.markdown("---")
        st.subheader("🔮 Simulador de Rendimentos")
        st.write("Projete o crescimento do seu dinheiro ao longo do tempo com a magia dos juros compostos.")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            val_inicial = st.number_input("Valor Inicial (R$)", min_value=0.0, value=1000.0, step=100.0)
        with col2:
            aporte_mensal = st.number_input("Aporte Mensal (R$)", min_value=0.0, value=200.0, step=50.0)
        with col3:
            taxa_anual = st.number_input("Taxa Anual (%)", min_value=0.0, value=10.5, step=0.5, help="Ex: 10.5% ao ano (Aprox. Selic/CDI atual)")
        with col4:
            anos = st.number_input("Período (Anos)", min_value=1, max_value=50, value=5, step=1)

        taxa_mensal = (1 + taxa_anual / 100) ** (1 / 12) - 1
        meses = int(anos * 12)

        saldo = val_inicial
        total_investido = val_inicial
        dados_grafico = [{'Mês': 0, 'Total Investido': total_investido, 'Saldo Projetado': saldo}]

        for m in range(1, meses + 1):
            saldo = saldo * (1 + taxa_mensal) + aporte_mensal
            total_investido += aporte_mensal
            dados_grafico.append({'Mês': m, 'Total Investido': total_investido, 'Saldo Projetado': saldo})

        df_simulacao = pd.DataFrame(dados_grafico)

        rendimento_juros = saldo - total_investido
        st.markdown("##### Resultado da Simulação")
        rm1, rm2, rm3 = st.columns(3)
        with rm1: st.metric("💰 Total Investido (Do seu bolso)", f"R$ {total_investido:,.2f}")
        with rm2: st.metric("📈 Rendimento (Só em Juros)", f"R$ {rendimento_juros:,.2f}")
        with rm3: st.metric("🏆 Valor Final Estimado", f"R$ {saldo:,.2f}")

        fig_sim = px.area(
            df_simulacao, 
            x='Mês', 
            y=['Total Investido', 'Saldo Projetado'],
            labels={'value': 'Valor (R$)', 'variable': 'Curva'},
            template="plotly_dark",
            color_discrete_map={'Total Investido': '#4B5563', 'Saldo Projetado': '#00CC96'} 
        )
        
        fig_sim.update_layout(
            margin=dict(l=20, r=20, t=20, b=20), 
            hovermode="x unified",
            legend_title_text=''
        )
        st.plotly_chart(fig_sim, use_container_width=True)

    with aba_saude:
        st.subheader("🏆 Raio-X Financeiro")
        df_s = buscar_transacoes(usuario)
        if not df_s.empty:
            df_s['MesAno'] = pd.to_datetime(df_s['Data']).dt.strftime('%m/%Y')
            df_mes = df_s[df_s['MesAno'] == st.selectbox("Mês Saúde", sorted(df_s['MesAno'].unique().tolist(), reverse=True))]
            e, d = df_mes[df_mes['Tipo'] == 'Entrada']['Valor'].astype(float).sum(), df_mes[df_mes['Tipo'] == 'Despesa']['Valor'].astype(float).sum()
            
            sc = max(0, min(100, 50 + (30 if d <= e else -30) + (20 if (e - d) >= (e * 0.20) else 0) if e > 0 else 0))
            
            if e == 0: st.warning("Adicione Entradas para calcular a saúde.")
            elif sc >= 70: st.success("✅ Saúde Financeira Excelente!")
            elif sc >= 40: st.warning("⚠️ Saúde no limite. Atenção aos gastos.")
            else: st.error("🚨 Estado Crítico. Reduza as despesas!")
            
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
                margin=dict(l=20, r=20, t=30, b=20) 
            )
            
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("💡 Diagnóstico com IA")
            
            df_despesas_mes = df_mes[df_mes['Tipo'] == 'Despesa']
            if not df_despesas_mes.empty:
                top_categorias = df_despesas_mes.groupby('Categoria')['Valor'].sum().sort_values(ascending=False).head(3).to_dict()
                detalhe_gastos = f"Os 3 maiores gastos deste mês foram: {top_categorias}"
            else:
                detalhe_gastos = "O utilizador ainda não registou despesas neste mês."

            @st.cache_data(ttl=3600, show_spinner=False)
            def gerar_diagnostico_ia(score, entradas, despesas, top_gastos):
                try:
                    model = genai.GenerativeModel('gemini-3.6-flash')
                    prompt_consultor = f'''
                    Atue como um consultor financeiro experiente.
                    O seu cliente tem uma pontuação de saúde financeira de {score} (escala 0-100).
                    Neste mês: Entradas R$ {entradas:.2f} | Despesas R$ {despesas:.2f}.
                    {top_gastos}
                    
                    Escreva um diagnóstico curto e amigável:
                    1. Explique a pontuação de {score}.
                    2. Aponte os pontos fortes.
                    3. Dê 2 dicas de onde/como melhorar com base nas categorias onde ele mais gastou.
                    
                    Sem markdown exagerado, use bullet points. Fale de forma motivadora.
                    '''
                    resposta = model.generate_content(prompt_consultor)
                    return resposta.text
                except Exception as erro:
                    return f"Não foi possível carregar o diagnóstico: {erro}"

            with st.spinner("A gerar a sua análise personalizada..."):
                texto_diagnostico = gerar_diagnostico_ia(sc, e, d, detalhe_gastos)
                st.info(texto_diagnostico)
