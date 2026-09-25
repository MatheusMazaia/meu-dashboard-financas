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
    aba_ia, aba_lancamento, aba_fixas, aba_va, aba_investimento = st.sidebar.tabs(["🤖 IA", "💸 Manual", "🔄 Fixas", "🍔 VA", "📈 Investir"])
    
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
                        texto_limpo = resposta.text.strip().replace("```json", "").replace("
